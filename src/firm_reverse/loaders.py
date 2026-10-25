"""Load digital captures exported from Saleae Logic 2, Digilent WaveForms, sigrok/PulseView, or any VCD writer."""

import configparser
import csv
import re
import zipfile
from pathlib import Path

import numpy as np

from .signals import Channel, Edge


def load(path: Path) -> list[Channel]:
    match path.suffix.lower():
        case ".csv":
            return load_csv(path)
        case ".vcd":
            return load_vcd(path)
        case ".sr":
            return load_sr(path)
        case _:
            raise ValueError(f"unsupported capture format {path.suffix}; export CSV, VCD, or sigrok .sr")


def load_csv(path: Path) -> list[Channel]:
    """First column is time in seconds; every other column is one digital channel (0/1).

    Works for both transition-only exports (Saleae) and per-sample exports (WaveForms).
    """
    with path.open(newline="") as f:
        rows = [row for row in csv.reader(f) if row and not row[0].startswith("#")]
    if len(rows) < 2:
        raise ValueError(f"{path} has no data rows")
    header, *data = rows
    names = [h.strip() for h in header[1:]]
    edges: list[list[Edge]] = [[] for _ in names]
    for row in data:
        t = float(row[0])
        for i, cell in enumerate(row[1 : len(names) + 1]):
            level = int(float(cell))
            if not edges[i] or edges[i][-1][1] != level:
                edges[i].append((t, level))
    end = float(data[-1][0])
    return [Channel(name, e + [(end, e[-1][1])]) for name, e in zip(names, edges) if e]


def load_vcd(path: Path) -> list[Channel]:
    ids: dict[str, str] = {}
    timescale_s = 1e-9
    edges: dict[str, list[Edge]] = {}
    t = 0.0
    in_header = True
    tokens = path.read_text().split()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if in_header:
            if token == "$timescale":
                timescale_s = _parse_timescale(tokens[i + 1 : tokens.index("$end", i)])
            elif token == "$var":
                ids[tokens[i + 3]] = tokens[i + 4]
            elif token == "$enddefinitions":
                in_header = False
            i += 1
            continue
        if token.startswith("#"):
            t = int(token[1:]) * timescale_s
        elif token[0] in "01" and token[1:] in ids:
            series = edges.setdefault(token[1:], [])
            level = int(token[0])
            if not series or series[-1][1] != level:
                series.append((t, level))
        i += 1
    return [Channel(ids[k], e + [(t, e[-1][1])]) for k, e in edges.items()]


def load_sr(path: Path) -> list[Channel]:
    """sigrok session file: a zip of an INI metadata file plus raw logic sample chunks."""
    with zipfile.ZipFile(path) as z:
        meta = configparser.ConfigParser()
        meta.read_string(z.read("metadata").decode())
        device = meta["device 1"]
        prefix = device["capturefile"]
        chunks = sorted(
            (n for n in z.namelist() if n == prefix or n.startswith(prefix + "-")),
            key=lambda n: 0 if n == prefix else int(n.rsplit("-", 1)[1]),
        )
        raw = b"".join(z.read(n) for n in chunks)
    unitsize = int(device["unitsize"])
    rate = _parse_samplerate(device["samplerate"])
    samples = np.frombuffer(raw[: len(raw) - len(raw) % unitsize], dtype=f"<u{unitsize}")
    probes = {int(k[5:]): v for k, v in device.items() if re.fullmatch(r"probe\d+", k)}
    end = len(samples) / rate
    channels = []
    for index, name in sorted(probes.items()):
        bits = ((samples >> (index - 1)) & 1).astype(np.int8)
        changes = np.flatnonzero(np.diff(bits)) + 1
        if not len(changes):
            continue
        edges = [(0.0, int(bits[0]))] + [(int(i) / rate, int(bits[i])) for i in changes]
        channels.append(Channel(name, edges + [(end, edges[-1][1])]))
    return channels


def _parse_samplerate(text: str) -> float:
    value, _, unit = text.strip().partition(" ")
    return float(value) * {"": 1, "Hz": 1, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}[unit]


def _parse_timescale(parts: list[str]) -> float:
    text = "".join(parts)
    units = {"s": 1, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12}
    for unit in sorted(units, key=len, reverse=True):
        if text.endswith(unit):
            return float(text[: -len(unit)] or 1) * units[unit]
    raise ValueError(f"unrecognised VCD timescale {text!r}")
