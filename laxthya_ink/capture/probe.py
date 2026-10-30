"""Analyse a signal-probe upload: what does this iPad + Pencil really report to Safari?

Pure logic, no I/O. The probe page (`static/probe.html`) records every pointer
event with every numeric field the browser exposes and uploads
`{"meta": {...}, "events": [...]}`. `summarise` turns that into facts:
which fields actually vary, whether hover events arrive, the sample rate, and
which browser features exist. The answers decide whether the web capture app is
enough or a native app is needed (docs/PROJECT_PLAN.md -> Capture signals).

Event fields (compact keys, set by the page): `k` event type, `t` timestamp (ms),
`x`, `y` client coordinates, `pt` pointerType, `b` buttons, `id` pointerId,
`c` 1 if it came from `getCoalescedEvents()`, plus any of `FIELDS`.
"""

from __future__ import annotations

from statistics import median

from ..exceptions import ProbeDataError

#: numeric PointerEvent fields the page records, when the browser provides them
FIELDS = (
    "pressure", "tiltX", "tiltY", "altitudeAngle", "azimuthAngle",
    "twist", "width", "height", "tangentialPressure",
)

_CONTACT_KINDS = ("pointerdown", "pointerup", "pointercancel")
#: a field with at most this many distinct values is reported as constant
_ROUND_DIGITS = 4


def _validate(payload: object) -> tuple[dict, list[dict]]:
    if not isinstance(payload, dict):
        raise ProbeDataError("probe upload must be a JSON object")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise ProbeDataError("probe upload needs a non-empty 'events' list")
    meta = payload.get("meta", {})
    if not isinstance(meta, dict):
        raise ProbeDataError("'meta' must be an object")
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            raise ProbeDataError(f"event {i}: must be an object")
        if not isinstance(ev.get("k"), str) or not isinstance(ev.get("pt"), str):
            raise ProbeDataError(f"event {i}: needs string fields 'k' and 'pt'")
        for key in ("t", "x", "y", "b"):
            v = ev.get(key)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ProbeDataError(f"event {i}: field {key!r} must be a number, got {v!r}")
    return meta, events


def _group(ev: dict) -> str | None:
    """'hover' (pen moving with nothing pressed), 'contact', or None for raw updates."""
    kind = ev["k"]
    if kind == "pointermove":
        return "hover" if ev["b"] == 0 else "contact"
    if kind in _CONTACT_KINDS:
        return "contact"
    return None


