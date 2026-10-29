"""Classify a line received from Marlin over serial.

Used by `printer_serial.SerialPrinter`; kept separate so it can be unit-tested
without a serial port.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RESEND_RE = re.compile(r"^\s*(?:resend|rs)\s*:?\s*n?\s*(\d+)", re.IGNORECASE)
_TEMP_RE = re.compile(r"\bT:\s*(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)")
_BED_RE = re.compile(r"\bB:\s*(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)")
_POS_RE = re.compile(
    r"\bX:\s*(-?\d+(?:\.\d+)?)\s+Y:\s*(-?\d+(?:\.\d+)?)\s+Z:\s*(-?\d+(?:\.\d+)?)"
    r"(?:\s+E:\s*(-?\d+(?:\.\d+)?))?"
)


@dataclass
class RxLine:
    kind: str          # "ok" | "wait" | "busy" | "resend" | "error" | "action" | "info"
    raw: str
    detail: object = None   # resend -> int; busy/error/action -> str


def classify(line: str) -> RxLine:
    s = line.strip()
    low = s.lower()

    if low == "ok" or low.startswith(("ok ", "ok\t")):
        return RxLine("ok", s)
    if low == "wait":
        return RxLine("wait", s)
    if "busy:" in low:                       # "echo:busy: processing" / "busy: processing"
        return RxLine("busy", s, s.split("busy:", 1)[1].strip())

    m = _RESEND_RE.match(s)
    if m:
        return RxLine("resend", s, int(m.group(1)))

    if low.startswith("error") or s.startswith("!!"):
        reason = s.split(":", 1)[1].strip() if ":" in s else s
        return RxLine("error", s, reason)

    if s.startswith("//action:"):
        return RxLine("action", s, s[len("//action:"):].strip())

    return RxLine("info", s)


def parse_temps(line: str) -> dict[str, tuple[float, float]]:
    """Return `{'nozzle': (cur, target), 'bed': (cur, target)}` for whatever is present."""
    out: dict[str, tuple[float, float]] = {}
    m = _TEMP_RE.search(line)
    if m:
        out["nozzle"] = (float(m.group(1)), float(m.group(2)))
    m = _BED_RE.search(line)
    if m:
        out["bed"] = (float(m.group(1)), float(m.group(2)))
    return out


def parse_position(line: str) -> tuple[float, float, float, float | None] | None:
    """Parse an `M114` reply: `X:.. Y:.. Z:.. [E:..] Count ...` -> (x, y, z, e|None)."""
    m = _POS_RE.search(line)
    if not m:
        return None
    e = float(m.group(4)) if m.group(4) is not None else None
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)), e)
