# CoreS3 I2C probe demo: flash and restore

Device: M5Stack CoreS3 Lite (ESP32-S3, 16 MB flash). Port: `/dev/cu.usbmodem101`.

## 1. Flash this sketch

```sh
arduino-cli upload -p /dev/cu.usbmodem101 --fqbn m5stack:esp32:m5stack_cores3 ~/firm-reverse/firmware/cores3_i2c_demo
```

Prebuilt binaries (from `arduino-cli compile --export-binaries`) are in
`build/m5stack.esp32.m5stack_cores3/`. To flash the exported merged image with esptool instead:

```sh
uv run --with esptool esptool.py --port /dev/cu.usbmodem101 --baud 921600 write_flash 0x0 ~/firm-reverse/firmware/cores3_i2c_demo/build/m5stack.esp32.m5stack_cores3/cores3_i2c_demo.ino.merged.bin
```

Serial output: 115200 baud. `arduino-cli monitor -p /dev/cu.usbmodem101 -c baudrate=115200`

## 0. Back up the current firmware FIRST (not yet done)

As of 2026-10-25 18:20 the CoreS3 was not enumerated on the Mac (no `/dev/cu.usbmodem*`,
empty USB tree), so no backup exists yet. Plug it in, then, before step 1:

```sh
uv run --with esptool esptool.py --port /dev/cu.usbmodem101 flash_id
uv run --with esptool esptool.py --port /dev/cu.usbmodem101 --baud 921600 read_flash 0 0x1000000 ~/firm-reverse/firmware/cores3_backup_$(date +%Y%m%d_%H%M).bin
```

Verify: file is exactly 16777216 bytes and `xxd <backup> | head` is not all `ff`.
Expect about 3 minutes at 921600 baud.

## 2. Restore the original firmware

The backup is a full 16 MB dump taken before flashing. Writing it back at offset 0 restores
bootloader, partition table, app, NVS and all other partitions exactly.

```sh
uv run --with esptool esptool.py --port /dev/cu.usbmodem101 --baud 921600 write_flash 0x0 ~/firm-reverse/firmware/cores3_backup_<YYYYMMDD_HHMM>.bin
```

After any esptool operation the board may sit in the bootloader; run
`uv run --with esptool esptool.py --port /dev/cu.usbmodem101 run` or unplug and replug it.

## Wiring

Grove Port A (red HY2.0-4P socket). Pin mapping confirmed from docs.m5stack.com/en/core/CoreS3
(`PORT.A SDA G2`, `PORT.A SCL G1`); pin order is the standard Grove convention:

| Pin | Signal | GPIO | Grove wire colour |
|-----|--------|------|-------------------|
| 1   | SCL    | G1   | yellow            |
| 2   | SDA    | G2   | white             |
| 3   | 5V     |      | red               |
| 4   | GND    |      | black             |

Logic analyzer: probe SCL on G1, SDA on G2, ground to GND. The bus runs at 100 kHz. Every
500 ms the sketch scans 0x08..0x77 (each a START, address+W, NACK, STOP) and then writes a
4-byte frame `DE AD BE EF` to 0x50, which NACKs when nothing is attached; both are decodable.

Internal bus (not on the Grove port): M-Bus connector on the bottom, `Int SDA G12` (M-Bus pin
17) and `Int SCL G11` (M-Bus pin 18). Devices on it per the M5 docs: AXP2101 0x34, AW88298
0x36, FT6336U 0x38, ES7210 0x40, BM8563 0x51, BMI270 0x69, LTR-553 0x23, GC0308 0x21,
AW9523B.
