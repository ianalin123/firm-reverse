import argparse
import sys
import time
from pathlib import Path

from . import datasheets, synth
from .signals import Channel


def _stream(token: str) -> None:
    sys.stdout.write(token)
    sys.stdout.flush()


def _gemma(args):
    from .llm import DEFAULT_MODEL, Gemma

    started = time.monotonic()
    gemma = Gemma(Path(args.model) if args.model else DEFAULT_MODEL, gpu=args.gpu)
    print(f"[model loaded in {time.monotonic() - started:.1f}s]", file=sys.stderr)
    return gemma


def cmd_index(args) -> None:
    sheets = datasheets.build_index()
    print(f"indexed {len(sheets)} datasheets into {datasheets.INDEX}")


def cmd_signals(args) -> None:
    from .bench import read_signals

    _, summary = read_signals(Path(args.capture))
    print(summary)


def cmd_parts(args) -> None:
    from .bench import identify_parts, parts_digest

    parts = identify_parts(_gemma(args), Path(args.photo), close_up=args.close_up, on_token=_stream)
    print("\n\n" + parts_digest(parts))


def cmd_run(args) -> None:
    from .bench import explain_signals, identify_parts, parts_digest, read_signals, write_spec

    gemma = _gemma(args)
    print("== parts ==")
    parts = parts_digest(identify_parts(gemma, Path(args.photo), on_token=_stream)) if args.photo else "- no photo given"
    print("\n" + parts)
    print("\n== signals ==")
    _, summary = read_signals(Path(args.capture))
    print(summary)
    print("\n== behaviour ==")
    explanation = explain_signals(gemma, summary, parts, on_token=_stream)
    print("\n\n== spec ==")
    spec = write_spec(gemma, parts, summary, explanation, on_token=_stream)
    out = Path(args.out)
    out.write_text(spec)
    print(f"\n\n[spec written to {out}]")


def cmd_ask(args) -> None:
    gemma = _gemma(args)
    started = time.monotonic()
    text = gemma.ask(args.prompt, image=Path(args.image) if args.image else None, on_token=_stream)
    elapsed = time.monotonic() - started
    print(f"\n[{len(text)} chars in {elapsed:.1f}s]", file=sys.stderr)


def write_csv(channels: list[Channel], path: Path) -> None:
    times = sorted({t for c in channels for t, _ in c.edges})
    rows = ["Time [s]," + ",".join(c.name for c in channels)]
    rows += [f"{t:.9f}," + ",".join(str(c.level_at(t)) for c in channels) for t in times]
    path.write_text("\n".join(rows) + "\n")


def cmd_capture(args) -> None:
    import serial

    names = args.names.split(",") if args.names else None
    out = Path(args.out)
    lines = []
    with serial.Serial(args.port, args.baud, timeout=0.2) as port:
        port.reset_input_buffer()
        print(f"[recording {args.seconds:g}s from {args.port}; press the buttons now]", file=sys.stderr)
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            line = port.readline().decode("ascii", errors="replace").strip()
            if line:
                lines.append(line)
    header = next((i for i, line in enumerate(lines) if line.startswith("Time")), None)
    if header is None:
        lines.insert(0, "Time [s],D2,D3")
        header = 0
    if names:
        lines[header] = "Time [s]," + ",".join(names)
    rows = lines[header:]
    out.write_text("\n".join(rows) + "\n")
    edges = sum(1 for line in rows[1:] if not line.startswith("#"))
    print(f"[{edges} edges written to {out}]", file=sys.stderr)
    if any(line.startswith("# overflow") for line in rows):
        print("[warning: the Uno dropped edges; capture a shorter burst]", file=sys.stderr)


def cmd_synth(args) -> None:
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_csv([synth.nec(0x04, 0x08, carrier_hz=38_000)], out / "remote_ir_led.csv")
    scl, sda = synth.i2c([(0x48, False, [0x00]), (0x48, True, [0x19, 0x80])] * 4)
    write_csv([scl, sda, synth.uart(b"T=25.5C\r\n", baud=9600)], out / "sensor_board.csv")
    print(f"wrote demo captures to {out}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="firm-reverse", description="Offline hardware teardown bench")
    parser.add_argument("--model", help="path to a .litertlm model (default: E2B in models/)")
    parser.add_argument("--gpu", action="store_true", help="use the GPU backend")
    sub = parser.add_subparsers(required=True)

    sub.add_parser("index", help="index PDFs in datasheets/").set_defaults(fn=cmd_index)
    p = sub.add_parser("signals", help="decode a capture, no model needed")
    p.add_argument("capture")
    p.set_defaults(fn=cmd_signals)
    p = sub.add_parser("parts", help="identify parts in a board photo")
    p.add_argument("photo")
    p.add_argument("--close-up", action="store_true", help="photo shows a single chip")
    p.set_defaults(fn=cmd_parts)
    p = sub.add_parser("run", help="photo + capture -> spec")
    p.add_argument("capture")
    p.add_argument("--photo")
    p.add_argument("--out", default="spec.md")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("ask", help="raw prompt, prints timing (benchmark the device)")
    p.add_argument("prompt")
    p.add_argument("--image")
    p.set_defaults(fn=cmd_ask)
    p = sub.add_parser("capture", help="record edges from an Arduino running firmware/uno_capture")
    p.add_argument("port", help="serial port, for example /dev/cu.usbmodem1101")
    p.add_argument("--out", default="captures/uno.csv")
    p.add_argument("--seconds", type=float, default=5)
    p.add_argument("--baud", type=int, default=500000)
    p.add_argument("--names", help="channel names for D2,D3, for example IR,BTN")
    p.set_defaults(fn=cmd_capture)
    p = sub.add_parser("synth", help="write synthetic demo captures")
    p.add_argument("out_dir", nargs="?", default="captures/demo")
    p.set_defaults(fn=cmd_synth)

    args = parser.parse_args()
    args.fn(args)
