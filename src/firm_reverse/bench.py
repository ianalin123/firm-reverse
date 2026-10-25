"""The three bench steps: identify parts, explain signals, write the spec."""

import re
from dataclasses import dataclass
from pathlib import Path

from . import datasheets
from .analyze import Finding, analyze, summarize
from .llm import Gemma
from .loaders import load

SYSTEM = (
    "You are a hardware reverse engineering assistant on an offline lab bench. "
    "Be concrete and terse. Say 'unknown' instead of guessing. Plain text and Markdown only, never LaTeX."
)

MAX_PARTS = 8
PLACEHOLDER = re.compile(r"^(chip|ic|u|part)\s*\d*$|^unreadable$|^unknown$", re.IGNORECASE)

BOARD_PROMPT = (
    "This is a photo of a circuit board. List only the integrated circuits (black chips with legs or pads) "
    f"and crystals. Skip resistors, capacitors, connectors and board text. At most {MAX_PARTS} lines. "
    "One line per chip, exactly in this format:\n"
    "marking | kind | location\n"
    "marking is the text printed on the chip, copied character by character, or unreadable. "
    "kind is microcontroller, sensor, regulator, USB bridge, memory, driver, crystal or unknown. "
    "No other text."
)

CHIP_PROMPT = (
    "This is a close-up of one chip. One line, exactly in this format:\n"
    "marking | kind | location\n"
    "marking is the main part number printed on it, copied character by character. "
    "kind is your best guess of its function. location is close-up. No other text."
)


@dataclass
class Part:
    marking: str
    kind: str
    location: str
    datasheet: datasheets.Datasheet | None


def identify_parts(gemma: Gemma, photo: Path, close_up: bool = False, on_token=None) -> list[Part]:
    prompt = CHIP_PROMPT if close_up else BOARD_PROMPT
    budget = 40 if close_up else 30 * MAX_PARTS
    text = gemma.ask(prompt, image=photo, system=SYSTEM, on_token=on_token, max_output_tokens=budget, temperature=0.0)
    try:
        sheets = datasheets.load_index()
    except FileNotFoundError:
        sheets = []
    return [Part(m, k, loc, datasheets.lookup(m, sheets)) for m, k, loc in parse_part_lines(text)]


def parse_part_lines(text: str) -> list[tuple[str, str, str]]:
    """Parse 'marking | kind | location' lines, dropping duplicates the model loops on."""
    seen: set[tuple[str, str]] = set()
    parts = []
    for line in text.splitlines():
        cells = [c.strip(" `*-") for c in line.split("|")]
        if len(cells) < 2 or cells[0].lower() in ("", "marking"):
            continue
        marking, kind = cells[0], cells[1]
        location = cells[2] if len(cells) > 2 else ""
        if PLACEHOLDER.match(marking):
            continue
        key = (marking.lower(), location.lower())
        if key in seen:
            continue
        seen.add(key)
        parts.append((marking, kind, location))
    return parts[:MAX_PARTS]


def read_signals(capture: Path) -> tuple[list[Finding], str]:
    findings = analyze(load(capture))
    return findings, summarize(findings)


def parts_digest(parts: list[Part]) -> str:
    lines = []
    for p in parts:
        line = f"- {p.marking} ({p.kind}, {p.location})"
        if p.datasheet:
            line += f"\n  datasheet {p.datasheet.file}: {p.datasheet.excerpt[:400]}"
        lines.append(line)
    return "\n".join(lines) or "- no parts identified"


def explain_signals(gemma: Gemma, signal_summary: str, parts: str, on_token=None) -> str:
    prompt = (
        f"Parts on the board:\n{parts}\n\nDecoded bus traffic:\n{signal_summary}\n\n"
        "In 3 to 5 short bullet points, explain what the device is doing: which chip talks to which, "
        "what each message likely means, and how often."
    )
    return gemma.ask(prompt, system=SYSTEM, on_token=on_token, max_output_tokens=300)


def write_spec(gemma: Gemma, parts: str, signal_summary: str, explanation: str, on_token=None) -> str:
    prompt = (
        f"Parts:\n{parts}\n\nDecoded signals:\n{signal_summary}\n\nBehaviour:\n{explanation}\n\n"
        "Write a functional specification in Markdown with these sections: "
        "Overview, Bill of materials, Interfaces (protocol, pins, timing), Behaviour, "
        "Open questions. Only state what the evidence supports. "
        "This spec is for a clean-room redesign, so describe behaviour, not code."
    )
    return gemma.ask(prompt, system=SYSTEM, on_token=on_token, max_output_tokens=900)
