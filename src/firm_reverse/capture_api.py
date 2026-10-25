"""Saleae capture upload: decode a Logic 2 export deterministically, hand the summary to the guide as evidence."""

import asyncio
import csv
import io
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .analyze import analyze, summarize
from .loaders import load

router = APIRouter()

CAPTURE_SUFFIXES = (".csv", ".vcd", ".sr")
MAX_CAPTURES = 8


def _times(cells: list[str]) -> list[float]:
    try:
        return [float(c) for c in cells]
    except ValueError:
        pass
    try:
        stamps = [datetime.fromisoformat(c.replace("Z", "+00:00")) for c in cells]
    except ValueError as e:
        raise ValueError(f"unreadable time column: {e}") from e
    return [(t - stamps[0]).total_seconds() for t in stamps]


def normalize_logic2_csv(text: str) -> str:
    """Rewrite a Logic 2 digital export into the plain `time,ch...` form load_csv expects.

    Tolerates a UTF-8 BOM, preamble lines before the `Time` header, padded cells, blank rows,
    and ISO8601 timestamps (the "Use ISO8601 timestamps" export option), which become seconds from the first row.
    """
    rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text.lstrip("\ufeff")))]
    rows = [row for row in rows if any(row)]
    start = next((i for i, row in enumerate(rows) if row[0].lower().startswith("time")), None)
    if start is None:
        return text
    header, *data = rows[start:]
    if not data:
        raise ValueError("the CSV has a header but no data rows")
    times = _times([row[0] for row in data])
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows([f"{t:.9f}", *row[1:]] for t, row in zip(times, data))
    return out.getvalue()


def decode_capture(path: Path) -> str:
    if path.suffix == ".csv":
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"{path.name} is not a text CSV export") from e
        path.write_text(normalize_logic2_csv(text))
    try:
        channels = load(path)
    except (IndexError, KeyError) as e:
        raise ValueError(f"{path.name} could not be parsed as a capture: {e}") from e
    if not channels:
        raise ValueError(f"{path.name} contains no digital channels")
    return summarize(analyze(channels)) or "- no recognisable activity on any channel"


@router.post("/api/guide/{session_id}/capture")
async def guide_capture(session_id: str, note: str = Form(""), capture: UploadFile = File(...)):
    from . import server

    session, directory = server._session(session_id)
    lock = server._session_locks[session_id]
    suffix = Path(capture.filename or "").suffix.lower()
    if suffix not in CAPTURE_SUFFIXES:
        raise HTTPException(422, f"export the capture as CSV, VCD, or sigrok .sr, not {suffix or 'a file with no extension'}")
    if len(session.captures) >= MAX_CAPTURES:
        raise HTTPException(422, f"a session holds at most {MAX_CAPTURES} captures")
    data = await capture.read(server.MAX_UPLOAD_BYTES + 1)
    if len(data) > server.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{capture.filename} is over {server.MAX_UPLOAD_BYTES // 2**20} MB")
    note = note.strip()[:500]

    def work():
        with lock:
            if session_id not in server._sessions:
                raise ValueError("session expired; start a new one")
            if len(session.captures) >= MAX_CAPTURES:
                raise ValueError(f"a session holds at most {MAX_CAPTURES} captures")
            path = directory / f"capture-{uuid.uuid4().hex[:8]}{suffix}"
            path.write_bytes(data)
            try:
                summary = decode_capture(path)
            except Exception:
                path.unlink(missing_ok=True)
                raise
            session.captures.append(f"User note: {note}\n{summary}" if note else summary)
            n = len(session.captures)
            turn = server.guide().step(session, (
                f"I captured with the Saleae: decoded summary is capture {n}. Before using it, check it against "
                "the wiring you asked for and the parts the shots and datasheets show. If it does not fit this device, "
                "say so in capture_check, do not use it as evidence, and ask for the capture again."
            ))
            return {"capture": n, "summary": summary, "turn": turn}

    try:
        return await asyncio.to_thread(work)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")
