import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from firm_reverse import server
from firm_reverse.guide import Guide, parse_turn

TURN = {
    "device": "IR remote",
    "confidence": 0.4,
    "claims": [{"claim": "battery powered", "status": "confirmed", "evidence": [1]}],
    "next": {"kind": "photo", "instruction": "Flip it over.", "why": "find the screws"},
    "shopping_list": [{"item": "PH0 driver", "why": "case screws", "approx_usd": 6}],
}


class FakeClient:
    def __init__(self):
        self.calls = []
        self.files = SimpleNamespace(upload=self._upload, get=lambda name: None)
        self.models = SimpleNamespace(generate_content=self._generate, generate_content_stream=self._stream)

    def _upload(self, file, config):
        return SimpleNamespace(name=f"files/{file.name}", uri=f"gs://{file.name}", state=SimpleNamespace(name="ACTIVE"))

    def _generate(self, model, contents, config):
        self.calls.append(contents)
        return SimpleNamespace(text="```json\n" + json.dumps(TURN) + "\n```")

    def _stream(self, model, contents, config):
        yield SimpleNamespace(text="## Overview\n")
        yield SimpleNamespace(text="An IR remote.")


def test_parse_turn_fills_defaults():
    turn = parse_turn('noise {"device": "x"} noise')
    assert turn["next"]["kind"] == "photo" and turn["claims"] == []


def test_guide_loop_sends_every_shot_and_previous_state(tmp_path, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(server, "_guide", Guide(client=fake))
    client = TestClient(server.app)
    session = client.post("/api/guide/session").json()["id"]
    for name in ("front.jpg", "back.mp4"):
        res = client.post(f"/api/guide/{session}/shot", data={"note": "n"}, files={"media": (name, b"bytes", "application/octet-stream")})
        assert res.status_code == 200, res.text
    assert res.json()["shot"] == 2
    assert res.json()["turn"]["next"]["instruction"] == "Flip it over."
    second_call = fake.calls[1][0].parts
    texts = [p.text for p in second_call if p.text]
    assert any("Shot 1" in t for t in texts) and any("Shot 2 (video)" in t for t in texts)
    assert any("previous state" in t for t in texts)
    spec = client.post(f"/api/guide/{session}/spec").text
    assert "An IR remote." in spec and '"done"' in spec


def test_guide_rejects_non_media(monkeypatch):
    monkeypatch.setattr(server, "_guide", Guide(client=FakeClient()))
    client = TestClient(server.app)
    session = client.post("/api/guide/session").json()["id"]
    res = client.post(f"/api/guide/{session}/shot", files={"media": ("notes.txt", b"x", "text/plain")})
    assert res.status_code == 422


def test_failed_shot_leaves_no_file(monkeypatch):
    monkeypatch.setattr(server, "_guide", Guide(client=FakeClient()))
    client = TestClient(server.app)
    session = client.post("/api/guide/session").json()["id"]
    client.post(f"/api/guide/{session}/shot", files={"media": ("notes.txt", b"x", "text/plain")})
    _, directory = server._sessions[session]
    assert list(directory.iterdir()) == []
