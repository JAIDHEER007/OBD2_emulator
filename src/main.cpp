// ============================================================
// Toyota OBD2 CAN Bus Emulator
// Hardware: Arduino Nano + MCP2515 (HW-184, 8MHz crystal)
// CAN Speed: 500kbps, Protocol: ISO 15765-4 (11-bit CAN)
// ECU Response ID: 0x7E8
// Responds to: 0x7DF (broadcast) and 0x7E0 (direct)
//
// Serial Protocol (from host Flask app):
//   SET:04=128,05=130,0C=2500,...\n  — update PID raw values
//   GET_VALUES\n                      — dump current values
//   OK\n                              — reply to SET
//
// Log output format (parsed by Flask):
//   [LOG] RX <can_id> <mode> <pid>
//   [LOG] TX <can_id> <mode> <pid> <b0> <b1> <b2> <b3>
//   [LOG] ERR TX_FAIL <error_code>
// ============================================================

#include <SPI.h>
#include <mcp_can.h>
#define CAN_CS_PIN  10
#define CAN_INT_PIN  2

MCP_CAN CAN(CAN_CS_PIN);

// ============================================================
// Forward Declarations
// ============================================================
void handleCANMessage();
void handleMode01(uint8_t pid);
void handleMode09(uint8_t pid);
void sendResponse(uint8_t b0, uint8_t b1, uint8_t b2, uint8_t b3,
                  uint8_t b4, uint8_t b5, uint8_t b6);
void sendVIN();
void parseSerial();
void applyValues(String csv);
void updatePidValue(uint8_t pid, long val);
void sendCurrentValues();

// ============================================================
// Simulated Engine Data — mutable, updated via serial from Flask
// Default values match the original hard-coded constants.
// Flask sends human values converted to these raw units:
//   0x04 engine_load = raw byte  (human% * 255/100)
//   0x0C rpm         = RPM value (Arduino multiplies x4 for CAN)
//   0x10 maf         = g/s * 100
//   0x42 battery_mv  = volts * 1000
// All others: direct raw byte value per OBD2 spec
// ============================================================
uint8_t  VAL_ENGINE_LOAD   = 128;   // 128/255*100 = 50.2%
uint8_t  VAL_COOLANT_TEMP  = 130;   // 130-40 = 90°C
uint8_t  VAL_FUEL_TRIM_S   = 128;   // (128-128)/1.28 = 0.0%
uint8_t  VAL_FUEL_TRIM_L   = 128;   // (128-128)/1.28 = 0.0%
uint8_t  VAL_MAP            = 101;   // 101 kPa
uint16_t VAL_RPM            = 2500;  // RPM (Arduino sends RPM*4 over CAN)
uint8_t  VAL_SPEED          = 35;    // km/h
uint8_t  VAL_TIMING_ADV    = 148;   // (148/2)-64 = 10.0°
uint8_t  VAL_INTAKE_TEMP   = 75;    // 75-40 = 35°C
uint16_t VAL_MAF            = 320;   // 320/100 = 3.2 g/s
uint8_t  VAL_THROTTLE       = 25;    // 25/255*100 = 9.8%
uint8_t  VAL_FUEL_LEVEL    = 166;   // 166/255*100 = 65.1%
uint8_t  VAL_BARO_PRESS    = 101;   // 101 kPa
uint16_t VAL_BATTERY_MV    = 14200; // 14200/1000 = 14.2V
uint8_t  VAL_AMBIENT_TEMP  = 65;    // 65-40 = 25°C
uint8_t  VAL_OIL_TEMP      = 135;   // 135-40 = 95°C

// Toyota VIN (Camry format)
const char VIN[] = "4T1BF3EK8AU123456"; // exactly 17 chars

// ============================================================
// Supported PID Bitmasks
// ============================================================
const uint32_t SUPP_PIDS_00 =
    (1UL << 28) |  // PID 04 engine load
    (1UL << 27) |  // PID 05 coolant temp
    (1UL << 26) |  // PID 06 short fuel trim B1
    (1UL << 25) |  // PID 07 long fuel trim B1
    (1UL << 21) |  // PID 0B MAP
    (1UL << 20) |  // PID 0C RPM
    (1UL << 19) |  // PID 0D speed
    (1UL << 18) |  // PID 0E timing advance
    (1UL << 17) |  // PID 0F intake temp
    (1UL << 16) |  // PID 10 MAF
    (1UL << 15) |  // PID 11 throttle pos
    (1UL <<  0);   // PID 20 — signals PIDs 21-40 group exists

