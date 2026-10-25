"""NEC infrared protocol, from either a receiver output or a raw LED drive line.

A raw LED line carries a ~38 kHz carrier during marks, so carrier bursts are
merged into single marks before decoding and the carrier frequency is reported.
"""

from ..signals import Channel, Frame

CARRIER_GAP_S = 100e-6
LEADER_MARK_S = 9e-3
LEADER_SPACE_S = 4.5e-3
REPEAT_SPACE_S = 2.25e-3
BIT_MARK_S = 562.5e-6
ONE_SPACE_S = 1687.5e-6


def _near(value: float, target: float, tolerance: float = 0.3) -> bool:
    return abs(value - target) <= target * tolerance


def _marks_and_spaces(channel: Channel) -> tuple[list[tuple[float, float, float]], float | None]:
    """Returns (start, mark_s, following_space_s) per mark, and the carrier Hz if one was present."""
    idle = channel.idle_level
    pulses = channel.pulses()
    marks: list[list[float]] = []
    carrier_periods: list[float] = []
    for level, start, duration in pulses:
        if level != idle:
            if marks and start - (marks[-1][0] + marks[-1][1]) < CARRIER_GAP_S:
                carrier_periods.append(start - marks[-1][2])
                marks[-1][1] = start + duration - marks[-1][0]
                marks[-1][2] = start
            else:
                marks.append([start, duration, start])
    spaced = [
        (m[0], m[1], (marks[i + 1][0] - (m[0] + m[1])) if i + 1 < len(marks) else float("inf"))
        for i, m in enumerate(marks)
    ]
    carrier_hz = None
    if len(carrier_periods) > 10:
        carrier_periods.sort()
        carrier_hz = 1 / carrier_periods[len(carrier_periods) // 2]
    return spaced, carrier_hz


def decode(channel: Channel) -> list[Frame]:
    marks, carrier_hz = _marks_and_spaces(channel)
    frames: list[Frame] = []
    i = 0
    while i < len(marks):
        start, mark, space = marks[i]
        if not _near(mark, LEADER_MARK_S):
            i += 1
            continue
        if _near(space, REPEAT_SPACE_S):
            frames.append(Frame(start, "nec", {"repeat": True, "carrier_hz": carrier_hz}))
            i += 1
            continue
        if not _near(space, LEADER_SPACE_S) or i + 33 > len(marks):
            i += 1
            continue
        bits = []
        for _, bit_mark, bit_space in marks[i + 1 : i + 33]:
            if not _near(bit_mark, BIT_MARK_S, 0.5):
                break
            bits.append(1 if bit_space > (BIT_MARK_S + ONE_SPACE_S) / 2 else 0)
        if len(bits) == 32:
            frames.append(Frame(start, "nec", _fields(bits) | {"carrier_hz": carrier_hz}))
            i += 33
        else:
            i += 1
    return frames


def _fields(bits: list[int]) -> dict:
    octets = [sum(bit << n for n, bit in enumerate(bits[k : k + 8])) for k in range(0, 32, 8)]
    address, address_inv, command, command_inv = octets
    return {
        "repeat": False,
        "address": address if address ^ address_inv == 0xFF else (address_inv << 8) | address,
        "extended_address": address ^ address_inv != 0xFF,
        "command": command,
        "checksum_ok": command ^ command_inv == 0xFF,
        "raw": "0x" + "".join(f"{o:02X}" for o in octets),
    }
