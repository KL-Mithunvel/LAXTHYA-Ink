"""Small, dependency-free G-code text helpers used by the planner, sim link and runner."""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+)")


def strip_comment(line: str) -> str:
    """Return `line` with any `;` comment removed (Marlin: `;` runs to end of line)."""
    idx = line.find(";")
    return line if idx < 0 else line[:idx]


def parse_words(line: str) -> dict[str, float]:
    """`"G1 X10 Y-5 F1200"` -> `{'G': 1.0, 'X': 10.0, 'Y': -5.0, 'F': 1200.0}`.

    The comment (if any) is stripped first. Duplicate letters keep the last value.
    """
    return {
        m.group(1).upper(): float(m.group(2))
        for m in _WORD_RE.finditer(strip_comment(line))
    }


def fmt_number(value: float) -> str:
    """Format a float for G-code: 3 dp, trailing zeros trimmed, never empty."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-", "-0") else "0"


_NUMBERED_RE = re.compile(r"^N\d+\s+(.*?)(?:\s*\*\d+)?$")


def build_numbered_line(n: int, text: str) -> str:
    """Marlin checksummed line: `N<n> <text>*<checksum>`, checksum = XOR of the
    ASCII bytes of `"N<n> <text>"`. Used by `GcodeRunner` when
    `gcode.use_line_numbers` is on, so a `Resend:` can be serviced instead of
    ending the run."""
    numbered = f"N{n} {text}"
    checksum = 0
    for ch in numbered:
        checksum ^= ord(ch)
    return f"{numbered}*{checksum}"


def strip_line_number(text: str) -> str:
    """Undo `build_numbered_line`: `"N5 G1 X10*37"` -> `"G1 X10"`. A line with
    no `N<n>` prefix passes through unchanged - real Marlin accepts both plain
    and checksummed lines, and the sim/serial links must too (Dev Rule 2)."""
    m = _NUMBERED_RE.match(text)
    return m.group(1) if m else text
