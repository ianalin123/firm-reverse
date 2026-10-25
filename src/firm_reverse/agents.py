"""Datasheet agent: one Antigravity managed agent call that finds and cross-checks every part's datasheet."""

import json
import os
import time
from collections.abc import Callable

from firm_reverse.guide import ARGON_MODEL, load_env_local

AGENT = os.environ.get("DATASHEET_AGENT", "antigravity-preview-09-2026")
POLL_SECONDS = 5.0
MAX_WAIT_SECONDS = 240.0
PENDING = ("queued", "in_progress")
VERDICTS = (True, False, "unknown")

PROMPT = """You are the datasheet agent for Firm Reverse, a camera-only hardware teardown guide.
A phone photo of a circuit board identified the parts below. For each part:
1. Search the web for its manufacturer datasheet. Prefer the manufacturer's own PDF URL.
2. From the datasheet extract the pinout, supply voltage range, interfaces (I2C, SPI, UART, USB, with pin numbers and names),
   and the package options.
3. Cross-check the photo reading. If the marking looks misread (wrong letter, truncated, a known variant), give the corrected marking.
   Set verified to true only when a real datasheet matches the marking and function, false when it clearly contradicts them,
   and "unknown" when you could not find a datasheet.
4. List the pins a logic analyzer should clip to in order to watch this part talk (name, pin number for the likely package, and why).

Parts from the photo:
{parts}

Reply with JSON only, no prose, matching this shape:
{{
  "parts": [{{
    "ref": "U1",
    "marking": "marking as the photo read it",
    "corrected_marking": "corrected marking or empty string",
    "verified": true,
    "part_number": "full manufacturer part number",
    "manufacturer": "...",
    "datasheet_url": "https://...",
    "package": "e.g. TQFP-32",
    "supply_voltage": "e.g. 1.8-5.5 V",
    "interfaces": [{{"kind": "I2C|SPI|UART|USB|other", "pins": ["PC4/SDA (27)", "PC5/SCL (28)"]}}],
    "key_specs": ["short facts worth knowing"],
    "probe_pins": [{{"pin": "PD1/TXD", "number": "31", "why": "UART transmit"}}],
    "notes": "anything the photo got wrong or could not settle"
  }}]
}}"""


def research_parts(parts: list[dict], client=None, on_status: Callable[[str], None] | None = None) -> list[dict]:
    if not parts:
        return []
    client = client or _default_client()
    notify = on_status or (lambda _message: None)
    notify(f"Datasheet agent searching for {len(parts)} part{'s' * (len(parts) != 1)}")
    interaction = client.interactions.create(
        agent=AGENT,
        agent_config={"type": "antigravity", "model": ARGON_MODEL},
        input=build_prompt(parts),
        environment="remote",
        background=True,
    )
    interaction = wait_for(client, interaction, notify)
    notify("Datasheet agent finished, cross-checking results")
    return merge(parts, parse_research(interaction.output_text or ""))


def build_prompt(parts: list[dict]) -> str:
    rows = [{key: part.get(key, "") for key in ("ref", "marking", "function", "package")} for part in parts]
    return PROMPT.format(parts=json.dumps(rows, indent=1))


def wait_for(client, interaction, notify: Callable[[str], None], max_wait: float = MAX_WAIT_SECONDS, poll: float = POLL_SECONDS):
    started = time.monotonic()
    while interaction.status in PENDING:
        elapsed = time.monotonic() - started
        if elapsed > max_wait:
            raise TimeoutError(f"datasheet agent still {interaction.status} after {max_wait:.0f}s (interaction {interaction.id})")
        notify(f"Datasheet agent {interaction.status.replace('_', ' ')} ({elapsed:.0f}s)")
        time.sleep(poll)
        interaction = client.interactions.get(id=interaction.id)
    if interaction.status != "completed":
        raise RuntimeError(f"datasheet agent ended {interaction.status}: {interaction.errors or 'no error detail'}")
    return interaction


def parse_research(text: str) -> list[dict]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"datasheet agent did not return JSON: {text[:200]!r}")
    found = json.loads(text[start : end + 1]).get("parts")
    if not isinstance(found, list):
        raise ValueError(f"datasheet agent JSON has no parts list: {text[:200]!r}")
    return [normalize(part) for part in found]


def normalize(part: dict) -> dict:
    for key in ("ref", "marking", "corrected_marking", "part_number", "manufacturer", "datasheet_url", "package", "supply_voltage", "notes"):
        part[key] = str(part.get(key) or "")
    for key in ("interfaces", "key_specs", "probe_pins"):
        part.setdefault(key, [])
    part["verified"] = coerce_verdict(part.get("verified"))
    return part


def coerce_verdict(value) -> bool | str:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return {"true": True, "yes": True, "false": False, "no": False}.get(text, "unknown")


def merge(parts: list[dict], found: list[dict]) -> list[dict]:
    """Keep the caller's order and refs; a part the agent skipped comes back unverified."""
    by_ref = {part["ref"]: part for part in found}
    missing = {"notes": "datasheet agent returned nothing for this part"}
    return [normalize({**part, **by_ref.get(part.get("ref", ""), missing)}) for part in parts]


def _default_client():
    from google import genai

    load_env_local()
    return genai.Client()
