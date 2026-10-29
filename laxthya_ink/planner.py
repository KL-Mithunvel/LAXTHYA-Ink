"""Turn lines of strokes into G-code that draws them with a pen.

Pure logic - no I/O, no printer. Pipeline:

  layout     writing units -> pen-tip bed coordinates (mm); baseline per line;
             refuses anything that falls off the configured paper area
  simplify   drop near-duplicate points, then Ramer-Douglas-Peucker
  emit       pen-tip -> nozzle coordinates (minus the pen offset), machine-limit
             check, then G-code: travel pen-up, lower, draw, lift

The pen is lifted and lowered with Z only (no servo): pen-up Z is
`pen.down_z + pen.lift_mm`. Nothing here sends heater or extrusion commands.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .exceptions import OutOfEnvelopeError, WritingAreaError
from .gcode.util import fmt_number
from .strokes import Line

Pt = tuple[float, float]
_EPS = 1e-9


@dataclass
class Plan:
    """A planned job. `segments` are the pen-tip polylines in bed mm, in drawing order."""

    gcode: list[str]
    segments: list[list[Pt]]
    stroke_count: int
    point_count: int
    draw_length_mm: float


# --- geometry ---------------------------------------------------------------

def _dist(a: Pt, b: Pt) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_segment_distance(p: Pt, a: Pt, b: Pt) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq < _EPS:
        return _dist(p, a)                 # degenerate segment (e.g. a closed loop's ends)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq))
    return _dist(p, (a[0] + t * dx, a[1] + t * dy))


def dedupe(points: list[Pt], min_spacing: float) -> list[Pt]:
    """Drop points closer than `min_spacing` to the previously kept one; keep the last point."""
    if len(points) < 2 or min_spacing <= 0:
        return list(points)
    out = [points[0]]
    for p in points[1:]:
        if _dist(p, out[-1]) >= min_spacing:
            out.append(p)
    if out[-1] != points[-1] and _dist(points[-1], out[-1]) > 0:
        out.append(points[-1])
    return out


def simplify(points: list[Pt], tolerance: float) -> list[Pt]:
    """Ramer-Douglas-Peucker, iterative. Endpoints are always kept."""
    n = len(points)
    if n < 3 or tolerance <= 0:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        worst, worst_i = 0.0, -1
        for i in range(a + 1, b):
            d = _point_segment_distance(points[i], points[a], points[b])
            if d > worst:
                worst, worst_i = d, i
        if worst > tolerance:
            keep[worst_i] = True
            stack.append((a, worst_i))
            stack.append((worst_i, b))
    return [p for p, k in zip(points, keep) if k]


# --- layout -----------------------------------------------------------------

def layout(lines: list[Line], config: dict) -> list[list[Pt]]:
    """Place strokes on the paper: returns pen-tip polylines in bed mm, in order.

    Line `i` has its baseline `(i + 1) * line_spacing_mm` below the top of the
    paper area. Raises `WritingAreaError` if any point leaves the paper area.
    """
    paper, writing = config["paper"], config["writing"]
    scale, spacing = writing["scale_mm_per_unit"], writing["line_spacing_mm"]
    x_lo, x_hi = paper["origin_x"], paper["origin_x"] + paper["width_mm"]
    y_lo, y_hi = paper["origin_y"], paper["origin_y"] + paper["height_mm"]

    polylines: list[list[Pt]] = []
    for li, line in enumerate(lines):
        baseline_y = y_hi - (li + 1) * spacing
        for si, stroke in enumerate(line):
            poly: list[Pt] = []
            for pt in stroke.points:
                x = x_lo + pt.x * scale
                y = baseline_y + pt.y * scale
                if not (x_lo - _EPS <= x <= x_hi + _EPS and y_lo - _EPS <= y <= y_hi + _EPS):
                    raise WritingAreaError(
                        f"line {li} stroke {si}: point ({x:.2f}, {y:.2f}) mm is outside the paper "
                        f"area x {x_lo:g}..{x_hi:g}, y {y_lo:g}..{y_hi:g} - shorten the text, "
                        f"lower writing.scale_mm_per_unit, or enlarge the paper area"
                    )
                poly.append((x, y))
            polylines.append(simplify(
                dedupe(poly, writing["min_point_spacing_mm"]), writing["simplify_tolerance_mm"]
            ))
    return polylines


# --- G-code ---------------------------------------------------------------

def pen_heights(config: dict) -> tuple[float, float, float]:
    """Return (pen-down Z, pen-up Z, safe Z), validated against the machine and `pen.min_z`."""
    pen, z_max = config["pen"], config["machine"]["z_max"]
    down = pen["down_z"]
    up = down + pen["lift_mm"]
    safe = config["park"]["safe_z"]
    if down < pen["min_z"]:
        raise OutOfEnvelopeError(f"pen.down_z {down:g} is below pen.min_z {pen['min_z']:g}")
    if max(up, safe) > z_max:
        raise OutOfEnvelopeError(f"pen-up Z {up:g} / safe Z {safe:g} exceeds machine.z_max {z_max:g}")
    return down, up, safe


class _Emitter:
    """Builds G-code lines; repeats `F` only when the feedrate changes."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._feed: float | None = None

    def raw(self, text: str) -> None:
        self.lines.append(text)

    def move(self, cmd: str, feed: float, *, x=None, y=None, z=None) -> None:
        words = [cmd]
        for letter, value in (("X", x), ("Y", y), ("Z", z)):
            if value is not None:
                words.append(f"{letter}{fmt_number(value)}")
        if feed != self._feed:
            words.append(f"F{fmt_number(feed)}")
            self._feed = feed
        self.lines.append(" ".join(words))


