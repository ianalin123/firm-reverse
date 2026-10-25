"""Synthetic captures for tests and for a no-hardware demo fallback."""

from .signals import Channel, Edge


class _Line:
    def __init__(self, idle: int, t: float = 0.0):
        self.edges: list[Edge] = [(0.0, idle)]
        self.t = t

    def hold(self, level: int, seconds: float) -> None:
        if self.edges[-1][1] != level:
            self.edges.append((self.t, level))
        self.t += seconds

    def channel(self, name: str, tail_s: float = 1e-3) -> Channel:
        level = self.edges[-1][1]
        return Channel(name, self.edges + [(self.t + tail_s, level)])


def nec(address: int, command: int, carrier_hz: float | None = None, start_s: float = 1e-3) -> Channel:
    """Receiver-style (idle high, active low) or LED-style with carrier (idle low, bursts high)."""
    idle = 0 if carrier_hz else 1
    line = _Line(idle, start_s)

    def mark(seconds: float) -> None:
        if carrier_hz is None:
            line.hold(0, seconds)
            return
        period = 1 / carrier_hz
        for _ in range(round(seconds / period)):
            line.hold(1, period / 3)
            line.hold(0, period * 2 / 3)

    def space(seconds: float) -> None:
        line.hold(idle, seconds)

    line.hold(idle, 0)
    mark(9e-3)
    space(4.5e-3)
    for octet in (address, address ^ 0xFF, command, command ^ 0xFF):
        for n in range(8):
            mark(562.5e-6)
            space(1687.5e-6 if octet >> n & 1 else 562.5e-6)
    mark(562.5e-6)
    space(5e-3)
    return line.channel("IR")


def uart(payload: bytes, baud: int = 115200, gap_bits: int = 2) -> Channel:
    bit = 1 / baud
    line = _Line(1, 5 * bit)
    for byte in payload:
        line.hold(0, bit)
        for n in range(8):
            line.hold(byte >> n & 1, bit)
        line.hold(1, bit * (1 + gap_bits))
    return line.channel("TX")


def i2c(transactions: list[tuple[int, bool, list[int]]], hz: float = 100_000, period_s: float = 0.05) -> tuple[Channel, Channel]:
    half = 1 / hz / 2
    scl, sda = _Line(1), _Line(1)

    def both(scl_level: int, sda_level: int, seconds: float) -> None:
        scl.hold(scl_level, seconds)
        sda.hold(sda_level, seconds)

    for k, (address, read, data) in enumerate(transactions):
        idle_until = k * period_s + 1e-3
        both(1, 1, max(idle_until - scl.t, half))
        both(1, 0, half)
        for byte in [(address << 1) | int(read), *data]:
            for bit in [byte >> (7 - n) & 1 for n in range(8)] + [0]:
                both(0, bit, half)
                both(1, bit, half)
        both(0, 0, half)
        both(1, 0, half)
        both(1, 1, half)
    return scl.channel("SCL"), sda.channel("SDA")
