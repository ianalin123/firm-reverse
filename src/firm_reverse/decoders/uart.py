from ..signals import Channel, Frame

STANDARD_BAUDS = (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, 1_000_000)


def estimate_baud(channel: Channel) -> int | None:
    widths = sorted(d for _, _, d in channel.pulses()[1:-1] if d > 0)
    if len(widths) < 8:
        return None
    bit_time = widths[len(widths) // 10]
    measured = 1 / bit_time
    best = min(STANDARD_BAUDS, key=lambda b: abs(b - measured))
    return best if abs(best - measured) / best < 0.08 else None


def decode(channel: Channel, baud: int | None = None) -> tuple[list[Frame], int | None, float]:
    """8N1 decode. Returns frames, the baud used, and the framing-error ratio."""
    baud = baud or estimate_baud(channel)
    if baud is None:
        return [], None, 1.0
    bit = 1 / baud
    end = channel.edges[-1][0]
    frames: list[Frame] = []
    errors = 0
    t = channel.edges[0][0]
    falling = [et for et, level in channel.edges[1:] if level == 0]
    for start in falling:
        if start < t:
            continue
        if start + 10 * bit > end:
            break
        value = sum(channel.level_at(start + (1.5 + n) * bit) << n for n in range(8))
        stop_ok = channel.level_at(start + 9.5 * bit) == 1
        errors += 0 if stop_ok else 1
        frames.append(Frame(start, "uart", {"byte": value, "framing_ok": stop_ok}))
        t = start + 9.5 * bit
    ratio = errors / len(frames) if frames else 1.0
    return frames, baud, ratio
