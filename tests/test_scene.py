from types import SimpleNamespace

from firm_reverse import scene
from firm_reverse.guide import Guide

HTML = "<!doctype html><html><body>v{n}</body></html>"


class SceneClient:
    def __init__(self, scores):
        self.scores = list(scores)
        self.calls = 0
        self.files = SimpleNamespace(upload=lambda file, config: SimpleNamespace(name="f", uri="gs://f", state=SimpleNamespace(name="ACTIVE")))
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, model, contents, config):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(text=f"```html\n{HTML.format(n=1)}\n```")
        score = self.scores.pop(0)
        return SimpleNamespace(text=f'```json\n{{"match_score": {score}, "mismatches": [{{"part": "U1", "problem": "too far left"}}]}}\n```\n```html\n{HTML.format(n=self.calls)}\n```')


def test_extract_block_variants():
    assert scene.extract_block("x ```html\n<p>a</p>\n``` y", "html") == "<p>a</p>"
    assert scene.extract_block('noise {"a": 1} noise', "json") == '{"a": 1}'


def test_loop_patches_until_match_and_keeps_best(tmp_path, monkeypatch):
    rendered = []
    monkeypatch.setattr(scene, "render", lambda html, views=scene.VIEWS: rendered.append(html) or {v: b"png" for v in views})
    guide = Guide(client=SceneClient([0.4, 0.9]))
    session = guide.new_session()
    photo = tmp_path / "board.jpg"
    photo.write_bytes(b"jpg")
    guide.add_shot(session, photo)
    events = []
    best = scene.run_loop(guide, session, events.append, iterations=4)
    assert [e["kind"] for e in events] == ["render", "critique", "patched", "render", "critique"]
    assert rendered[1] != rendered[0]
    assert best["iteration"] == 2 and best["match_score"] == 0.9
    assert session.scenes[-1] is best
