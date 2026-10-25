import json
import re
from pathlib import Path

import litert_lm

litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)

DEFAULT_MODEL =Path(__file__).resolve().parents[2] / "models" / "gemma-4-E2B-it.litertlm"


class Gemma:
    """One engine per process: loading the model is the slow part on a Pi."""

    def __init__(self, model_path: Path = DEFAULT_MODEL, gpu: bool = False):
        if not model_path.exists():
            raise FileNotFoundError(f"model not found at {model_path}; see README for download")
        backend = litert_lm.Backend.GPU() if gpu else litert_lm.Backend.CPU()
        self._engine = litert_lm.Engine(
            str(model_path),
            backend=backend,
            vision_backend=backend,
            max_num_images=1,
        ).__enter__()

    def ask(
        self,
        prompt: str,
        image: Path | None = None,
        system: str | None = None,
        on_token=None,
        max_output_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        messages = [litert_lm.Message.system(system)] if system else None
        contents = (
            litert_lm.Contents.of(litert_lm.Content.ImageFile(absolute_path=str(image.resolve())), prompt)
            if image
            else prompt
        )
        with self._engine.create_conversation(
            messages=messages,
            max_output_tokens=max_output_tokens,
            sampler_config=litert_lm.SamplerConfig(temperature=temperature, top_k=40),
        ) as conversation:
            if on_token is None:
                return conversation.send_message(contents)["content"][0]["text"]
            parts: list[str] = []
            for chunk in conversation.send_message_async(contents):
                for item in chunk.get("content", []):
                    if item.get("type") == "text":
                        parts.append(item["text"])
                        on_token(item["text"])
            return "".join(parts)

    def close(self) -> None:
        self._engine.__exit__(None, None, None)


def extract_json(text: str):
    """Small models wrap JSON in prose or code fences; take the first parseable array or object."""
    for match in re.finditer(r"(\[.*\]|\{.*\})", text, re.DOTALL):
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
    raise ValueError(f"model returned no parseable JSON: {text[:300]!r}")
