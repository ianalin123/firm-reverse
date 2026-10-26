// Firm Reverse probe demo for M5Stack CoreS3 (ESP32-S3).
// Generates decodable I2C traffic on Grove Port A every 500 ms for a logic analyzer,
// and reads the AXP2101 PMIC on the internal bus. Results go to Serial and the screen.
//
// Port A (HY2.0-4P Grove): SCL = G1, SDA = G2, 5V, GND.
// Internal bus (M-Bus, owned by M5Unified In_I2C): SCL = G11, SDA = G12.

#include <M5Unified.h>
#include <Wire.h>

static constexpr int PORT_A_SDA = 2;
static constexpr int PORT_A_SCL = 1;
static constexpr uint32_t PORT_A_HZ = 100000;
static constexpr uint8_t AXP2101_ADDR = 0x34;
static constexpr uint8_t PROBE_FRAME_ADDR = 0x50;
static constexpr uint32_t PERIOD_MS = 500;

// Peripheral 0: M5Unified's In_I2C takes peripheral 1 on ESP32-S3 (the global Wire1).
TwoWire portA(0);

uint32_t scanCount = 0;
String portAFound;
String internalFound;
uint8_t axpReg00 = 0;
uint16_t batteryMv = 0;

String scanTwoWire(TwoWire& bus) {
  String found;
  for (uint8_t addr = 0x08; addr <= 0x77; addr++) {
    bus.beginTransmission(addr);
    if (bus.endTransmission() == 0) {
      found += (found.length() ? " 0x" : "0x") + String(addr, HEX);
    }
  }
  return found.length() ? found : "none";
}

String scanInternalBus() {
  bool present[120] = {};
  M5.In_I2C.scanID(present);
  String found;
  for (uint8_t addr = 0x08; addr <= 0x77; addr++) {
    if (present[addr]) found += (found.length() ? " 0x" : "0x") + String(addr, HEX);
  }
  return found.length() ? found : "none";
}

// AXP2101 VBAT ADC: reg 0x34 bits[5:0] high, reg 0x35 bits[7:0] low, 1 mV per LSB.
uint16_t readAxpBatteryMv() {
  uint8_t raw[2] = {0, 0};
  if (!M5.In_I2C.readRegister(AXP2101_ADDR, 0x34, raw, 2, 400000)) return 0;
  return ((raw[0] & 0x3F) << 8) | raw[1];
}

// Deliberate frame to an absent address: START, 0x50+W, NACK, STOP is still decodable I2C.
void sendProbeFrame() {
  const uint8_t frame[4] = {0xDE, 0xAD, 0xBE, 0xEF};
  portA.beginTransmission(PROBE_FRAME_ADDR);
  portA.write(frame, sizeof(frame));
  uint8_t status = portA.endTransmission();
  Serial.printf("port A: probe frame to 0x%02X -> %s\n", PROBE_FRAME_ADDR, status == 0 ? "ACK" : "NACK");
}

void drawScreen() {
  auto& d = M5.Display;
  d.fillRect(0, 40, d.width(), d.height() - 40, TFT_BLACK);
  d.setCursor(8, 48);
  d.setTextColor(TFT_WHITE, TFT_BLACK);
  d.printf("scan #%lu\n\n", (unsigned long)scanCount);
  d.setTextColor(TFT_GREENYELLOW, TFT_BLACK);
  d.printf(" Port A (G2/G1): %s\n\n", portAFound.c_str());
  d.setTextColor(TFT_CYAN, TFT_BLACK);
  d.printf(" Internal: %s\n\n", internalFound.c_str());
  d.setTextColor(TFT_ORANGE, TFT_BLACK);
  d.printf(" AXP2101 reg00=0x%02X\n", axpReg00);
  d.printf(" battery %u mV\n", batteryMv);
}

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);
  Serial.begin(115200);

  portA.begin(PORT_A_SDA, PORT_A_SCL, PORT_A_HZ);
  portA.setTimeOut(20);

  auto& d = M5.Display;
  d.setRotation(1);
  d.fillScreen(TFT_BLACK);
  d.setTextSize(2);
  d.setTextColor(TFT_YELLOW, TFT_BLACK);
  d.setCursor(8, 8);
  d.println("Firm Reverse probe demo");
  d.drawFastHLine(0, 34, d.width(), TFT_DARKGREY);
  Serial.println("Firm Reverse probe demo: CoreS3 I2C traffic generator");
}

void loop() {
  M5.update();
  scanCount++;

  portAFound = scanTwoWire(portA);
  sendProbeFrame();
  internalFound = scanInternalBus();
  axpReg00 = M5.In_I2C.readRegister8(AXP2101_ADDR, 0x00, 400000);
  batteryMv = readAxpBatteryMv();

  Serial.printf("scan %lu | port A: found %s\n", (unsigned long)scanCount, portAFound.c_str());
  Serial.printf("internal: found %s\n", internalFound.c_str());
  Serial.printf("AXP2101 reg00=0x%02X\n", axpReg00);
  Serial.printf("battery mV=%u (M5Unified says %d)\n", batteryMv, M5.Power.getBatteryVoltage());

  drawScreen();
  delay(PERIOD_MS);
}
