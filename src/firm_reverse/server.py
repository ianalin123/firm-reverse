"""Bench UI: `firm-reverse-serve`, then open http://<pi>:8000 from any laptop on the same network."""

import asyncio
import json
import os
import queue
import tempfile
import threading
from pathlib import Path

import shutil
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .access import AccessCodeMiddleware
from .analyze import Finding, analyze, summarize
from .loaders import load
from .signals import Channel

STATIC = Path(__file__).parent / "static"
MAX_EDGES_PER_CHANNEL = 4000

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "*.local", "testserver"] + [
    h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()
]

app = FastAPI()
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.add_middleware(AccessCodeMiddleware)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_gemma = None
_gemma_lock = threading.Lock()


def gemma():
    global _gemma
    with _gemma_lock:
        if _gemma is None:
            from .llm import DEFAULT_MODEL, Gemma

            _gemma = Gemma(Path(os.environ.get("FIRM_REVERSE_MODEL", DEFAULT_MODEL)), gpu=bool(os.environ.get("FIRM_REVERSE_GPU")))
        return _gemma


MAX_UPLOAD_BYTES = 150 * 1024 * 1024
MAX_PHOTOS = 8


@app.middleware("http")
async def same_origin_only(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method == "POST" and origin and urlparse(origin).netloc != request.headers.get("host"):
        return JSONResponse({"detail": "cross-origin request rejected"}, status_code=403)
    return await call_next(request)


async def _save(upload: UploadFile, directory: Path) -> Path:
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{upload.filename} is over {MAX_UPLOAD_BYTES // 2**20} MB")
    path = directory / Path(upload.filename or "upload").name
    path.write_bytes(data)
    return path


def _wave(channels: list[Channel], findings: list[Finding]) -> dict:
    group_of = {name: i for i, f in enumerate(findings) for name in f.channels}
    by_name = {c.name: c for c in channels}
    windows = {i: _first_burst([by_name[n] for n in f.channels], f.frames[0].t if f.frames else None) for i, f in enumerate(findings)}
    return {
        "channels": [
            {"name": c.name, "window": windows.get(group_of.get(c.name), _first_burst([c], None)), "edges": c.edges[:MAX_EDGES_PER_CHANNEL]}
            for c in channels
        ],
        "frames": [
            {"t": fr.t, "label": _label(f.protocol, fr.data), "channel": f.channels[-1], "group": i}
            for i, f in enumerate(findings)
            for fr in f.frames[:200]
        ],
    }


MIN_IDLE_GAP_S = 6e-3


def _first_burst(group: list[Channel], start: float | None) -> tuple[float, float]:
    """Time window covering the first run of activity, ending at the first long idle gap on every line."""
    times = sorted(t for c in group for t, _ in c.edges[1:-1])
    end = max(c.edges[-1][0] for c in group)
    if not times:
        return (0.0, end)
    start = times[0] if start is None else start
    widths = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
    threshold = max(20 * widths[len(widths) // 2], MIN_IDLE_GAP_S) if widths else MIN_IDLE_GAP_S
    after = [t for t in times if t >= start]
    stop = next((a for a, b in zip(after, after[1:]) if b - a > threshold), after[-1] if after else end)
    pad = (stop - start) * 0.05 or 1e-4
    return (max(0.0, start - pad), min(end, stop + pad))


def _label(protocol: str, data: dict) -> str:
    if protocol == "NEC infrared":
        return "repeat" if data["repeat"] else f"cmd 0x{data['command']:02X}"
    if protocol == "I2C":
        return f"{data['address']} {'R' if data['read'] else 'W'} {' '.join(data['data'])}"
    if protocol == "UART 8N1":
        ch = chr(data["byte"])
        return ch if ch.isprintable() else f"0x{data['byte']:02X}"
    return ""


@app.get("/")
def index():
    return FileResponse(STATIC / "guide.html")


@app.get("/bench")
def bench_page():
    return FileResponse(STATIC / "index.html")


_guide = None
_sessions: dict = {}
_session_locks: dict[str, threading.Lock] = {}
MAX_SESSIONS = 50
_researching: set[str] = set()


def guide():
    global _guide
    with _gemma_lock:
        if _guide is None:
            from .guide import Guide

            _guide = Guide()
        return _guide


def _evict_idle_session() -> None:
    for victim, lock in list(_session_locks.items()):
        if lock.acquire(blocking=False):
            try:
                shutil.rmtree(_sessions.pop(victim)[1], ignore_errors=True)
                _session_locks.pop(victim, None)
            finally:
                lock.release()
            return
    raise HTTPException(503, "every session is busy; try again in a minute")


def _session(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(404, "unknown session; start a new one")
    return _sessions[session_id]


@app.post("/api/guide/session")
def guide_session():
    if len(_sessions) >= MAX_SESSIONS:
        _evict_idle_session()
    session = guide().new_session()
    _sessions[session.id] = (session, Path(tempfile.mkdtemp()))
    _session_locks[session.id] = threading.Lock()
    return {"id": session.id}


@app.post("/api/guide/{session_id}/shot")
async def guide_shot(session_id: str, note: str = Form(""), media: UploadFile = File(...)):
    from .guide import MAX_SHOTS

    session, directory = _session(session_id)
    lock = _session_locks[session_id]
    if len(session.shots) >= MAX_SHOTS:
        raise HTTPException(422, f"a session holds at most {MAX_SHOTS} shots")
    data = await media.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{media.filename} is over {MAX_UPLOAD_BYTES // 2**20} MB")
    suffix = Path(media.filename or "").suffix.lower()[:8]

    def work():
        with lock:
            if session_id not in _sessions:
                raise ValueError("session expired; start a new one")
            path = directory / f"shot-{len(session.shots) + 1}{suffix}"
            path.write_bytes(data)
            try:
                shot = guide().add_shot(session, path, note)
            except Exception:
                path.unlink(missing_ok=True)
                raise
            return {"shot": shot.index, "turn": guide().step(session)}

    try:
        return await asyncio.to_thread(work)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")


@app.post("/api/guide/{session_id}/chat")
async def guide_chat(session_id: str, message: str = Form(...)):
    session, _ = _session(session_id)
    lock = _session_locks[session_id]
    if not message.strip():
        raise HTTPException(422, "type a question first")

    def work():
        with lock:
            return {"turn": guide().step(session, message.strip())}

    try:
        return await asyncio.to_thread(work)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")


@app.post("/api/guide/{session_id}/datasheets")
def guide_datasheets(session_id: str):
    from .agents import research_parts

    session, _ = _session(session_id)
    parts = list((session.state or {}).get("parts", []))
    if session_id in _researching:
        raise HTTPException(409, "the datasheet agent is already running for this session")
    if not parts:
        raise HTTPException(422, "no parts identified yet; send a shot that shows the chips")
    events: queue.Queue = queue.Queue()

    def work():
        try:
            results = research_parts(parts, client=guide().client, on_status=lambda text: events.put(json.dumps({"kind": "status", "text": text})))
            session.datasheets = results
            events.put(json.dumps({"kind": "done", "results": results}))
        except Exception as e:  # surfaced to the UI, never swallowed
            events.put(json.dumps({"kind": "error", "message": f"{type(e).__name__}: {e}"}))
        finally:
            _researching.discard(session_id)
            events.put(None)

    _researching.add(session_id)
    threading.Thread(target=work, daemon=True).start()

    async def stream():
        while True:
            item = await asyncio.to_thread(events.get)
            if item is None:
                return
            yield f"data: {item}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/guide/{session_id}/spec")
def guide_spec(session_id: str):
    session, _ = _session(session_id)
    lock = _session_locks[session_id]
    events: queue.Queue = queue.Queue()

    def work():
        try:
            with lock:
                for text in guide().stream_spec(session):
                    events.put(json.dumps({"kind": "token", "text": text}))
            events.put(json.dumps({"kind": "done"}))
        except Exception as e:  # surfaced to the UI, never swallowed
            events.put(json.dumps({"kind": "error", "message": f"{type(e).__name__}: {e}"}))
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    async def stream():
        while True:
            item = await asyncio.to_thread(events.get)
            if item is None:
                return
            yield f"data: {item}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/signals")
async def signals(capture: UploadFile = File(...)):
    with tempfile.TemporaryDirectory() as tmp:
        try:
            channels = load(await _save(capture, Path(tmp)))
        except ValueError as e:
            raise HTTPException(422, str(e))
    findings = analyze(channels)
    return {"summary": summarize(findings), "wave": _wave(channels, findings)}


@app.post("/api/run")
async def run(summary: str = Form(""), close_up: bool = Form(True), photos: list[UploadFile] = File(default=[])):
    from .bench import explain_signals, identify_parts, parts_digest, write_spec

    named = [p for p in photos if p.filename]
    if len(named) > MAX_PHOTOS:
        raise HTTPException(413, f"at most {MAX_PHOTOS} photos per run")
    tmp = Path(tempfile.mkdtemp())
    photo_paths = []
    try:
        for i, photo in enumerate(named):
            directory = tmp / str(i)
            directory.mkdir()
            photo_paths.append(await _save(photo, directory))
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    events: queue.Queue = queue.Queue()

    def emit(kind: str, **payload) -> None:
        events.put(json.dumps({"kind": kind, **payload}))

    def work() -> None:
        try:
            model = gemma()
            parts = "- no photo given"
            if photo_paths:
                emit("step", step="parts")
                found = [
                    part
                    for path in photo_paths
                    for part in identify_parts(model, path, close_up=close_up, on_token=lambda t: emit("token", step="parts", text=t))
                ]
                parts = parts_digest(found)
                emit("parts", parts=[{"marking": p.marking, "kind": p.kind, "location": p.location, "datasheet": p.datasheet.file if p.datasheet else None} for p in found])
            emit("step", step="behaviour")
            explanation = explain_signals(model, summary, parts, on_token=lambda t: emit("token", step="behaviour", text=t))
            emit("step", step="spec")
            write_spec(model, parts, summary, explanation, on_token=lambda t: emit("token", step="spec", text=t))
            emit("done")
        except Exception as e:  # surfaced to the UI, never swallowed
            emit("error", message=f"{type(e).__name__}: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    async def stream():
        while True:
            item = await asyncio.to_thread(events.get)
            if item is None:
                return
            yield f"data: {item}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


from .capture_api import router as capture_router  # noqa: E402
from .scene_api import router as scene_router  # noqa: E402

app.include_router(capture_router)
app.include_router(scene_router)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))
