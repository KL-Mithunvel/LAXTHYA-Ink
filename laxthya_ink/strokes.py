"""Stroke data: the one interchange format between capture, the writer model and the planner.

A *stroke* is one pen-down-to-pen-up trace: an ordered list of points. A *line*
is a list of strokes written on one baseline. A job is a list of lines.

Coordinates are in **writing units**: x grows to the right, **y grows upward**,
and the baseline of the line is y = 0 (descenders are negative). The planner
scales units to millimetres (`writing.scale_mm_per_unit`). A tablet reports y
growing downward - the capture side must flip it before it reaches this module.

File format (JSON)::

    {"version": 1,
     "lines": [
       {"strokes": [ [[x, y], [x, y, t, pressure], ...], ... ]},
       ...
     ]}

Each point is `[x, y]` with optional `t` (seconds) and `pressure` (0..1). The
planner uses only x and y today; `t` and `pressure` are carried for the writer
model and a later pressure-aware planner.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import StrokeDataError

FORMAT_VERSION = 1


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    t: float | None = None
    pressure: float | None = None


@dataclass
class Stroke:
    points: list[Point] = field(default_factory=list)


#: one baseline of writing
Line = list[Stroke]


def _parse_point(raw: object, where: str) -> Point:
    if not isinstance(raw, (list, tuple)) or not 2 <= len(raw) <= 4:
        raise StrokeDataError(f"{where}: a point must be [x, y] or [x, y, t, pressure], got {raw!r}")
    values: list[float | None] = []
    for item in raw:
        if item is None:
            values.append(None)
            continue
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise StrokeDataError(f"{where}: point values must be finite numbers, got {raw!r}")
        values.append(float(item))
    if values[0] is None or values[1] is None:
        raise StrokeDataError(f"{where}: x and y are required, got {raw!r}")
    padded = values + [None] * (4 - len(values))
    return Point(padded[0], padded[1], padded[2], padded[3])  # type: ignore[arg-type]


def parse_lines(data: object) -> list[Line]:
    """Turn the decoded JSON structure into lines of strokes. Raises `StrokeDataError`."""
    if not isinstance(data, dict):
        raise StrokeDataError("stroke file must be a JSON object")
    if data.get("version") != FORMAT_VERSION:
        raise StrokeDataError(
            f"unsupported stroke file version {data.get('version')!r} (expected {FORMAT_VERSION})"
        )
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise StrokeDataError("stroke file needs a non-empty 'lines' list")

    lines: list[Line] = []
    for li, raw_line in enumerate(raw_lines):
        raw_strokes = raw_line.get("strokes") if isinstance(raw_line, dict) else None
        if not isinstance(raw_strokes, list):
            raise StrokeDataError(f"line {li}: needs a 'strokes' list")
        line: Line = []
        for si, raw_stroke in enumerate(raw_strokes):
            if not isinstance(raw_stroke, list) or not raw_stroke:
                raise StrokeDataError(f"line {li} stroke {si}: needs at least one point")
            where = f"line {li} stroke {si}"
            line.append(Stroke([_parse_point(p, where) for p in raw_stroke]))
        lines.append(line)
    return lines


def load_strokes(path: str | Path) -> list[Line]:
    """Read a stroke JSON file. Raises `StrokeDataError` (bad content) or `OSError` (unreadable)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StrokeDataError(f"{path}: not valid JSON ({exc})") from exc
    return parse_lines(data)
