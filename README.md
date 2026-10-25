# Firm Reverse

Hypothesize, verify, revise. A phone and a logic analyzer turn any device into a spec you could rebuild it from.

Reverse engineering hardware usually takes about $10k of lab gear. We think a phone, one logic analyzer and a model that checks its own work get you most of the way. Firm Reverse runs in three stages on Gemini 4 Argon. Each stage is the same loop. Make a claim, try to prove it wrong, write down what changed and why. It ends with a clean room functional spec. It never copies firmware.

Built for the Gemini 4 Argon SF hackathon (More Dimensions track) by Iana Lin and Sissi Wang. Repo: https://github.com/ianalin123/firm-reverse

## The three stages

1. Camera guide. You take the shot it asks for. Argon looks at every photo and video so far, makes claims about the device, and cites the shot numbers behind each one. A claim is confirmed only when a shot shows it sharply. When a new shot contradicts a claim, it revises it and records the reason in `revisions`. Then it asks for exactly one next shot, the one that settles the weakest claim (flip the board, tilt to kill glare, film the LEDs while it boots). It warns before anything dangerous and lists the cheap kit you need with buy links. Once a chip is identified, a datasheet Managed Agent runs in the background, finds the manufacturer datasheet, cross checks the photo reading and lists the pins to probe by datasheet pin number.
2. Required Saleae probe step. Some things a camera cannot settle, like what is on the bus. Argon writes a wiring card: which Saleae channel goes to which pin (datasheet pin numbers), where the ground clip goes, the sample rate, and what to press while capturing. You export CSV from Logic 2 and upload it. It is decoded deterministically in plain Python (I2C, UART, NEC IR), not by a model. Every capture gets a `capture_check` against the identified device before it counts as evidence. Do the channels match the wiring, does the I2C address belong to a chip we can see, does the UART sit on UART pins. If it fits, it is the strongest evidence we have. If not, it is marked mismatch with the reason and kept out of every claim.
3. Verified 3D reconstruction. Argon writes a Three.js scene of the device (enclosure, PCB, ICs, connectors, buttons, LEDs) placed from the photos. Headless Chromium renders it. Argon gets the renders and the real shots in one call, scores the match, lists the mismatches and patches the scene code. It repeats until the score is high enough. The UI shows each pass with its render and critique.

When the parts, the board map and the behaviour are all settled and at least one capture is decoded, it writes the clean room spec. Parts with the shots and captures that prove them, the board map, the behaviour, the open questions.

## Real results from today

1. From one photo of an Arduino Uno it identified the board. A chip close up moved ATmega328P from likely to confirmed, with the reason recorded.
2. The probe step produced a real wiring card. Channel 0 to Digital Pin 0 RX (ATmega328P pin 30). Channel 1 to Pin 1 TX (pin 31). Channel 2 to Pin 13 (pin 17). Channel 3 to RESET (pin 29). Ground clip on GND. 16 MS/s.
3. The datasheet agent matched the ATmega328P and listed its I2C, UART and SPI pins.
4. The 3D loop went from a 76% match on pass 1 to 86% on pass 2 after it fixed the chip rotation and the USB shell.
5. A mismatched capture (a temperature sensor trace uploaded to the Arduino session) was flagged mismatch with the reason and rejected as evidence.

Camera turns take about 20 seconds. The datasheet agent takes about 3 minutes. The 3D loop takes about 6 minutes.

## How we used Gemini 4 Argon

- Every shot, every turn. Each turn calls `generate_content` on `gemini-4-argon` with every photo and video in the session uploaded through the Files API, labeled by shot number and the user's note. Up to 24 shots. Video is for behaviour over time.
- Structured state. The model replies in JSON with a fixed shape: device, confidence, claims with status and evidence, parts with chip markings, revisions, next step, safety warning, shopping list, capture checks. The previous state goes back in on the next turn so it builds on itself.
- Thinking level per job. `thinking_level` is medium for each verification turn and low for streaming the spec. No temperature setting.
- Managed Agent for datasheets. An Antigravity managed agent on `gemini-4-argon` with `background=True` searches the web for each part's datasheet while you keep shooting. Later turns and the spec cite what it found.
- 3D critique in one call. Each pass sends the renders and the real shots together, with `max_output_tokens` at 65536 so the full corrected scene fits in one reply.

## Run it

```fish
uv sync
echo "GEMINI_API_KEY=..." > .env.local
HOST=0.0.0.0 ALLOWED_HOSTS=(ipconfig getifaddr en0) uv run firm-reverse-serve
# open http://<laptop-ip>:8000 on your phone
```

Set `ACCESS_CODE` in the environment to gate a public deploy behind a code.

Docker:

```fish
docker build -t firm-reverse . && docker run -p 8000:8000 -e GEMINI_API_KEY=... firm-reverse
```

Saleae: capture in Logic 2, then File, Export Data, CSV. sigrok `.sr` and VCD files also load.

Tests: `uv run pytest -q` (37 tests).

## Built today vs reused

Built today: the Argon camera guide, the verification loop, the datasheet Managed Agent, the Saleae probe step with capture check, the 3D reconstruction loop, the UI and the deploy.

Reused: the deterministic decoder library (I2C, UART 8N1, NEC IR) and the offline Gemma bench at `/bench`, both from a prior project. The bench is not part of this submission.

## Team

Iana Lin and Sissi Wang. https://github.com/ianalin123/firm-reverse