def _field_stats(events: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in FIELDS:
        values = [ev[name] for ev in events if isinstance(ev.get(name), (int, float))]
        if not values:
            out[name] = {"present": False, "varies": False}
            continue
        distinct = len({round(v, _ROUND_DIGITS) for v in values})
        out[name] = {
            "present": True,
            "min": min(values),
            "max": max(values),
            "distinct": distinct,
            "varies": distinct > 1,
        }
    return out


#: a gap between consecutive pen-down samples longer than this is a pause between
#: strokes, not part of the sampling rhythm
_STROKE_GAP_MS = 100.0


def _timing(events: list[dict]) -> dict:
    """Sample timing over contact `pointermove` events of one pointer type.

    `rate_hz` counts every sample inside strokes, so samples that share a
    timestamp (Safari stamps a whole frame alike) still count. `median_interval_ms`
    is the gap between *distinct* timestamps, i.e. the frame time.
    """
    stamps = [ev["t"] for ev in events if ev["k"] == "pointermove" and ev["b"] > 0]
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    moving = [g for g in gaps if 0 <= g <= _STROKE_GAP_MS]       # inside a stroke
    positive = [g for g in moving if g > 0]
    duration = sum(moving)
    if not positive or duration <= 0:
        return {"samples": len(stamps)}
    return {
        "samples": len(stamps),
        "median_interval_ms": median(positive),
        "rate_hz": 1000.0 * len(moving) / duration,
        "zero_interval_share": (len(moving) - len(positive)) / len(moving),
        "coalesced_share": sum(1 for ev in events if ev.get("c")) / len(events),
    }


def summarise(payload: object) -> dict:
    """Return the facts in an upload. Raises `ProbeDataError` on a malformed one."""
    meta, events = _validate(payload)

    by_type: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    groups: dict[str, list[dict]] = {}
    per_type: dict[str, list[dict]] = {}
    for ev in events:
        by_type[ev["pt"]] = by_type.get(ev["pt"], 0) + 1
        by_kind[ev["k"]] = by_kind.get(ev["k"], 0) + 1
        per_type.setdefault(ev["pt"], []).append(ev)
        group = _group(ev)
        if group:
            groups.setdefault(f"{ev['pt']}/{group}", []).append(ev)

    summary = {
        "event_count": len(events),
        "by_pointer_type": by_type,
        "by_kind": by_kind,
        "groups": {name: {"count": len(evs), "fields": _field_stats(evs)} for name, evs in groups.items()},
        "timing": {pt: _timing(evs) for pt, evs in per_type.items()},
        "features": meta.get("features", {}),
        "device": {k: meta.get(k) for k in ("userAgent", "screen", "devicePixelRatio", "viewport") if k in meta},
    }
    summary["findings"] = _findings(summary)
    return summary


def _findings(s: dict) -> list[str]:
    """Plain-language conclusions, one per question we care about."""
    out: list[str] = []
    types = s["by_pointer_type"]
    if "pen" not in types:
        seen = ", ".join(f"{k} ({v})" for k, v in types.items())
        out.append(f"NO Apple Pencil events: only {seen}. Draw with the Pencil, not a finger or mouse.")
        return out
    out.append(f"Pencil events seen: {types['pen']}.")

    contact = s["groups"].get("pen/contact")
    if contact is None:
        out.append("No pen-down samples: the Pencil never touched the screen.")
    else:
        fields = contact["fields"]
        for name, label in (
            ("pressure", "pressure"), ("tiltX", "tilt X"), ("tiltY", "tilt Y"),
            ("altitudeAngle", "altitude angle"), ("azimuthAngle", "azimuth angle"),
            ("twist", "twist (barrel roll)"), ("tangentialPressure", "tangential pressure"),
        ):
            f = fields[name]
            if not f["present"]:
                out.append(f"{label}: NOT reported by this browser.")
            elif f["varies"]:
                out.append(f"{label}: varies ({f['min']:.3g} to {f['max']:.3g}, {f['distinct']} distinct values).")
            else:
                out.append(f"{label}: reported but CONSTANT at {f['min']:.3g} - not usable (did you do that move?).")

    timing = s["timing"].get("pen", {})
    if "rate_hz" in timing:
        out.append(
            f"Pen-down sample rate: about {timing['rate_hz']:.0f} samples per second "
            f"({timing['samples']} samples; {timing['coalesced_share']:.0%} came from the coalesced list)."
        )
        if timing["zero_interval_share"] > 0.05:
            out.append(
                f"Timestamps are quantised: {timing['zero_interval_share']:.0%} of consecutive samples share a "
                f"timestamp (distinct timestamps are {timing['median_interval_ms']:.1f} ms apart), so the exact "
                f"time of a sample inside a frame is lost and can only be interpolated."
            )
    else:
        out.append(f"Pen-down sample rate: not enough moving samples ({timing.get('samples', 0)}).")

    hover = s["groups"].get("pen/hover")
    if hover:
        out.append(f"Hover: {hover['count']} pen events arrived with nothing pressed, so the path between strokes is visible.")
    else:
        out.append("Hover: NO events while the pen is above the screen, so the path between strokes is not visible to the web page.")
    out.append("Hover HEIGHT (z): Pointer Events have no distance-above-screen field, so it is not available from Safari either way.")

    feats = s.get("features") or {}
    for name in ("coalescedEvents", "predictedEvents", "rawUpdate"):
        if name in feats:
            out.append(f"Browser feature {name}: {'yes' if feats[name] else 'no'}.")
    return out


def format_report(summary: dict) -> str:
    """The summary as readable text, for the page and the saved .txt file."""
    lines = ["LAXTHYA-Ink signal probe", "=" * 24, ""]
    lines += [f"- {f}" for f in summary["findings"]]
    lines += ["", f"Events: {summary['event_count']}  by type {summary['by_pointer_type']}", f"By kind: {summary['by_kind']}"]
    if summary["device"]:
        lines.append(f"Device: {summary['device']}")
    return "\n".join(lines) + "\n"
