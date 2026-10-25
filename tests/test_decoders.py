from firm_reverse import synth
from firm_reverse.analyze import analyze, summarize
from firm_reverse.decoders import i2c, nec, uart


def test_nec_receiver_output():
    [frame] = nec.decode(synth.nec(0x04, 0x08))
    assert frame.data["address"] == 0x04
    assert frame.data["command"] == 0x08
    assert frame.data["checksum_ok"]
    assert frame.data["carrier_hz"] is None


def test_nec_led_line_reports_carrier():
    [frame] = nec.decode(synth.nec(0x20, 0xDF, carrier_hz=38_000))
    assert frame.data["command"] == 0xDF
    assert abs(frame.data["carrier_hz"] - 38_000) < 1_000


def test_uart_autobaud_and_payload():
    frames, baud, errors = uart.decode(synth.uart(b"TEMP=23.5\r\n", baud=9600))
    assert baud == 9600
    assert errors == 0
    assert bytes(f.data["byte"] for f in frames) == b"TEMP=23.5\r\n"


def test_i2c_transactions():
    scl, sda = synth.i2c([(0x48, False, [0x00]), (0x48, True, [0x19, 0x80])])
    frames = i2c.decode(scl, sda)
    assert [f.data["address"] for f in frames] == ["0x48", "0x48"]
    assert [f.data["read"] for f in frames] == [False, True]
    assert frames[1].data["data"] == ["0x19", "0x80"]


def test_analyze_identifies_mixed_capture():
    scl, sda = synth.i2c([(0x48, True, [0x19, 0x80])] * 5)
    findings = analyze([synth.nec(0x04, 0x08), synth.uart(b"hello world\n"), sda, scl])
    assert {f.protocol for f in findings} == {"NEC infrared", "I2C", "UART 8N1"}
    text = summarize(findings)
    assert "command=0x08" in text and "0x48" in text and "hello world" in text


def test_part_lines_parse_and_dedupe_model_loops():
    from firm_reverse.bench import parse_part_lines

    text = "marking | kind | location\nATMEGA328P | microcontroller | bottom right\n10K | resistor | center\n10K | resistor | center\n- `16U2` | USB bridge | top left\nchip3 | unknown | top\nsome chatter"
    assert parse_part_lines(text) == [
        ("ATMEGA328P", "microcontroller", "bottom right"),
        ("10K", "resistor", "center"),
        ("16U2", "USB bridge", "top left"),
    ]


def test_uno_capture_rows_decode_as_nec(tmp_path):
    from firm_reverse.loaders import load

    ir = synth.nec(0x04, 0x08)
    rows = ["Time [s],D2,D3"] + [f"{round(t * 1e6) // 4 * 4 / 1e6:.6f},{level},1" for t, level in ir.edges]
    rows.insert(5, "# overflow: edges dropped")
    path = tmp_path / "uno.csv"
    path.write_text("\n".join(rows) + "\n")
    [d2, _] = load(path)
    [frame] = nec.decode(d2)
    assert frame.data["command"] == 0x08
