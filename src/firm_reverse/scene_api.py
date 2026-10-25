import asyncio
import json
import queue
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

router = APIRouter()
_building: set[str] = set()


@router.post("/api/guide/{session_id}/scene")
def build_scene(session_id: str):
    from . import server
    from .scene import run_loop

    session, _ = server._session(session_id)
    if not session.shots:
        raise HTTPException(422, "send at least one shot before building the 3D model")
    if session_id in _building:
        raise HTTPException(409, "the 3D model is already being built for this session")
    events: queue.Queue = queue.Queue()

    def work():
        try:
            best = run_loop(server.guide(), session, lambda ev: events.put(json.dumps(ev)))
            events.put(json.dumps({"kind": "done", "iteration": best["iteration"], "match_score": best["match_score"]}))
        except Exception as e:  # surfaced to the UI, never swallowed
            events.put(json.dumps({"kind": "error", "message": f"{type(e).__name__}: {e}"}))
        finally:
            _building.discard(session_id)
            events.put(None)

    _building.add(session_id)
    threading.Thread(target=work, daemon=True).start()

    async def stream():
        while True:
            item = await asyncio.to_thread(events.get)
            if item is None:
                return
            yield f"data: {item}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/api/guide/{session_id}/scene.html")
def scene_html(session_id: str):
    from . import server

    session, _ = server._session(session_id)
    if not session.scenes:
        raise HTTPException(404, "no 3D model yet")
    return HTMLResponse(
        session.scenes[-1]["html"],
        headers={"Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'unsafe-inline'; img-src data: blob:; connect-src https://cdn.jsdelivr.net"},
    )