const uint32_t SUPP_PIDS_20 =
    (1UL << 17) |  // PID 2F fuel level
    (1UL << 13) |  // PID 1F runtime
    (1UL <<  0);   // PID 40 — signals PIDs 41-60 group exists

const uint32_t SUPP_PIDS_40 =
    (1UL << 30) |  // PID 42 battery voltage
    (1UL << 26) |  // PID 46 ambient temp
    (1UL << 12);   // PID 5C oil temp

// ============================================================
// Serial command buffer
// ============================================================
String serialBuffer = "";

// ============================================================
void setup() {
    Serial.begin(115200);
    Serial.println(F("========================================"));
    Serial.println(F(" Toyota OBD2 CAN Emulator"));
    Serial.println(F(" Arduino Nano + MCP2515 HW-184 8MHz"));
    Serial.println(F("========================================"));

    while (CAN.begin(MCP_ANY, CAN_500KBPS, MCP_8MHZ) != CAN_OK) {
        Serial.println(F("MCP2515 init failed, retrying in 500ms..."));
        delay(500);
    }

    CAN.setMode(MCP_NORMAL);
    pinMode(CAN_INT_PIN, INPUT);

    Serial.println(F("MCP2515 Init: OK"));
    Serial.println(F("CAN Speed:    500 kbps"));
    Serial.println(F("ECU ID:       0x7E8"));
    Serial.println(F("Listening on: 0x7DF / 0x7E0"));
    Serial.println(F("========================================"));
    Serial.println(F("READY"));
}

// ============================================================
void loop() {
    if (digitalRead(CAN_INT_PIN) == LOW) {
        handleCANMessage();
    }
    parseSerial();
}

// ============================================================
// Serial Command Parser
// ============================================================
void parseSerial() {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (serialBuffer.length() > 0) {
                serialBuffer.trim();
                if (serialBuffer.startsWith(F("SET:"))) {
                    applyValues(serialBuffer.substring(4));
                    Serial.println(F("OK"));
                } else if (serialBuffer == F("GET_VALUES")) {
                    sendCurrentValues();
                }
                serialBuffer = "";
            }
        } else {
            if (serialBuffer.length() < 200) {
                serialBuffer += c;
            }
        }
    }
}

void applyValues(String csv) {
    int start = 0;
    while (start < (int)csv.length()) {
        int comma = csv.indexOf(',', start);
        if (comma == -1) comma = csv.length();
        String pair = csv.substring(start, comma);
        int eq = pair.indexOf('=');
        if (eq > 0) {
            String pidStr = pair.substring(0, eq);
            long val = pair.substring(eq + 1).toInt();
            uint8_t pid = (uint8_t)strtol(pidStr.c_str(), NULL, 16);
            updatePidValue(pid, val);
        }
        start = comma + 1;
    }
}

void updatePidValue(uint8_t pid, long val) {
    switch (pid) {
        case 0x04: VAL_ENGINE_LOAD  = (uint8_t)val;  break;
        case 0x05: VAL_COOLANT_TEMP = (uint8_t)val;  break;
        case 0x06: VAL_FUEL_TRIM_S  = (uint8_t)val;  break;
        case 0x07: VAL_FUEL_TRIM_L  = (uint8_t)val;  break;
        case 0x0B: VAL_MAP          = (uint8_t)val;  break;
        case 0x0C: VAL_RPM          = (uint16_t)val; break;
        case 0x0D: VAL_SPEED        = (uint8_t)val;  break;
        case 0x0E: VAL_TIMING_ADV   = (uint8_t)val;  break;
        case 0x0F: VAL_INTAKE_TEMP  = (uint8_t)val;  break;
        case 0x10: VAL_MAF          = (uint16_t)val; break;
        case 0x11: VAL_THROTTLE     = (uint8_t)val;  break;
        case 0x2F: VAL_FUEL_LEVEL   = (uint8_t)val;  break;
        case 0x33: VAL_BARO_PRESS   = (uint8_t)val;  break;
        case 0x42: VAL_BATTERY_MV   = (uint16_t)val; break;
        case 0x46: VAL_AMBIENT_TEMP = (uint8_t)val;  break;
        case 0x5C: VAL_OIL_TEMP     = (uint8_t)val;  break;
    }
}

