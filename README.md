# Toyota OBD2 CAN Bus Emulator

Emulates a Toyota ECU over a CAN bus using an **Arduino Nano + MCP2515** transceiver. A **Flask web app** lets you edit PID values in real time, watch the live CAN log, save sessions, and verify the emulator against a VLinker FS adapter — all from a browser on your local network.

---

## Hardware

| Part | Role |
|---|---|
| Arduino Nano | Runs the OBD2 emulator firmware |
| MCP2515 (HW-184, 8 MHz crystal) | CAN bus transceiver (SPI to Nano) |
| VLinker FS (optional) | ELM327-compatible USB adapter — used for the Verify mode only |

**Wiring (MCP2515 → Arduino Nano)**

| MCP2515 | Nano |
|---|---|
| VCC | 5V |
| GND | GND |
| CS | D10 |
| SO (MISO) | D12 |
| SI (MOSI) | D11 |
| SCK | D13 |
| INT | D2 |

Connect CANH/CANL between the MCP2515 and the VLinker FS CAN bus pins. A 120 Ω termination resistor across CANH/CANL is required at each end of the bus.

---

## Architecture

```
Browser ──HTTP──► Flask App  (webapp/app.py, port 5000)
                      │
                      ├── Read/write  webapp/config/pid_values.json
                      ├── SSE stream  live CAN log to browser
                      ├── USB Serial ──────────────────► Arduino Nano
                      │   (push updated PID values, read structured logs)
                      │
                      └── USB Serial ──► VLinker FS ──CAN──► MCP2515
                              (Verify mode only — separate USB port)
```

The Arduino has **two independent channels**:

- **USB serial** — Flask pushes updated PID values whenever you save in the editor; Arduino logs every CAN RX/TX event back over the same port.
- **CAN bus** — Arduino responds to OBD2 requests. The VLinker FS connects here only during Verify mode.

---

## Supported PIDs

| PID | Name | Unit | Default |
|---|---|---|---|
| 0x04 | Engine Load | % | 50.2 |
| 0x05 | Coolant Temperature | °C | 90 |
| 0x06 | Short Fuel Trim Bank 1 | % | 0.0 |
| 0x07 | Long Fuel Trim Bank 1 | % | 0.0 |
| 0x0B | Intake Manifold Pressure | kPa | 101 |
| 0x0C | Engine RPM | RPM | 2500 |
| 0x0D | Vehicle Speed | km/h | 35 |
| 0x0E | Timing Advance | ° | 10.0 |
| 0x0F | Intake Air Temperature | °C | 35 |
| 0x10 | MAF Air Flow Rate | g/s | 3.2 |
| 0x11 | Throttle Position | % | 9.8 |
| 0x2F | Fuel Tank Level | % | 65.1 |
| 0x33 | Barometric Pressure | kPa | 101 |
| 0x42 | Battery Voltage | V | 14.2 |
| 0x46 | Ambient Air Temperature | °C | 25 |
| 0x5C | Engine Oil Temperature | °C | 95 |

Also responds to Mode 09 PID 02 (VIN) and Mode 03 (DTCs — always returns clean).

---

## File Structure

```
OBD2_emulator/
├── platformio.ini            PlatformIO build config (Arduino Nano, 500 kbps)
├── src/
│   └── main.cpp              Arduino firmware
└── webapp/
    ├── app.py                Flask application (all routes)
    ├── pid_schema.py         PID metadata and human↔raw encoding
    ├── serial_manager.py     Background serial thread + SSE log stream
    ├── verify_runner.py      OBD2 verify logic (runs in background thread)
    ├── requirements.txt      pip install (use inside conda env)
    ├── environment.yml       conda environment definition
    ├── config/
    │   └── pid_values.json   Runtime PID config (edit via web UI)
    ├── logs/                 Saved session log files (auto-created)
    ├── static/
    │   ├── css/style.css
    │   └── js/
    │       ├── dashboard.js
    │       ├── pid_editor.js
    │       ├── log_viewer.js
    │       └── verify.js
    └── templates/
        ├── base.html
        ├── dashboard.html
        ├── pid_editor.html
        ├── log_files.html
        └── verify.html
```

---

## Setup

### 1. Flash the Arduino Firmware

