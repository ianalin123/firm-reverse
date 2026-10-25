// Turns an Arduino Uno into a two-channel edge logger for `firm-reverse capture`.
// D2 and D3 are sampled on every change; each edge streams out as one CSV row.
// Good for demodulated IR (a 38 kHz receiver module), slow UART, and button lines.
// Resolution is 4 us, so raw 38 kHz carrier and fast I2C need a real analyzer.

const uint8_t CH_A = 2;
const uint8_t CH_B = 3;
const uint16_t BUF = 240;

volatile uint32_t stamps[BUF];
volatile uint8_t levels[BUF];
volatile uint16_t head = 0;
volatile uint16_t tail = 0;
volatile bool overflow = false;

void onEdge() {
  uint16_t next = (head + 1) % BUF;
  if (next == tail) {
    overflow = true;
    return;
  }
  stamps[head] = micros();
  levels[head] = (PIND >> 2) & 0b11;
  head = next;
}

void printRow(uint32_t us, uint8_t lv) {
  Serial.print(us / 1000000UL);
  Serial.print('.');
  uint32_t frac = us % 1000000UL;
  for (uint32_t d = 100000UL; d > 1 && frac < d; d /= 10) Serial.print('0');
  Serial.print(frac);
  Serial.print(',');
  Serial.print(lv & 1);
  Serial.print(',');
  Serial.println((lv >> 1) & 1);
}

void setup() {
  pinMode(CH_A, INPUT_PULLUP);
  pinMode(CH_B, INPUT_PULLUP);
  Serial.begin(500000);
  Serial.println("Time [s],D2,D3");
  printRow(micros(), (PIND >> 2) & 0b11);
  attachInterrupt(digitalPinToInterrupt(CH_A), onEdge, CHANGE);
  attachInterrupt(digitalPinToInterrupt(CH_B), onEdge, CHANGE);
}

void loop() {
  while (tail != head) {
    noInterrupts();
    uint32_t us = stamps[tail];
    uint8_t lv = levels[tail];
    tail = (tail + 1) % BUF;
    interrupts();
    printRow(us, lv);
  }
  if (overflow) {
    overflow = false;
    Serial.println("# overflow: edges dropped");
  }
}
