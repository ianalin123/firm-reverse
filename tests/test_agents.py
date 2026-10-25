import json
from types import SimpleNamespace

import pytest

from firm_reverse import agents
from firm_reverse.agents import parse_research, research_parts, wait_for

PARTS = [
    {"ref": "U1", "marking": "ATMEL MEGA328P AU", "function": "MCU"},
    {"ref": "U2", "marking": "MEGA16U2", "function": "USB bridge"},
]

FOUND = {
    "parts": [
        {
            "ref": "U1",
            "marking": "ATMEL MEGA328P AU",
            "corrected_marking": "ATMEGA328P-AU",
            "verified": "true",
            "datasheet_url": "https://example.com/328p.pdf",
            "probe_pins": [{"pin": "PD1/TXD", "number": "31", "why": "UART transmit"}],
        }
    ]
}


class FakeInteractions:
    def __init__(self, statuses, text="", errors=None):
        self.statuses = list(statuses)
        self.text = text
        self.errors = errors
        self.created = []
        self.gets = 0

    def create(self, **body):
        self.created.append(body)
        return self._next()

    def get(self, id):
        assert id == "int-1"
        self.gets += 1
        return self._next()

    def _next(self):
        status = self.statuses.pop(0)
        return SimpleNamespace(id="int-1", status=status, output_text=self.text if status == "completed" else None, errors=self.errors)


def fake_client(statuses, text="", errors=None):
    return SimpleNamespace(interactions=FakeInteractions(statuses, text, errors))


@pytest.fixture(autouse=True)
def instant_sleep(monkeypatch):
    monkeypatch.setattr(agents.time, "sleep", lambda _seconds: None)


def test_parse_research_strips_fences_and_fills_defaults():
    [part] = parse_research("```json\n" + json.dumps(FOUND) + "\n```")
    assert part["verified"] is True
    assert part["corrected_marking"] == "ATMEGA328P-AU"
    assert part["interfaces"] == [] and part["key_specs"] == []
    assert part["package"] == ""


def test_parse_research_rejects_prose_and_missing_parts():
    with pytest.raises(ValueError, match="did not return JSON"):
        parse_research("I could not find anything.")
    with pytest.raises(ValueError, match="no parts list"):
        parse_research('{"answer": "none"}')


def test_unrecognized_verdict_becomes_unknown():
    [part] = parse_research('{"parts": [{"ref": "U9", "verified": "maybe"}]}')
    assert part["verified"] == "unknown"


def test_research_parts_polls_until_complete_and_keeps_order():
    client = fake_client(["queued", "in_progress", "in_progress", "completed"], json.dumps(FOUND))
    statuses = []
    result = research_parts(PARTS, client=client, on_status=statuses.append)

    assert client.interactions.gets == 3
    body = client.interactions.created[0]
    assert body["agent"] == agents.AGENT and body["background"] is True and body["environment"] == "remote"
    assert "MEGA16U2" in body["input"]
    assert [part["ref"] for part in result] == ["U1", "U2"]
    assert result[0]["verified"] is True
    assert result[1]["verified"] == "unknown" and "returned nothing" in result[1]["notes"]
    assert any("queued" in s for s in statuses) and statuses[-1].startswith("Datasheet agent finished")


def test_research_parts_raises_on_failed_interaction():
    client = fake_client(["in_progress", "failed"], errors=["quota"])
    with pytest.raises(RuntimeError, match="ended failed"):
        research_parts(PARTS, client=client)


def test_wait_for_times_out(monkeypatch):
    clock = iter(range(0, 1000, 100))
    monkeypatch.setattr(agents.time, "monotonic", lambda: next(clock))
    client = fake_client(["in_progress"] * 10)
    first = client.interactions.create()
    with pytest.raises(TimeoutError, match="still in_progress"):
        wait_for(client, first, lambda _message: None, max_wait=240)


def test_no_parts_makes_no_call():
    client = fake_client([])
    assert research_parts([], client=client) == []
    assert client.interactions.created == []
