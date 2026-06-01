"""
PID metadata and human↔raw encoding/decoding.

Flask always works in human-readable units.
The Arduino stores values in the units listed under 'arduino_unit'.
Flask encodes before sending SET: commands; decodes GET_VALUES responses.
"""

PID_SCHEMA = [
    {
        "pid": "0x04",
        "name": "Engine Load",
        "unit": "%",
        "description": "Calculated engine load",
        "min": 0.0,
        "max": 100.0,
        "default": 50.2,
        "bytes": 1,
    },
    {
        "pid": "0x05",
        "name": "Coolant Temperature",
        "unit": "°C",
        "description": "Engine coolant temperature",
        "min": -40.0,
        "max": 215.0,
        "default": 90.0,
        "bytes": 1,
    },
    {
        "pid": "0x06",
        "name": "Short Fuel Trim Bank 1",
        "unit": "%",
        "description": "Short term fuel trim — Bank 1",
        "min": -100.0,
        "max": 99.2,
        "default": 0.0,
        "bytes": 1,
    },
    {
        "pid": "0x07",
        "name": "Long Fuel Trim Bank 1",
        "unit": "%",
        "description": "Long term fuel trim — Bank 1",
        "min": -100.0,
        "max": 99.2,
        "default": 0.0,
        "bytes": 1,
    },
    {
        "pid": "0x0B",
        "name": "Intake Manifold Pressure",
        "unit": "kPa",
        "description": "Intake manifold absolute pressure (MAP)",
        "min": 0.0,
        "max": 255.0,
        "default": 101.0,
        "bytes": 1,
    },
    {
        "pid": "0x0C",
        "name": "Engine RPM",
        "unit": "RPM",
        "description": "Engine revolutions per minute",
        "min": 0.0,
        "max": 16383.75,
        "default": 2500.0,
        "bytes": 2,
    },
    {
        "pid": "0x0D",
        "name": "Vehicle Speed",
        "unit": "km/h",
        "description": "Vehicle speed",
        "min": 0.0,
        "max": 255.0,
        "default": 35.0,
        "bytes": 1,
    },
    {
        "pid": "0x0E",
        "name": "Timing Advance",
        "unit": "°",
        "description": "Ignition timing advance for #1 cylinder",
        "min": -64.0,
        "max": 63.5,
        "default": 10.0,
        "bytes": 1,
    },
    {
        "pid": "0x0F",
        "name": "Intake Air Temperature",
        "unit": "°C",
        "description": "Intake air temperature",
        "min": -40.0,
        "max": 215.0,
        "default": 35.0,
        "bytes": 1,
    },
    {
        "pid": "0x10",
        "name": "MAF Air Flow Rate",
        "unit": "g/s",
        "description": "Mass air flow sensor rate",
        "min": 0.0,
        "max": 655.35,
        "default": 3.2,
        "bytes": 2,
    },
    {
        "pid": "0x11",
        "name": "Throttle Position",
        "unit": "%",
        "description": "Absolute throttle position",
        "min": 0.0,
        "max": 100.0,
        "default": 9.8,
        "bytes": 1,
    },
    {
        "pid": "0x2F",
        "name": "Fuel Tank Level",
        "unit": "%",
        "description": "Fuel tank level input",
        "min": 0.0,
        "max": 100.0,
        "default": 65.1,
        "bytes": 1,
    },
    {
        "pid": "0x33",
        "name": "Barometric Pressure",
        "unit": "kPa",
        "description": "Absolute barometric pressure",
        "min": 0.0,
        "max": 255.0,
        "default": 101.0,
        "bytes": 1,
    },
    {
        "pid": "0x42",
        "name": "Battery Voltage",
        "unit": "V",
        "description": "Control module voltage",
        "min": 0.0,
        "max": 65.535,
        "default": 14.2,
        "bytes": 2,
    },
    {
        "pid": "0x46",
        "name": "Ambient Air Temperature",
        "unit": "°C",
        "description": "Outside air temperature",
        "min": -40.0,
        "max": 215.0,
        "default": 25.0,
        "bytes": 1,
    },
    {
        "pid": "0x5C",
        "name": "Engine Oil Temperature",
        "unit": "°C",
        "description": "Engine oil temperature",
        "min": -40.0,
        "max": 215.0,
        "default": 95.0,
        "bytes": 1,
    },
]

# Map pid hex string → schema entry for fast lookup
PID_MAP = {p["pid"]: p for p in PID_SCHEMA}

# OBD2 obd-python command names used in verify mode
OBD_COMMAND_NAMES = {
    "0x04": "ENGINE_LOAD",
    "0x05": "COOLANT_TEMP",
    "0x06": "SHORT_FUEL_TRIM_1",
    "0x07": "LONG_FUEL_TRIM_1",
    "0x0B": "INTAKE_PRESSURE",
    "0x0C": "RPM",
    "0x0D": "SPEED",
    "0x0E": "TIMING_ADVANCE",
    "0x0F": "INTAKE_TEMP",
    "0x10": "MAF",
    "0x11": "THROTTLE_POS",
    "0x2F": "FUEL_LEVEL",
    "0x33": "BAROMETRIC_PRESSURE",
    "0x42": "CONTROL_MODULE_VOLTAGE",
    "0x46": "AMBIANT_AIR_TEMP",
    "0x5C": None,  # not in python-obd standard commands
}


def encode(pid_hex: str, human_val: float) -> int:
    """Convert human-readable value → Arduino raw integer for given PID."""
    v = float(human_val)
    p = pid_hex.lower()
    if p == "0x04":
        return round(v * 255 / 100)
    if p in ("0x05", "0x0f", "0x46", "0x5c"):
        return round(v + 40)
    if p in ("0x06", "0x07"):
        return round(v * 1.28 + 128)
    if p == "0x0b":
        return round(v)
    if p == "0x0c":
        return round(v)  # Arduino multiplies by 4 internally
    if p == "0x0d":
        return round(v)
    if p == "0x0e":
        return round((v + 64) * 2)
    if p == "0x10":
        return round(v * 100)
    if p == "0x11":
        return round(v * 255 / 100)
    if p == "0x2f":
        return round(v * 255 / 100)
    if p == "0x33":
        return round(v)
    if p == "0x42":
        return round(v * 1000)
    raise ValueError(f"Unknown PID: {pid_hex}")


def decode(pid_hex: str, raw_val: int) -> float:
    """Convert Arduino raw integer → human-readable value for given PID."""
    v = int(raw_val)
    p = pid_hex.lower()
    if p == "0x04":
        return round(v * 100 / 255, 3)
    if p in ("0x05", "0x0f", "0x46", "0x5c"):
        return float(v - 40)
    if p in ("0x06", "0x07"):
        return round((v - 128) / 1.28, 3)
    if p == "0x0b":
        return float(v)
    if p == "0x0c":
        return float(v)  # Arduino stores actual RPM
    if p == "0x0d":
        return float(v)
    if p == "0x0e":
        return round(v / 2 - 64, 1)
    if p == "0x10":
        return round(v / 100, 2)
    if p == "0x11":
        return round(v * 100 / 255, 3)
    if p == "0x2f":
        return round(v * 100 / 255, 3)
    if p == "0x33":
        return float(v)
    if p == "0x42":
        return round(v / 1000, 3)
    raise ValueError(f"Unknown PID: {pid_hex}")
