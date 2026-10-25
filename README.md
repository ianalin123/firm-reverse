# Firm Reverse

An offline bench that reverse engineers a circuit board into a functional spec.
Point a camera at the board, clip probes on its buses, and get a spec a design team can rebuild from.
Gemma 4 runs on the device through LiteRT-LM. Nothing leaves the bench.

## How it works

1. **Signals (deterministic).** A capture from a logic analyzer (Saleae Logic 2 or Digilent WaveForms CSV, or any VCD) is decoded in plain Python: NEC infrared (with carrier detection), I2C, UART with auto baud. The model never sees raw samples, only a few lines of summary.
2. **Parts (Gemma vision).** Gemma reads chip markings from a board photo, then each marking is matched against a local datasheet library.
3. **Behaviour and spec (Gemma text).** Gemma combines the parts and the decoded traffic into an explanation and a clean-room functional spec.

## Setup

```fish
uv sync
# models (about 6 GB, gitignored)
mkdir -p models
curl -L -o models/gemma-4-E2B-it.litertlm https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/main/gemma-4-E2B-it.litertlm
curl -L -o models/gemma-4-E4B-it.litertlm https://huggingface.co/litert-community/gemma-4-E4B-it-litert-lm/resolve/main/gemma-4-E4B-it.litertlm
```

Datasheets: drop PDFs named by part number (for example `ATtiny85.pdf`) into `datasheets/`, then `uv run firm-reverse index`.

## Use

```fish
uv run firm-reverse synth                                   # demo captures in captures/demo
uv run firm-reverse signals captures/demo/sensor_board.csv  # no model needed
uv run firm-reverse parts board.jpg
uv run firm-reverse run captures/demo/sensor_board.csv --photo board.jpg --out spec.md
uv run firm-reverse ask "Say hi" --image board.jpg          # timing check on a new device
uv run firm-reverse-serve                                   # bench UI on :8000
```

`--model models/gemma-4-E4B-it.litertlm` swaps in the larger model. `--gpu` (or `FIRM_REVERSE_GPU=1` for the server) uses the GPU backend.

## Raspberry Pi 5

```fish
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone <this repo> firm-reverse; cd firm-reverse; uv sync
# copy models/ over from a laptop or the event USB drive; do not download on venue wifi
uv run firm-reverse ask "Say hi"
HOST=0.0.0.0 ALLOWED_HOSTS=$(hostname -I | cut -d' ' -f1) uv run firm-reverse-serve
```

The server binds to localhost by default and only answers to allowlisted host names (localhost, `*.local`, plus `ALLOWED_HOSTS`), so a `raspberrypi.local:8000` URL works without extra setup.

Then open `http://<pi-ip>:8000` from a laptop or phone. Capture on whichever machine runs the analyzer software, export CSV, and upload it in the page. Inference still happens on the Pi.

## Capturing

### No analyzer: an Arduino Uno

`firmware/uno_capture` turns an Uno into a two-channel edge logger on D2 and D3.
It covers demodulated IR, slow UART, and button lines. Use a real analyzer for raw 38 kHz carrier or I2C.

IR remote demo: wire a 38 kHz receiver module (VS1838B or TSOP38238) to 5V, GND, and D2. Then:

```fish
arduino-cli compile -b arduino:avr:uno firmware/uno_capture
arduino-cli upload -b arduino:avr:uno -p /dev/cu.usbmodem* firmware/uno_capture
uv run firm-reverse capture /dev/cu.usbmodem* --names IR,BTN --seconds 5   # press remote buttons while it records
uv run firm-reverse signals captures/uno.csv
```

### Logic analyzers

- **Saleae Logic 2:** File, Export Data, CSV, digital channels. Transition-only output loads directly.
- **Digilent WaveForms (Analog Discovery 3):** Logic tool, Export, CSV with the time column.
- Name channels in the software (SCL, SDA, IR, TX) so the spec uses real names.
