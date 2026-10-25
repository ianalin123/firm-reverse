"""Deterministic protocol identification. Gemma only ever sees the compact summary this produces."""

from collections import Counter
from dataclasses import dataclass, field

from .decoders import i2c, nec, uart
from .signals import Channel, Frame

CLOCK_SCORE = 0.8

I2C_ADDRESS_HINTS = {
    **{a: "24xx EEPROM" for a in range(0x50, 0x58)},
    0x5A: "MLX90614 IR thermometer or MPR121 touch controller",
    0x48: "TMP102/LM75 temperature sensor or ADS1115 ADC",
    0x68: "DS1307/DS3231 RTC or MPU-6050 IMU",
    0x76: "BME280/BMP280 environmental sensor",
    0x77: "BME280/BMP180 environmental sensor",
    0x3C: "SSD1306 OLED display",
    0x27: "PCF8574 I/O expander (character LCD backpack)",
    0x40: "INA219 current sensor or PCA9685 PWM driver",
    0x29: "VL53L0X time-of-flight sensor",
    0x00: "general call address (broadcast to every device; MLX90614 also answers here)",
}
UART_MAX_FRAMING_ERRORS = 0.05


@dataclass
class Finding:
    protocol: str
    channels: list[str]
    frames: list[Frame]
    params: dict = field(default_factory=dict)


def analyze(channels: list[Channel]) -> list[Finding]:
    findings: list[Finding] = []
    remaining = [c for c in channels if len(c.edges) > 3]

    for channel in list(remaining):
        frames = nec.decode(channel)
        if frames:
            carrier = next((f.data["carrier_hz"] for f in frames if f.data["carrier_hz"]), None)
            findings.append(Finding("NEC infrared", [channel.name], frames, {"carrier_hz": carrier}))
            remaining.remove(channel)

    clocks = sorted(remaining, key=i2c.looks_like_clock, reverse=True)
    for scl in clocks:
        if i2c.looks_like_clock(scl) < CLOCK_SCORE or scl not in remaining:
            continue
        for sda in [c for c in remaining if c is not scl]:
            frames = i2c.decode(scl, sda)
            if frames and sum(f.data["address_acked"] for f in frames) >= len(frames) / 2:
                findings.append(Finding("I2C", [scl.name, sda.name], frames, {"scl": scl.name, "sda": sda.name}))
                remaining = [c for c in remaining if c not in (scl, sda)]
                break

    for channel in list(remaining):
        frames, baud, error_ratio = uart.decode(channel)
        if frames and error_ratio <= UART_MAX_FRAMING_ERRORS:
            findings.append(Finding("UART 8N1", [channel.name], frames, {"baud": baud}))
            remaining.remove(channel)

    for channel in remaining:
        findings.append(Finding("unidentified", [channel.name], [], _timing_profile(channel)))
    return findings


def _timing_profile(channel: Channel) -> dict:
    pulses = channel.pulses()
    widths = sorted(d for _, _, d in pulses)
    span = channel.edges[-1][0] - channel.edges[0][0]
    return {
        "transitions": len(channel.edges) - 2,
        "min_pulse_us": round(widths[0] * 1e6, 2) if widths else None,
        "median_pulse_us": round(widths[len(widths) // 2] * 1e6, 2) if widths else None,
        "approx_rate_hz": round(len(pulses) / 2 / span, 1) if span else None,
    }


def summarize(findings: list[Finding], max_examples: int = 6) -> str:
    lines: list[str] = []
    for f in findings:
        head = f"- {f.protocol} on {'channels' if len(f.channels) > 1 else 'channel'} {', '.join(f.channels)}"
        if f.params:
            head += " (" + ", ".join(f"{k}={_fmt(v)}" for k, v in f.params.items() if v is not None) + ")"
        lines.append(head)
        if not f.frames:
            continue
        lines.append(f"  {len(f.frames)} frames over {_fmt(f.frames[-1].t - f.frames[0].t)} s")
        lines.extend(_protocol_digest(f, max_examples))
    return "\n".join(lines)


def _protocol_digest(f: Finding, max_examples: int) -> list[str]:
    if f.protocol == "NEC infrared":
        codes = Counter((d["address"], d["command"]) for d in (fr.data for fr in f.frames) if not d["repeat"])
        repeats = sum(1 for fr in f.frames if fr.data["repeat"])
        out = [f"  button code address=0x{a:02X} command=0x{c:02X} sent {n}x" for (a, c), n in codes.most_common(max_examples)]
        return out + ([f"  {repeats} repeat codes (button held)"] if repeats else [])
    if f.protocol == "I2C":
        by_device = Counter((fr.data["address"], fr.data["read"]) for fr in f.frames)
        period = _median_period([fr.t for fr in f.frames])
        out = [f"  device {a} {'read' if r else 'write'} x{n}" for (a, r), n in by_device.most_common(max_examples)]
        out += _address_hints(sorted({int(fr.data["address"], 16) for fr in f.frames}))
        out += [f"  e.g. t={fr.t:.4f}s {fr.data['address']} {'R' if fr.data['read'] else 'W'} {_clip(fr.data['data'])}" for fr in f.frames[:max_examples]]
        return out + ([f"  transactions repeat every ~{_fmt(period * 1e3)} ms"] if period and len(f.frames) >= 10 else [])
    if f.protocol == "UART 8N1":
        payload = bytes(fr.data["byte"] for fr in f.frames)
        printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in payload) / max(len(payload), 1)
        sample = payload[:200].decode("ascii") if printable > 0.9 else payload[:48].hex(" ")
        return [f"  {'ascii' if printable > 0.9 else 'binary'} payload: {sample!r}"]
    return []


def _address_hints(addresses: list[int]) -> list[str]:
    eeprom = [a for a in addresses if 0x50 <= a <= 0x57]
    out = []
    if len(eeprom) > 1:
        span = f"0x{eeprom[0]:02X} to 0x{eeprom[-1]:02X}"
        out.append(f"  addresses {span} together look like one 24xx04/08/16 EEPROM, which answers on one address per 256-byte block")
    elif eeprom:
        out.append(f"  address 0x{eeprom[0]:02X} commonly belongs to: 24xx EEPROM")
    out += [f"  address 0x{a:02X} commonly belongs to: {I2C_ADDRESS_HINTS[a]}" for a in addresses if a in I2C_ADDRESS_HINTS and a not in eeprom]
    return out


def _clip(data: list[str], limit: int = 16) -> str:
    shown = " ".join(data[:limit])
    return f"[{shown} ... +{len(data) - limit} more]" if len(data) > limit else f"[{shown}]"


def _median_period(times: list[float]) -> float | None:
    gaps = sorted(b - a for a, b in zip(times, times[1:]))
    return gaps[len(gaps) // 2] if gaps else None


def _fmt(value) -> str:
    if isinstance(value, float) and value >= 1000:
        return f"{value / 1000:.1f}k"
    return f"{value:.3g}" if isinstance(value, float) else str(value)
