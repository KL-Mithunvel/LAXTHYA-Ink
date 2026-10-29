import pytest

from laxthya_ink.gcode.util import (
    build_numbered_line,
    fmt_number,
    parse_words,
    strip_comment,
    strip_line_number,
)


def test_strip_comment():
    assert strip_comment("G1 X1 ; move") == "G1 X1 "
    assert strip_comment("; only comment") == ""
    assert strip_comment("G28") == "G28"


def test_parse_words():
    assert parse_words("G1 X10 Y-5.5 F1200 ; c") == {"G": 1.0, "X": 10.0, "Y": -5.5, "F": 1200.0}


@pytest.mark.parametrize("value,text", [
    (1.0, "1"), (1.5, "1.5"), (0.0004, "0"), (-0.0004, "0"), (12.3456, "12.346"), (-2.0, "-2"),
])
def test_fmt_number(value, text):
    assert fmt_number(value) == text


def test_numbered_line_checksum_and_roundtrip():
    line = build_numbered_line(5, "G1 X10")
    body, checksum = line.rsplit("*", 1)
    expected = 0
    for ch in body:
        expected ^= ord(ch)
    assert int(checksum) == expected
    assert body == "N5 G1 X10"
    assert strip_line_number(line) == "G1 X10"
    assert strip_line_number("G1 X10") == "G1 X10"     # plain lines pass through
