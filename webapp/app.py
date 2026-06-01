"""
OBD2 Emulator — Flask Web Application
Run: python app.py
Access: http://<host-ip>:5000
"""

import json
import os
import queue
import time
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, render_template, request, jsonify,
    Response, stream_with_context, send_file,
)

from pid_schema import PID_SCHEMA, PID_MAP
from serial_manager import manager as serial_mgr, list_usb_ports
from verify_runner import runner as verify_runner

# ------------------------------------------------------------------ #
# Paths                                                                 #
# ------------------------------------------------------------------ #
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config" / "pid_values.json"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)


# ------------------------------------------------------------------ #
# Config helpers                                                        #
# ------------------------------------------------------------------ #

def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ------------------------------------------------------------------ #
# Page routes                                                           #
# ------------------------------------------------------------------ #

@app.route("/")
def dashboard():
    return render_template("dashboard.html",
                           connected=serial_mgr.connected,
                           port=serial_mgr.port)


@app.route("/pids")
def pid_editor():
    return render_template("pid_editor.html")


@app.route("/logs")
def log_files():
    return render_template("log_files.html")


@app.route("/verify")
def verify():
    return render_template("verify.html",
                           verify_running=verify_runner.running)


# ------------------------------------------------------------------ #
# Port API                                                              #
# ------------------------------------------------------------------ #

@app.route("/api/ports")
def api_ports():
    return jsonify(list_usb_ports())


# ------------------------------------------------------------------ #
# Arduino serial API                                                    #
# ------------------------------------------------------------------ #

@app.route("/api/arduino/connect", methods=["POST"])
def api_arduino_connect():
    data = request.get_json(force=True)
    port = data.get("port", "").strip()
    if not port:
        return jsonify({"ok": False, "error": "No port specified"}), 400
    try:
        cfg = load_config()
        serial_mgr.connect(port, cfg)
        return jsonify({"ok": True, "port": port})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/arduino/disconnect", methods=["POST"])
def api_arduino_disconnect():
    serial_mgr.disconnect()
    return jsonify({"ok": True})


@app.route("/api/arduino/push", methods=["POST"])
def api_arduino_push():
    """Re-send current values to Arduino (useful after reconnect)."""
    cfg = load_config()
    ok = serial_mgr.push_values(cfg)
    return jsonify({"ok": ok})


@app.route("/api/arduino/status")
def api_arduino_status():
    return jsonify({
        "connected": serial_mgr.connected,
        "port": serial_mgr.port,
    })


# ------------------------------------------------------------------ #
# PID config API                                                        #
# ------------------------------------------------------------------ #

@app.route("/api/pids", methods=["GET"])
def api_pids_get():
    cfg = load_config()
    # Normalize all config keys to lowercase for lookup
    cfg_pids_lower = {k.lower(): v for k, v in cfg["pids"].items()}

    merged = []
    for schema in PID_SCHEMA:
        pid_lower = schema["pid"].lower()  # e.g. "0x04"
        entry = cfg_pids_lower.get(pid_lower, {
            "enabled": True,
            "human_value": schema["default"],
        })
        merged.append({
            **schema,
            "enabled": entry.get("enabled", True),
            "human_value": entry.get("human_value", schema["default"]),
        })

    return jsonify({
        "pids": merged,
        "vin": cfg.get("vin", "4T1BF3EK8AU123456"),
    })


@app.route("/api/pids", methods=["POST"])
def api_pids_save():
    data = request.get_json(force=True)
    cfg = load_config()

    for item in data.get("pids", []):
        pid_lower = item.get("pid", "").lower()  # normalize to "0x04"
        if pid_lower not in PID_MAP:
            continue
        cfg["pids"][pid_lower] = {
            "enabled": bool(item.get("enabled", True)),
            "human_value": float(item.get("human_value", 0)),
        }

    if "vin" in data:
        cfg["vin"] = str(data["vin"])[:17]

    save_config(cfg)
    serial_mgr.push_values(cfg)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ #
# Live log SSE                                                          #
# ------------------------------------------------------------------ #

@app.route("/api/log/stream")
def api_log_stream():
    """Server-Sent Events stream of live Arduino log entries."""
    q = serial_mgr.subscribe()

    @stream_with_context
    def generate():
        # Send a heartbeat comment every 15 s to keep the connection alive
        last_hb = time.time()
        try:
            while True:
                try:
                    entry = q.get(timeout=1)
                    payload = json.dumps(entry)
                    yield f"data: {payload}\n\n"
                except queue.Empty:
                    if time.time() - last_hb > 15:
                        yield ": heartbeat\n\n"
                        last_hb = time.time()
        finally:
            serial_mgr.unsubscribe(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/log/save", methods=["POST"])
def api_log_save():
    entries = serial_mgr.get_current_log()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"session_{ts}.json"
    path = LOGS_DIR / filename
    with open(path, "w") as f:
        json.dump({"saved_at": ts, "entries": entries}, f, indent=2)
    return jsonify({"ok": True, "filename": filename, "count": len(entries)})


@app.route("/api/log/clear", methods=["POST"])
def api_log_clear():
    serial_mgr.clear_log()
    return jsonify({"ok": True})


@app.route("/api/log/files")
def api_log_files():
    files = []
    for path in sorted(LOGS_DIR.glob("*.json"), reverse=True):
        stat = path.stat()
        try:
            with open(path) as f:
                data = json.load(f)
                count = len(data.get("entries", []))
        except Exception:
            count = 0
        files.append({
            "name": path.name,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "count": count,
        })
    return jsonify(files)


@app.route("/api/log/files/<filename>")
def api_log_file_get(filename: str):
    # Sanitize: only allow basename, no path traversal
    filename = Path(filename).name
    path = LOGS_DIR / filename
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/log/files/<filename>", methods=["DELETE"])
def api_log_file_delete(filename: str):
    filename = Path(filename).name
    path = LOGS_DIR / filename
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    path.unlink()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ #
# Verify API                                                            #
# ------------------------------------------------------------------ #

@app.route("/api/verify/start", methods=["POST"])
def api_verify_start():
    data = request.get_json(force=True)
    port = data.get("port", "").strip()
    cycles = int(data.get("cycles", 20))

    if not port:
        return jsonify({"ok": False, "error": "No port specified"}), 400

    cfg = load_config()
    ok = verify_runner.start(port, cycles, cfg)
    if not ok:
        return jsonify({"ok": False, "error": "Verify already running"}), 409
    return jsonify({"ok": True})


@app.route("/api/verify/stop", methods=["POST"])
def api_verify_stop():
    verify_runner.stop()
    return jsonify({"ok": True})


@app.route("/api/verify/stream")
def api_verify_stream():
    """SSE stream of verify progress events."""
    q = verify_runner.get_queue()

    @stream_with_context
    def generate():
        last_hb = time.time()
        while True:
            try:
                event = q.get(timeout=1)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
            except queue.Empty:
                if not verify_runner.running:
                    break
                if time.time() - last_hb > 15:
                    yield ": heartbeat\n\n"
                    last_hb = time.time()

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/verify/status")
def api_verify_status():
    return jsonify({"running": verify_runner.running})


# ------------------------------------------------------------------ #
# Entry point                                                           #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
