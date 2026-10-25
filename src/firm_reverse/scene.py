"""Verified 3D reconstruction: Argon writes a Three.js scene, headless Chrome renders it,
Argon compares the renders with the real shots, then patches the scene until they match."""

import base64
import json
import re
from collections.abc import Callable

from .guide import Guide, Session

THREE_VERSION = "0.160.0"
ALLOWED_HOSTS = ("cdn.jsdelivr.net",)
VIEWS = ("front", "iso")
MAX_ITERATIONS = 4
MATCH_SCORE = 0.85

SCENE_CONTRACT = f"""Output one self-contained HTML file that builds a 3D model of this device in Three.js.
Rules:
- Load Three.js only through this import map, nothing else external:
  <script type="importmap">{{"imports": {{"three": "https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}/build/three.module.js",
  "three/addons/": "https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}/examples/jsm/"}}}}</script>
- Real proportions in millimetres (1 unit = 1 mm), estimated from the shots. Model the enclosure, the PCB, and every
  identified IC, connector, button, LED, screen, battery and crystal as separate meshes named by their reference (U1, J1, ...),
  placed where the shots show them. Chip tops carry their marking as a canvas texture.
- Plain neutral background (#f3f6f7), soft key light plus ambient, no shadows needed. The canvas fills the window.
- OrbitControls for the user, an "explode" range input (0 to 1) that separates the enclosure, PCB and parts along Y,
  and a small label overlay listing parts.
- Expose window.setView(name) for "front" (looking at the face shown in shot 1), "back", "top" and "iso", which
  places the camera, hides the UI overlay, and renders one frame synchronously.
- Set window.__ready = true after the first frame renders.
Reply with only the HTML inside one ```html fenced block."""

GENERATE_PROMPT = "Build the first 3D reconstruction of this device from every shot and your current state.\n\n" + SCENE_CONTRACT

CRITIQUE_PROMPT = """Above are the real shots of the device, then renders of your current 3D reconstruction
(labelled Render front and Render iso). Compare them like an inspector.
First reply with a JSON object in a ```json block:
{"match_score": 0.0, "mismatches": [{"part": "U1 or enclosure", "problem": "wrong placement, missing, wrong proportion, wrong colour",
  "evidence": "which shot shows the truth", "fix": "what to change"}], "verdict": "one sentence"}
match_score is 1.0 only when every visible part is in the right place at the right size.
Then reply with the full corrected HTML in one ```html block that fixes every mismatch. Keep the same contract:
""" + SCENE_CONTRACT


def run_loop(guide: Guide, session: Session, on_event: Callable[[dict], None], iterations: int = MAX_ITERATIONS) -> dict:
    html = extract_block(_ask(guide, session, GENERATE_PROMPT), "html")
    best = {"iteration": 0, "match_score": 0.0, "html": html}
    for n in range(1, iterations + 1):
        renders = render(html)
        on_event({"kind": "render", "iteration": n, "images": {v: _data_url(png) for v, png in renders.items()}})
        reply = _ask(guide, session, CRITIQUE_PROMPT, renders)
        critique = json.loads(extract_block(reply, "json"))
        score = float(critique.get("match_score", 0))
        on_event({"kind": "critique", "iteration": n, "critique": critique})
        if score > best["match_score"] or n == 1:
            best = {"iteration": n, "match_score": score, "html": html}
        if score >= MATCH_SCORE or n == iterations:
            break
        html = extract_block(reply, "html")
        on_event({"kind": "patched", "iteration": n})
    session.scenes.append(best)
    return best


def render(html: str, views: tuple[str, ...] = VIEWS) -> dict[str, bytes]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        try:
            page = browser.new_page(viewport={"width": 900, "height": 640})
            page.route("**/*", _only_cdn)
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.set_content(html, wait_until="load")
            try:
                page.wait_for_function("window.__ready === true", timeout=20_000)
            except Exception as e:
                raise RuntimeError(f"scene never became ready: {errors[:3] or e}") from e
            shots = {}
            for view in views:
                page.evaluate("v => window.setView(v)", view)
                page.wait_for_timeout(150)
                shots[view] = page.screenshot()
            return shots
        finally:
            browser.close()


def _only_cdn(route) -> None:
    url = route.request.url
    if url.startswith(("data:", "blob:", "about:")) or any(f"//{host}/" in url for host in ALLOWED_HOSTS):
        route.continue_()
    else:
        route.abort()


def _ask(guide: Guide, session: Session, prompt: str, renders: dict[str, bytes] | None = None) -> str:
    from google.genai import types

    contents = guide._contents(session, prompt)
    if renders:
        extra = []
        for view, png in renders.items():
            extra.append(types.Part.from_text(text=f"Render {view}"))
            extra.append(types.Part.from_bytes(data=png, mime_type="image/png"))
        contents[0].parts[-1:-1] = extra
    response = guide.client.models.generate_content(
        model=guide.model,
        contents=contents,
        config=types.GenerateContentConfig(
            max_output_tokens=65536,
            thinking_config=types.ThinkingConfig(thinking_level="medium"),
        ),
    )
    return response.text or ""


def extract_block(text: str, lang: str) -> str:
    match = re.search(rf"```{lang}\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    if lang == "html" and "<html" in text.lower():
        return text[text.lower().index("<!doctype") if "<!doctype" in text.lower() else text.lower().index("<html") :].strip()
    if lang == "json" and "{" in text:
        return text[text.index("{") : text.rindex("}") + 1]
    raise ValueError(f"model reply has no {lang} block: {text[:200]!r}")


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()

