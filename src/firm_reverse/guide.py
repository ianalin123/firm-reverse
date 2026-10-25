"""Camera-only guided teardown on Gemini 4 Argon.

Each turn the model sees every photo and video so far, updates its hypotheses about the device,
checks them against the evidence, and asks for the one shot that would settle the weakest claim.
"""

import json
import mimetypes
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env.local"
ARGON_MODEL = os.environ.get("ARGON_MODEL", "gemini-4-argon")
MAX_SHOTS = 24
MAX_MESSAGES = 40

SYSTEM = """You are Firm Reverse, a hardware reverse engineering guide for people who only have a phone camera.
The user films and photographs a device; you work out what it is, how it is built, and how it behaves,
then hand them a clean-room functional spec they could rebuild from. Never reproduce firmware or copy code.

Every turn:
1. Look at every shot, including earlier ones. Update your hypotheses about the device, its parts, and its behaviour.
2. Verify: for each claim, cite the shot numbers that show it. Mark a claim confirmed only when a shot shows it sharply and
   legibly. A chip marking you can only partly read, or a part you infer from layout, is at most likely.
   If a newer shot contradicts an earlier claim, revise it and say so in `revisions`.
3. Ask for exactly one next shot: the one that would most raise confidence in the weakest important claim.
   Be concrete about framing, angle, lighting, distance and what to do (open the case, flip the board, press a button,
   film the LEDs while it boots, tilt to kill glare on a chip marking). Prefer video when behaviour over time matters.
4. Safety first. If the device is mains powered, has a large capacitor, a lithium cell, a CRT or a microwave magnetron,
   say exactly what not to touch and do not ask them to open powered mains equipment.
5. Shopping list: name the tools or parts they would need for the next steps (driver bits by exact size, spudger,
   a 38 kHz IR receiver, a logic analyzer only if the camera cannot answer the question). Keep it short and cheap.
6. If the user sent a message, answer it plainly in `reply` (one to three sentences), then carry on guiding.
7. When the parts, the board map and the behaviour are all confirmed or clearly unanswerable by camera, set next.kind to "done".

Reply with JSON only, matching this shape:
{
  "device": "best guess at what this is",
  "confidence": 0.0,
  "observations": ["what is new in the latest shot"],
  "claims": [{"claim": "...", "status": "confirmed|likely|unknown", "evidence": [1, 3]}],
  "revisions": ["claims you changed this turn and why"],
  "parts": [{"ref": "U1", "marking": "text on the chip or unreadable", "function": "...", "evidence": [2]}],
  "next": {"kind": "photo|video|probe|done", "instruction": "one or two sentences", "why": "which claim it settles"},
  "safety": "warning or empty string",
  "shopping_list": [{"item": "...", "why": "...", "approx_usd": 0, "search": "exact product search phrase"}],
  "reply": "answer to the user's latest message, or empty string"
}"""

SPEC_PROMPT = """Write the clean-room functional spec for this device in Markdown, from every shot and the final state below.
Sections: Overview, Bill of materials (with the shot numbers that show each part), Board map, Interfaces,
Behaviour (with timings seen in video), Rebuild notes, Open questions (what a camera could not settle, and which tool would).
Only state what the evidence supports. Describe behaviour, never code.

Final state:
"""


@dataclass
class Shot:
    index: int
    path: Path
    mime: str
    note: str
    uploaded: object = None


@dataclass
class Session:
    id: str
    shots: list[Shot] = field(default_factory=list)
    turns: list[dict] = field(default_factory=list)
    messages: list[tuple[int, str]] = field(default_factory=list)

    @property
    def state(self) -> dict | None:
        return self.turns[-1] if self.turns else None


