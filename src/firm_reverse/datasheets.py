"""Offline datasheet library: drop PDFs into datasheets/, run `firm-reverse index` once."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2] / "datasheets"
INDEX = ROOT / "index.json"
EXCERPT_CHARS = 1500


@dataclass(frozen=True)
class Datasheet:
    part: str
    file: str
    excerpt: str


def normalize(marking: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", marking.upper())


def build_index(root: Path = ROOT) -> list[Datasheet]:
    sheets = []
    for pdf in sorted(root.glob("*.pdf")):
        reader = PdfReader(pdf)
        text = " ".join((page.extract_text() or "") for page in reader.pages[:2])
        sheets.append(Datasheet(pdf.stem, pdf.name, re.sub(r"\s+", " ", text)[:EXCERPT_CHARS]))
    INDEX.write_text(json.dumps([s.__dict__ for s in sheets], indent=1))
    return sheets


def load_index() -> list[Datasheet]:
    if not INDEX.exists():
        raise FileNotFoundError(f"no datasheet index at {INDEX}; run `firm-reverse index`")
    return [Datasheet(**d) for d in json.loads(INDEX.read_text())]


def lookup(marking: str, sheets: list[Datasheet]) -> Datasheet | None:
    """Chip tops abbreviate part numbers, so match on the longest shared prefix of 4+ characters."""
    key = normalize(marking)
    if len(key) < 3:
        return None
    best, best_len = None, 3
    for sheet in sheets:
        part = normalize(sheet.part)
        shared = next((n for n in range(min(len(key), len(part)), 0, -1) if key[:n] == part[:n]), 0)
        if shared > best_len or (key in normalize(sheet.excerpt) and len(key) > best_len):
            best, best_len = sheet, max(shared, len(key))
    return best