Install [PlatformIO](https://platformio.org/) (CLI or VS Code extension), then:

```bash
# From the project root
pio run --target upload
```

The default upload port is `/dev/ttyUSB1` (set in `platformio.ini`). Change `upload_port` if your Nano is on a different port.

Open the serial monitor to confirm it's running:

```bash
pio device monitor --baud 115200
```

You should see:

```
========================================
 Toyota OBD2 CAN Emulator
 Arduino Nano + MCP2515 HW-184 8MHz
========================================
MCP2515 Init: OK
CAN Speed:    500 kbps
ECU ID:       0x7E8
Listening on: 0x7DF / 0x7E0
========================================
READY
```

> **Note:** Close the serial monitor before starting the Flask app — both cannot hold the port at the same time.

---

### 2. Set Up the Python Environment (conda)

```bash
cd webapp/

# Create and activate the conda environment
conda env create -f environment.yml
conda activate obd2-emulator
```

To update an existing environment after pulling changes:

```bash
conda env update -f environment.yml --prune
```

---

### 3. Run the Flask App

```bash
cd webapp/
conda activate obd2-emulator
python app.py
```

The app binds to `0.0.0.0:5000`. Open it from any machine on the same network:

```
http://<host-ip>:5000
```

---

## Web Interface

### Dashboard (`/`)

- **Port selector** — lists all `/dev/ttyUSB*` and `/dev/ttyACM*` ports with manufacturer and udevadm info so you can identify the correct one.
- **Connect** — opens the serial connection to the Arduino. Flask immediately pushes the current `pid_values.json` values and starts reading logs.
- **Live log table** — streams every CAN RX request and TX response with timestamps. Pause, clear, or save the session at any time.

### PID Editor (`/pids`)

- Edit any PID value in human-readable units (°C, RPM, %, V, etc.).
- Enable or disable individual PIDs.
- Edit the VIN string.
- **Save & Push to Arduino** — writes `pid_values.json` and immediately sends the new values to the Arduino over serial. No reflash needed.

### Log Files (`/logs`)

- Lists all saved session logs with timestamps and entry counts.
- Click any file to open a searchable, sortable DataTables view.
- Export as JSON or CSV, or delete individual files.

### Verify Mode (`/verify`)

Requires a **VLinker FS** (or compatible ELM327 USB adapter) plugged into the same machine on a separate USB port.

- Select the VLinker FS port from the dropdown (same udevadm info shown to help identify it).
- Set the number of poll cycles (default 20).
- **Run Verify** — connects to the ECU via the VLinker FS, runs a single-query snapshot first, then the reliability test.
- Results stream live: per-PID pass/fail, diff from expected, and a final reliability rate with a verdict (Excellent / Good / Fair / Poor).
- Expected values come from the current `pid_values.json` — so what you set in the PID Editor is exactly what gets tested.

---

## Serial Protocol Reference

The Flask app communicates with the Arduino over USB serial at **115200 baud**.

### Flask → Arduino

| Command | Description |
|---|---|
| `SET:04=128,0c=2500,10=320\n` | Update one or more PID raw values |
| `GET_VALUES\n` | Request a dump of all current values |

PID IDs are bare hex without `0x` prefix. Values are decimal integers in the same units as the Arduino's internal variables (see encoding table below).

### Arduino → Flask

| Output | Description |
|---|---|
| `OK\n` | Acknowledgement of a `SET` command |
| `VALUES:04=128,05=130,...\n` | Response to `GET_VALUES` |
| `[LOG] RX <can_id> <mode> <pid>` | Incoming CAN request |
| `[LOG] TX 7E8 <mode> <pid> <b0> <b1> <b2> <b3>` | Outgoing CAN response |
| `[LOG] ERR TX_FAIL <code>` | CAN send failure |
| `READY` | Arduino just booted — Flask auto-pushes current values |

Lines without a `[LOG]` prefix (startup banner) are displayed in the log but not parsed as structured entries.

### PID Raw Value Encoding

Flask always stores and displays values in human-readable units. It encodes them before sending to the Arduino:

| PID | Human Unit | Encoding (human → raw sent to Arduino) |
|---|---|---|
| 0x04 | % | `round(v * 255 / 100)` |
| 0x05 | °C | `round(v + 40)` |
| 0x06 | % | `round(v * 1.28 + 128)` |
| 0x07 | % | `round(v * 1.28 + 128)` |
| 0x0B | kPa | `round(v)` |
| 0x0C | RPM | `round(v)` *(Arduino internally multiplies ×4 for the CAN frame)* |
| 0x0D | km/h | `round(v)` |
| 0x0E | ° | `round((v + 64) * 2)` |
| 0x0F | °C | `round(v + 40)` |
| 0x10 | g/s | `round(v * 100)` |
| 0x11 | % | `round(v * 255 / 100)` |
| 0x2F | % | `round(v * 255 / 100)` |
| 0x33 | kPa | `round(v)` |
| 0x42 | V | `round(v * 1000)` |
| 0x46 | °C | `round(v + 40)` |
| 0x5C | °C | `round(v + 40)` |