class Guide:
    def __init__(self, client=None, model: str = ARGON_MODEL):
        if client is None:
            from google import genai

            load_env_local()
            client = genai.Client()
        self.client = client
        self.model = model

    def new_session(self) -> Session:
        return Session(uuid.uuid4().hex)

    def add_shot(self, session: Session, path: Path, note: str = "") -> Shot:
        if len(session.shots) >= MAX_SHOTS:
            raise ValueError(f"a session holds at most {MAX_SHOTS} shots")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if not mime.startswith(("image/", "video/")):
            raise ValueError(f"{path.name} is not a photo or video")
        shot = Shot(len(session.shots) + 1, path, mime, note)
        shot.uploaded = self._upload(shot)
        session.shots.append(shot)
        return shot

    def step(self, session: Session, message: str = "") -> dict:
        from google.genai import types

        instruction = "Update your hypotheses, verify them, and ask for the next shot."
        if message:
            if len(session.messages) >= MAX_MESSAGES:
                raise ValueError(f"a session holds at most {MAX_MESSAGES} messages")
            session.messages.append((len(session.shots), message[:2000]))
            instruction = f"The user says: {message[:2000]}\nAnswer them in `reply`, then {instruction[0].lower()}{instruction[1:]}"
        response = self.client.models.generate_content(
            model=self.model,
            contents=self._contents(session, instruction),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_level="medium"),
            ),
        )
        turn = parse_turn(response.text)
        session.turns.append(turn)
        return turn

    def stream_spec(self, session: Session):
        from google.genai import types

        prompt = SPEC_PROMPT + json.dumps(session.state or {}, indent=1)
        for chunk in self.client.models.generate_content_stream(
            model=self.model,
            contents=self._contents(session, prompt),
            config=types.GenerateContentConfig(system_instruction=SYSTEM, thinking_config=types.ThinkingConfig(thinking_level="low")),
        ):
            if chunk.text:
                yield chunk.text

    def _contents(self, session: Session, instruction: str) -> list:
        from google.genai import types

        parts = []
        earlier = session.messages[:-1] if session.messages and instruction.startswith("The user says") else session.messages
        for shot in session.shots:
            label = f"Shot {shot.index} ({'video' if shot.mime.startswith('video/') else 'photo'})"
            parts.append(types.Part.from_text(text=label + (f", user note: {shot.note}" if shot.note else "")))
            parts.append(types.Part.from_uri(file_uri=shot.uploaded.uri, mime_type=shot.mime))
            parts += [types.Part.from_text(text=f"User message: {text}") for after, text in earlier if after == shot.index]
        parts += [types.Part.from_text(text=f"User message: {text}") for after, text in earlier if after == 0]
        if session.state:
            parts.append(types.Part.from_text(text="Your previous state:\n" + json.dumps(session.state)))
        parts.append(types.Part.from_text(text=instruction))
        return [types.Content(role="user", parts=parts)]

    def _upload(self, shot: Shot):
        uploaded = self.client.files.upload(file=shot.path, config={"mime_type": shot.mime})
        deadline = time.monotonic() + 120
        while getattr(uploaded.state, "name", str(uploaded.state)) == "PROCESSING":
            if time.monotonic() > deadline:
                raise TimeoutError(f"Gemini is still processing {shot.path.name} after 2 minutes")
            time.sleep(1.5)
            uploaded = self.client.files.get(name=uploaded.name)
        if getattr(uploaded.state, "name", str(uploaded.state)) == "FAILED":
            raise RuntimeError(f"Gemini could not process {shot.path.name}")
        return uploaded


def load_env_local(path: Path = ENV_FILE) -> None:
    """`.env.local` wins over the shell so the event key replaces any stale GEMINI_API_KEY."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def parse_turn(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"model did not return JSON: {text[:200]!r}")
    turn = json.loads(text[start : end + 1])
    turn.setdefault("next", {"kind": "photo", "instruction": "Take a clear photo of the whole device.", "why": ""})
    for key in ("observations", "claims", "revisions", "parts", "shopping_list"):
        turn.setdefault(key, [])
    turn.setdefault("safety", "")
    turn.setdefault("reply", "")
    return turn
