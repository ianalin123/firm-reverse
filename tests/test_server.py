from pathlib import Path

from fastapi.testclient import TestClient

from firm_reverse import synth
from firm_reverse.cli import write_csv
from firm_reverse.server import app


def test_signals_endpoint_decodes_upload(tmp_path: Path):
    capture = tmp_path / "remote.csv"
    write_csv([synth.nec(0x04, 0x08, carrier_hz=38_000)], capture)
    response = TestClient(app).post("/api/signals", files={"capture": ("remote.csv", capture.read_bytes())})
    assert response.status_code == 200
    body = response.json()
    assert "command=0x08" in body["summary"]
    assert body["wave"]["frames"][0]["label"] == "cmd 0x08"


def test_signals_endpoint_rejects_unknown_format():
    response = TestClient(app).post("/api/signals", files={"capture": ("x.bin", b"\x00")})
    assert response.status_code == 422