void sendCurrentValues() {
    Serial.print(F("VALUES:"));
    Serial.print(F("04=")); Serial.print(VAL_ENGINE_LOAD);
    Serial.print(F(",05=")); Serial.print(VAL_COOLANT_TEMP);
    Serial.print(F(",06=")); Serial.print(VAL_FUEL_TRIM_S);
    Serial.print(F(",07=")); Serial.print(VAL_FUEL_TRIM_L);
    Serial.print(F(",0B=")); Serial.print(VAL_MAP);
    Serial.print(F(",0C=")); Serial.print(VAL_RPM);
    Serial.print(F(",0D=")); Serial.print(VAL_SPEED);
    Serial.print(F(",0E=")); Serial.print(VAL_TIMING_ADV);
    Serial.print(F(",0F=")); Serial.print(VAL_INTAKE_TEMP);
    Serial.print(F(",10=")); Serial.print(VAL_MAF);
    Serial.print(F(",11=")); Serial.print(VAL_THROTTLE);
    Serial.print(F(",2F=")); Serial.print(VAL_FUEL_LEVEL);
    Serial.print(F(",33=")); Serial.print(VAL_BARO_PRESS);
    Serial.print(F(",42=")); Serial.print(VAL_BATTERY_MV);
    Serial.print(F(",46=")); Serial.print(VAL_AMBIENT_TEMP);
    Serial.print(F(",5C=")); Serial.println(VAL_OIL_TEMP);
}

// ============================================================
// CAN Message Handler
// ============================================================
void handleCANMessage() {
    long unsigned int rxId;
    unsigned char len;
    unsigned char rxBuf[8];

    CAN.readMsgBuf(&rxId, &len, rxBuf);

    if (rxId != 0x7DF && rxId != 0x7E0) return;

    uint8_t mode = rxBuf[1];
    uint8_t pid  = rxBuf[2];

    Serial.print(F("[LOG] RX "));
    Serial.print(rxId, HEX);
    Serial.print(F(" "));
    Serial.print(mode, HEX);
    Serial.print(F(" "));
    Serial.println(pid, HEX);

    if      (mode == 0x01) handleMode01(pid);
    else if (mode == 0x09) handleMode09(pid);
    else if (mode == 0x03) {
        sendResponse(0x43, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00);
    }
}

// ============================================================
// Mode 01 — Current Data
// ============================================================
void handleMode01(uint8_t pid) {
    switch (pid) {

        case 0x00:
            sendResponse(0x41, 0x00,
                (SUPP_PIDS_00 >> 24) & 0xFF,
                (SUPP_PIDS_00 >> 16) & 0xFF,
                (SUPP_PIDS_00 >>  8) & 0xFF,
                 SUPP_PIDS_00        & 0xFF, 0x00);
            break;

        case 0x20:
            sendResponse(0x41, 0x20,
                (SUPP_PIDS_20 >> 24) & 0xFF,
                (SUPP_PIDS_20 >> 16) & 0xFF,
                (SUPP_PIDS_20 >>  8) & 0xFF,
                 SUPP_PIDS_20        & 0xFF, 0x00);
            break;

        case 0x40:
            sendResponse(0x41, 0x40,
                (SUPP_PIDS_40 >> 24) & 0xFF,
                (SUPP_PIDS_40 >> 16) & 0xFF,
                (SUPP_PIDS_40 >>  8) & 0xFF,
                 SUPP_PIDS_40        & 0xFF, 0x00);
            break;

        case 0x04:
            sendResponse(0x41, 0x04, VAL_ENGINE_LOAD, 0, 0, 0, 0);
            break;

        case 0x05:
            sendResponse(0x41, 0x05, VAL_COOLANT_TEMP, 0, 0, 0, 0);
            break;

        case 0x06:
            sendResponse(0x41, 0x06, VAL_FUEL_TRIM_S, 0, 0, 0, 0);
            break;

        case 0x07:
            sendResponse(0x41, 0x07, VAL_FUEL_TRIM_L, 0, 0, 0, 0);
            break;

        case 0x0B:
            sendResponse(0x41, 0x0B, VAL_MAP, 0, 0, 0, 0);
            break;

        case 0x0C: {
            uint16_t raw = VAL_RPM * 4;
            sendResponse(0x41, 0x0C, (raw >> 8) & 0xFF, raw & 0xFF, 0, 0, 0);
            break;
        }

        case 0x0D:
            sendResponse(0x41, 0x0D, VAL_SPEED, 0, 0, 0, 0);
            break;

        case 0x0E:
            sendResponse(0x41, 0x0E, VAL_TIMING_ADV, 0, 0, 0, 0);
            break;

        case 0x0F:
            sendResponse(0x41, 0x0F, VAL_INTAKE_TEMP, 0, 0, 0, 0);
            break;

        case 0x10:
            sendResponse(0x41, 0x10,
                (VAL_MAF >> 8) & 0xFF,
                 VAL_MAF       & 0xFF, 0, 0, 0);
            break;

        case 0x11:
            sendResponse(0x41, 0x11, VAL_THROTTLE, 0, 0, 0, 0);
            break;

        case 0x1F: {
            uint16_t rt = (uint16_t)(millis() / 1000);
            sendResponse(0x41, 0x1F, (rt >> 8) & 0xFF, rt & 0xFF, 0, 0, 0);
            break;
        }

        case 0x2F:
            sendResponse(0x41, 0x2F, VAL_FUEL_LEVEL, 0, 0, 0, 0);
            break;

        case 0x33:
            sendResponse(0x41, 0x33, VAL_BARO_PRESS, 0, 0, 0, 0);
            break;

        case 0x42:
            sendResponse(0x41, 0x42,
                (VAL_BATTERY_MV >> 8) & 0xFF,
                 VAL_BATTERY_MV       & 0xFF, 0, 0, 0);
            break;

        case 0x46:
            sendResponse(0x41, 0x46, VAL_AMBIENT_TEMP, 0, 0, 0, 0);
            break;

        case 0x5C:
            sendResponse(0x41, 0x5C, VAL_OIL_TEMP, 0, 0, 0, 0);
            break;

        default:
            break;
    }
}

