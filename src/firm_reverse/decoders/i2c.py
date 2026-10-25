from ..signals import Channel, Frame


def _merged_events(scl: Channel, sda: Channel) -> list[tuple[float, str, int]]:
    events = [(t, "scl", v) for t, v in scl.edges[1:-1]] + [(t, "sda", v) for t, v in sda.edges[1:-1]]
    return sorted(events)


def decode(scl: Channel, sda: Channel) -> list[Frame]:
    """One frame per transaction: address, direction, data bytes, and ACK/NACK per byte."""
    frames: list[Frame] = []
    scl_level, sda_level = scl.idle_level, sda.idle_level
    bits: list[int] = []
    current: dict | None = None
    for t, line, value in _merged_events(scl, sda):
        if line == "sda":
            if scl_level == 1 and value == 0:
                if current and current["bytes"]:
                    frames.append(_finish(current))
                current, bits = {"t": t, "bytes": [], "acks": []}, []
            elif scl_level == 1 and value == 1 and current is not None:
                if current["bytes"]:
                    frames.append(_finish(current))
                current, bits = None, []
            sda_level = value
            continue
        scl_level = value
        if value == 1 and current is not None:
            bits.append(sda_level)
            if len(bits) == 9:
                current["bytes"].append(sum(b << (7 - n) for n, b in enumerate(bits[:8])))
                current["acks"].append(bits[8] == 0)
                bits = []
    return frames


def _finish(txn: dict) -> Frame:
    first, *rest = txn["bytes"]
    return Frame(
        txn["t"],
        "i2c",
        {
            "address": f"0x{first >> 1:02X}",
            "read": bool(first & 1),
            "address_acked": txn["acks"][0],
            "data": [f"0x{b:02X}" for b in rest],
        },
    )


def looks_like_clock(channel: Channel) -> float:
    """Regularity score: clocks have many pulses of near-identical high width."""
    highs = sorted(d for level, _, d in channel.pulses() if level == 1)
    if len(highs) < 16:
        return 0.0
    median = highs[len(highs) // 2]
    tight = sum(1 for d in highs if abs(d - median) < median * 0.2)
    return tight / len(highs)