def _to_nozzle(poly: list[Pt], config: dict) -> list[Pt]:
    """Pen-tip -> nozzle coordinates, refusing positions outside the machine volume."""
    ox, oy = config["pen"]["offset_x"], config["pen"]["offset_y"]
    x_max, y_max = config["machine"]["x_max"], config["machine"]["y_max"]
    out: list[Pt] = []
    for x, y in poly:
        nx, ny = x - ox, y - oy
        if not (-_EPS <= nx <= x_max + _EPS and -_EPS <= ny <= y_max + _EPS):
            raise OutOfEnvelopeError(
                f"nozzle target ({nx:.2f}, {ny:.2f}) is outside the machine "
                f"0..{x_max:g} x 0..{y_max:g} (pen tip at ({x:.2f}, {y:.2f}), "
                f"pen offset ({ox:g}, {oy:g}))"
            )
        out.append((nx, ny))
    return out


def plan_job(lines: list[Line], config: dict) -> Plan:
    """Lay out `lines` on the paper and emit the G-code that draws them."""
    down, up, safe = pen_heights(config)
    segments = layout(lines, config)
    motion, park = config["motion"], config["park"]
    dwell_ms = config["pen"]["down_dwell_ms"]

    em = _Emitter()
    em.raw("; LAXTHYA-Ink handwriting job")
    em.raw("G21")
    em.raw("G90")
    if config["start"]["home"]:
        em.raw("G28")
    em.move("G0", motion["z_feed"], z=safe)

    point_count = 0
    draw_length = 0.0
    for poly in segments:
        if not poly:
            continue
        nozzle = _to_nozzle(poly, config)
        point_count += len(poly)
        draw_length += sum(_dist(a, b) for a, b in zip(poly, poly[1:]))
        em.move("G0", motion["travel_feed"], x=nozzle[0][0], y=nozzle[0][1])
        em.move("G1", motion["z_feed"], z=down)
        if dwell_ms > 0:
            em.raw(f"G4 P{fmt_number(dwell_ms)}")
        for nx, ny in nozzle[1:]:
            em.move("G1", motion["draw_feed"], x=nx, y=ny)
        em.move("G0", motion["z_feed"], z=up)

    em.move("G0", motion["z_feed"], z=safe)
    em.move("G0", motion["travel_feed"], x=park["x"], y=park["y"])
    em.raw("M400")

    return Plan(
        gcode=em.lines,
        segments=[p for p in segments if p],
        stroke_count=sum(1 for p in segments if p),
        point_count=point_count,
        draw_length_mm=draw_length,
    )


def safe_stop_commands(config: dict) -> list[str]:
    """G-code that lifts the pen clear and parks: sent after a cancel or a failure."""
    _, _, safe = pen_heights(config)
    motion, park = config["motion"], config["park"]
    em = _Emitter()
    em.raw("G90")
    em.move("G0", motion["z_feed"], z=safe)
    em.move("G0", motion["travel_feed"], x=park["x"], y=park["y"])
    em.raw("M400")
    return em.lines
