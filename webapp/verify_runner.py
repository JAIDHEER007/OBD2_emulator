"""
OBD2 Verify Runner — adapted from obd_test.py.

Runs in a background thread, pushes progress events to a queue
that gets consumed by the /api/verify/stream SSE endpoint.
"""

import threading
import time
import queue
from datetime import datetime

import obd
from obd import OBDStatus

from pid_schema import PID_SCHEMA, OBD_COMMAND_NAMES


TOLERANCE = 0.5


class VerifyRunner:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._event_queue: queue.Queue = queue.Queue(maxsize=500)
        self.running = False

    def start(self, port: str, cycles: int, pid_values: dict) -> bool:
        """Start verify session in background thread. Returns False if already running."""
        if self.running:
            return False

        self._stop_event.clear()
        self.running = True
        self._event_queue = queue.Queue(maxsize=500)

        self._thread = threading.Thread(
            target=self._run,
            args=(port, cycles, pid_values),
            daemon=True,
            name="verify-runner"
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        self.running = False

    def get_queue(self) -> queue.Queue:
        return self._event_queue

    def _emit(self, event_type: str, data: dict) -> None:
        data["type"] = event_type
        data["ts"] = datetime.now().isoformat(timespec="milliseconds")
        try:
            self._event_queue.put_nowait(data)
        except queue.Full:
            pass

    def _run(self, port: str, cycles: int, pid_values: dict) -> None:
        try:
            self._emit("status", {"message": f"Connecting to VLinker FS on {port}..."})

            connection = obd.OBD(
                portstr=port,
                baudrate=115200,
                protocol="6",
                fast=False,
                timeout=5,
                check_voltage=False,
            )

            status = connection.status()
            protocol = connection.protocol_name()

            if status == OBDStatus.NOT_CONNECTED:
                self._emit("error", {"message": f"Could not connect on {port}. Check USB connection."})
                self.running = False
                return

            if status == OBDStatus.ELM_CONNECTED:
                self._emit("error", {
                    "message": "ELM connected but no ECU detected. Check Arduino power and CAN wiring."
                })
                self.running = False
                return

            self._emit("connected", {
                "message": f"Connected — Protocol: {protocol}",
                "protocol": protocol,
                "status": str(status),
            })

            # Build list of PIDs to test (enabled only, with OBD command)
            test_pids = self._build_test_pids(pid_values)

            if not test_pids:
                self._emit("error", {"message": "No enabled PIDs with supported OBD commands."})
                connection.close()
                self.running = False
                return

            self._emit("status", {"message": f"Testing {len(test_pids)} PIDs × {cycles} cycles..."})

            # Run snapshot first
            snapshot = self._run_snapshot(connection, test_pids)
            self._emit("snapshot_done", {"results": snapshot})

            # Reliability cycles
            stats = {p["pid"]: {"attempts": 0, "correct": 0, "no_resp": 0, "wrong": 0}
                     for p in test_pids}

            for cycle in range(1, cycles + 1):
                if self._stop_event.is_set():
                    break

                cycle_pass = 0
                for tp in test_pids:
                    if self._stop_event.is_set():
                        break

                    resp = connection.query(tp["cmd"])
                    stats[tp["pid"]]["attempts"] += 1
                    expected = tp["expected"]

                    if resp.is_null():
                        stats[tp["pid"]]["no_resp"] += 1
                    else:
                        actual = _get_float(resp)
                        if actual is not None and abs(actual - expected) <= TOLERANCE:
                            stats[tp["pid"]]["correct"] += 1
                            cycle_pass += 1
                        else:
                            stats[tp["pid"]]["wrong"] += 1

                self._emit("cycle", {
                    "cycle": cycle,
                    "total": cycles,
                    "pass": cycle_pass,
                    "pid_count": len(test_pids),
                })

                time.sleep(0.5)

            # Final report
            report = self._build_report(stats, test_pids)
            self._emit("done", {"report": report})
            connection.close()

        except Exception as e:
            self._emit("error", {"message": str(e)})
        finally:
            self.running = False

    def _build_test_pids(self, pid_values: dict) -> list:
        """Return list of {pid, name, expected, unit, cmd} for enabled PIDs."""
        # Normalize config keys to lowercase for lookup
        cfg_lower = {k.lower(): v for k, v in pid_values["pids"].items()}
        result = []
        for schema in PID_SCHEMA:
            pid_lower = schema["pid"].lower()  # e.g. "0x04"
            entry = cfg_lower.get(pid_lower)
            if not entry or not entry.get("enabled", True):
                continue

            cmd_name = OBD_COMMAND_NAMES.get(schema["pid"].lower())
            if cmd_name is None:
                continue

            cmd = getattr(obd.commands, cmd_name, None)
            if cmd is None:
                continue

            result.append({
                "pid": schema["pid"],
                "name": schema["name"],
                "unit": schema["unit"],
                "expected": entry["human_value"],
                "cmd": cmd,
                "cmd_name": cmd_name,
            })
        return result

    def _run_snapshot(self, connection, test_pids: list) -> list:
        results = []
        for tp in test_pids:
            if self._stop_event.is_set():
                break
            resp = connection.query(tp["cmd"])
            actual = None if resp.is_null() else _get_float(resp)
            expected = tp["expected"]
            passed = (
                actual is not None and abs(actual - expected) <= TOLERANCE
            )
            results.append({
                "pid": tp["pid"],
                "name": tp["name"],
                "unit": tp["unit"],
                "expected": expected,
                "actual": actual,
                "diff": round(abs(actual - expected), 4) if actual is not None else None,
                "status": "PASS" if passed else ("NO_RESP" if actual is None else "FAIL"),
            })
            time.sleep(0.05)
        return results

    @staticmethod
    def _build_report(stats: dict, test_pids: list) -> list:
        report = []
        for tp in test_pids:
            s = stats[tp["pid"]]
            attempts = s["attempts"]
            rate = (s["correct"] / attempts * 100) if attempts > 0 else 0
            report.append({
                "pid": tp["pid"],
                "name": tp["name"],
                "attempts": attempts,
                "correct": s["correct"],
                "no_resp": s["no_resp"],
                "wrong": s["wrong"],
                "rate": round(rate, 1),
            })
        return report


def _get_float(response) -> float | None:
    if response.is_null():
        return None
    try:
        return float(response.value.magnitude)
    except Exception:
        try:
            return float(str(response.value).split()[0])
        except Exception:
            return None


# Module-level singleton
runner = VerifyRunner()