// ============================================================
// Mode 09 — Vehicle Information
// ============================================================
void handleMode09(uint8_t pid) {
    switch (pid) {
        case 0x00:
            sendResponse(0x49, 0x00, 0x00, 0x00, 0x40, 0x00, 0x00);
            break;
        case 0x02:
            sendVIN();
            break;
        default:
            break;
    }
}

// ============================================================
// Send CAN Response + structured log
// ============================================================
void sendResponse(uint8_t b0, uint8_t b1,
                  uint8_t b2, uint8_t b3,
                  uint8_t b4, uint8_t b5, uint8_t b6) {
    uint8_t txBuf[8];
    txBuf[0] = 0x06;
    txBuf[1] = b0;
    txBuf[2] = b1;
    txBuf[3] = b2;
    txBuf[4] = b3;
    txBuf[5] = b4;
    txBuf[6] = b5;
    txBuf[7] = b6;

    delayMicroseconds(300);

    uint8_t result = CAN.sendMsgBuf(0x7E8, 0, 8, txBuf);

    if (result == CAN_OK) {
        Serial.print(F("[LOG] TX 7E8 "));
        Serial.print(b0, HEX);
        Serial.print(F(" "));
        Serial.print(b1, HEX);
        Serial.print(F(" "));
        Serial.print(b2, HEX);
        Serial.print(F(" "));
        Serial.print(b3, HEX);
        Serial.print(F(" "));
        Serial.print(b4, HEX);
        Serial.print(F(" "));
        Serial.println(b5, HEX);
    } else {
        Serial.print(F("[LOG] ERR TX_FAIL "));
        Serial.println(result);
    }
}

// ============================================================
// VIN Response — ISO-TP Multi-Frame
// ============================================================
void sendVIN() {
    uint8_t ff[8] = {
        0x10, 0x14,
        0x49, 0x02,
        0x01,
        (uint8_t)VIN[0],
        (uint8_t)VIN[1],
        (uint8_t)VIN[2]
    };
    CAN.sendMsgBuf(0x7E8, 0, 8, ff);
    delay(10);

    uint8_t cf1[8] = {
        0x21,
        (uint8_t)VIN[3],  (uint8_t)VIN[4],  (uint8_t)VIN[5],
        (uint8_t)VIN[6],  (uint8_t)VIN[7],  (uint8_t)VIN[8],
        (uint8_t)VIN[9]
    };
    CAN.sendMsgBuf(0x7E8, 0, 8, cf1);
    delay(10);

    uint8_t cf2[8] = {
        0x22,
        (uint8_t)VIN[10], (uint8_t)VIN[11], (uint8_t)VIN[12],
        (uint8_t)VIN[13], (uint8_t)VIN[14], (uint8_t)VIN[15],
        (uint8_t)VIN[16]
    };
    CAN.sendMsgBuf(0x7E8, 0, 8, cf2);
    Serial.println(F("[LOG] TX 7E8 49 02 VIN"));
}
