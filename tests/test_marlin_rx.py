import pytest

from laxthya_ink.links._marlin_rx import classify, parse_position, parse_temps


@pytest.mark.parametrize("line,kind", [
    ("ok", "ok"),
    ("ok T:20.0 /0.0 B:21.0 /0.0", "ok"),
    ("wait", "wait"),
    ("echo:busy: processing", "busy"),
    ("Resend: 12", "resend"),
    ("rs N5", "resend"),
    ("Error:Printer halted. kill() called!", "error"),
    ("//action:cancel", "action"),
    ("FIRMWARE_NAME:Marlin", "info"),
])
def test_classify(line, kind):
    assert classify(line).kind == kind


def test_resend_carries_line_number():
    assert classify("Resend: 12").detail == 12


def test_parse_temps():
    assert parse_temps("ok T:20.5 /0.0 B:60.0 /60.0") == {
        "nozzle": (20.5, 0.0), "bed": (60.0, 60.0),
    }
    assert parse_temps("nothing here") == {}


def test_parse_position():
    assert parse_position("X:10.00 Y:20.00 Z:0.30 E:0.00 Count X:800") == (10.0, 20.0, 0.3, 0.0)
    assert parse_position("X:1 Y:2 Z:3")[3] is None
    assert parse_position("garbage") is None
