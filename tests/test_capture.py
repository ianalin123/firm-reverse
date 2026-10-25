from pathlib import Path

from fastapi.testclient import TestClient

from firm_reverse import server, synth
from firm_reverse.capture_api import normalize_logic2_csv
from firm_reverse.cli import write_csv
from firm_reverse.guide import Guide
from firm_reverse.signals import Channel

from test_guide import FakeClient

DEMO = Path(__file__).parent.parent / "captures" / "demo" / "sensor_board.csv"


def _start(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(server, "_guide", Guide(client=fake))
    client = TestClient(server.app)
    return fake, client, client.post("/api/guide/session").json()["id"]


def _texts(fake) -> list[str]:
    return [p.text for p in fake.calls[-1][0].parts if p.text]


def test_capture_is_decoded_and_fed_to_the_guide(monkeypatch):
    fake, client, session = _start(monkeypatch)
    res = client.post(f"/api/guide/{session}/capture", data={"note": "CH0 SCL"}, files={"capture": ("sensor_board.csv", DEMO.read_bytes(), "text/csv")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["capture"] == 1 and "I2C" in body["summary"]
    assert body["turn"]["next"]["instruction"] == "Flip it over."
    stored, _ = server._sessions[session]
    assert len(stored.captures) == 1 and stored.captures[0].startswith("User note: CH0 SCL")
    assert any("Saleae capture 1" in t for t in _texts(fake))


def test_capture_rejects_non_capture_files(monkeypatch):
    _, client, session = _start(monkeypatch)
    res = client.post(f"/api/guide/{session}/capture", files={"capture": ("notes.txt", b"hello", "text/plain")})
    assert res.status_code == 422
    assert server._sessions[session][0].captures == []


def test_capture_rejects_garbage_csv_and_leaves_no_file(monkeypatch):
    _, client, session = _start(monkeypatch)
    res = client.post(f"/api/guide/{session}/capture", files={"capture": ("bad.csv", b"Time [s],Channel 0\n0.0,banana\n", "text/csv")})
    assert res.status_code == 422, res.text
    assert list(server._sessions[session][1].iterdir()) == []


def _logic2_channels() -> list[Channel]:
    scl, sda = synth.i2c([(0x48, False, [0x01, 0x60])])
    return [Channel("Channel 0", scl.edges), Channel("Channel 1", sda.edges)]


def test_logic2_style_export_decodes(tmp_path, monkeypatch):
    path = tmp_path / "logic2.csv"
    write_csv(_logic2_channels(), path)
    assert path.read_text().startswith("Time [s],Channel 0,Channel 1")
    fake, client, session = _start(monkeypatch)
    res = client.post(f"/api/guide/{session}/capture", files={"capture": ("export.csv", path.read_bytes(), "text/csv")})
    assert res.status_code == 200, res.text
    assert "I2C" in res.json()["summary"]
    assert any("Saleae capture 1" in t for t in _texts(fake))


def test_logic2_quirks_are_normalized(tmp_path):
    path = tmp_path / "logic2.csv"
    write_csv(_logic2_channels(), path)
    header, *rows = path.read_text().splitlines()
    quirky = "﻿Exported by Logic 2\n\n" + header.replace(",", ", ") + "\n" + "\n".join(r.replace(",", ", ") for r in rows) + "\n"
    out = normalize_logic2_csv(quirky)
    assert out.splitlines()[0] == "Time [s],Channel 0,Channel 1"
    assert out.splitlines()[1:] == rows


def test_iso_timestamps_become_relative_seconds():
    out = normalize_logic2_csv("Time [s],Channel 0\n2024-05-01T12:00:00.000000+00:00,1\n2024-05-01T12:00:00.000500+00:00,0\n")
    assert out.splitlines()[1:] == ["0.000000000,1", "0.000500000,0"]


def test_capture_cap(monkeypatch):
    _, client, session = _start(monkeypatch)
    server._sessions[session][0].captures.extend(["x"] * 8)
    res = client.post(f"/api/guide/{session}/capture", files={"capture": ("sensor_board.csv", DEMO.read_bytes(), "text/csv")})
    assert res.status_code == 422
