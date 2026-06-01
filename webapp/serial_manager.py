"""
Serial communication manager for Arduino Nano.

Background thread reads structured [LOG] lines from the Arduino,
maintains a rolling deque of log entries, and provides SSE-compatible
event generators. Also handles pushing updated PID values to Arduino.
"""

import threading
import time
import queue
from collections import deque
from datetime import datetime

import serial
import serial.tools.list_ports

from pid_schema import encode


class SerialManager:
    MAX_LOG_ENTRIES = 2000
    BAUD = 115200
    READY_SIGNAL = "READY"

    def __init__(self):
        self._port = None
        self._serial = None
        self._thread = None
        self._stop_event = threading.Event()
        self._log = deque(maxlen=self.MAX_LOG_ENTRIES)
        self._sse_queues: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._connected = False
        self._current_pid_values: dict = {}

    # ------------------------------------------------------------------ #
    # Connection management                                                 #
    # ------------------------------------------------------------------ #

    def connect(self, port: str, pid_values: dict) -> None:
        """Open serial port and start background reader thread."""
        if self._connected:
            self.disconnect()

        self._current_pid_values = pid_values
        self._stop_event.clear()
        self._serial = serial.Serial(port, self.BAUD, timeout=1)
        self._port = port
        self._connected = True

        self._thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="serial-reader"
        )
        self._thread.start()

    def disconnect(self) -> None:
        """Stop reader thread and close serial port."""
        self._stop_event.set()
        self._connected = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None
        self._port = None

    @property
    def connected(self) -> bool:
        return self._connected and self._serial is not None and self._serial.is_open

    @property
    def port(self) -> str | None:
        return self._port

    # ------------------------------------------------------------------ #
    # Value push                                                            #
    # ------------------------------------------------------------------ #

    def push_values(self, pid_values: dict) -> bool:
        """Encode human values and send SET: command to Arduino."""
        self._current_pid_values = pid_values
        if not self.connected:
            return False

        parts = []
        for pid_hex, entry in pid_values["pids"].items():
            pid_lower = pid_hex.lower()  # ensure "0x04" form
            raw = encode(pid_lower, entry["human_value"])
            # Strip 0x prefix for serial command (e.g. "04=128")
            pid_id = pid_lower.replace("0x", "")
            parts.append(f"{pid_id}={raw}")

        cmd = "SET:" + ",".join(parts) + "\n"
        try:
            self._serial.write(cmd.encode("ascii"))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Log access                                                            #
    # ------------------------------------------------------------------ #

    def get_current_log(self) -> list:
        """Snapshot of the current in-memory log as a list of dicts."""
        with self._lock:
            return list(self._log)

    def clear_log(self) -> None:
        with self._lock:
            self._log.clear()

    # ------------------------------------------------------------------ #
    # SSE stream                                                            #
    # ------------------------------------------------------------------ #

    def subscribe(self) -> queue.Queue:
        """Register a new SSE consumer; returns a queue."""
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._sse_queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._sse_queues.remove(q)
            except ValueError:
                pass

    def _broadcast(self, entry: dict) -> None:
        """Push a log entry to all active SSE queues (non-blocking)."""
        with self._lock:
            dead = []
            for q in self._sse_queues:
                try:
                    q.put_nowait(entry)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._sse_queues.remove(q)

    # ------------------------------------------------------------------ #
    # Background reader                                                     #
    # ------------------------------------------------------------------ #

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._serial or not self._serial.is_open:
                break
            try:
                raw = self._serial.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", errors="replace").strip()
                if not line:
                    continue

                if self.READY_SIGNAL in line:
                    # Arduino just booted — push current values
                    time.sleep(0.1)
                    self.push_values(self._current_pid_values)

                entry = self._parse_line(line)
                with self._lock:
                    self._log.append(entry)
                self._broadcast(entry)

            except serial.SerialException:
                self._connected = False
                break
            except Exception:
                continue

    @staticmethod
    def _parse_line(line: str) -> dict:
        """Turn a serial line into a structured log entry."""
        ts = datetime.now().isoformat(timespec="milliseconds")
        base = {"ts": ts, "raw": line, "direction": None,
                "can_id": None, "mode": None, "pid": None, "data": []}

        if line.startswith("[LOG] RX"):
            parts = line.split()
            # [LOG] RX <can_id> <mode> <pid>
            base["direction"] = "RX"
            if len(parts) >= 5:
                base["can_id"] = parts[2]
                base["mode"] = parts[3]
                base["pid"] = parts[4]

        elif line.startswith("[LOG] TX"):
            parts = line.split()
            # [LOG] TX <can_id> <mode> <pid> [data bytes...]
            base["direction"] = "TX"
            if len(parts) >= 5:
                base["can_id"] = parts[2]
                base["mode"] = parts[3]
                base["pid"] = parts[4]
                base["data"] = parts[5:]

        elif line.startswith("[LOG] ERR"):
            base["direction"] = "ERR"
            base["raw"] = line

        return base


# ------------------------------------------------------------------ #
# Port listing                                                          #
# ------------------------------------------------------------------ #

def list_usb_ports() -> list[dict]:
    """Return ttyUSB ports with device info from udevadm."""
    import subprocess

    ports = []
    for p in sorted(serial.tools.list_ports.comports(), key=lambda x: x.device):
        if "ttyUSB" not in p.device and "ttyACM" not in p.device:
            continue
        info = {
            "device": p.device,
            "manufacturer": p.manufacturer or "",
            "description": p.description or "",
            "hwid": p.hwid or "",
            "udev": "",
        }
        try:
            result = subprocess.run(
                ["udevadm", "info", "-a", "-n", p.device],
                capture_output=True, text=True, timeout=3
            )
            lines = [
                ln.strip() for ln in result.stdout.splitlines()
                if any(k in ln for k in ("manufacturer", "product", "idVendor", "idProduct"))
            ]
            info["udev"] = " | ".join(lines[:4])
        except Exception:
            pass
        ports.append(info)
    return ports


# Module-level singleton
manager = SerialManager()
