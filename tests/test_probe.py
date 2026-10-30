import pytest

from laxthya_ink.capture.probe import FIELDS, format_report, summarise
from laxthya_ink.exceptions import ProbeDataError

DT = 1000 / 240      # 240 Hz


def _ev(kind, t, *, b=1, pt="pen", **fields):
    return {"k": kind, "t": t, "x": t, "y": 0.0, "pt": pt, "b": b, "id": 1, "c": 0, **fields}


def _pen_session(*, twist_varies=False, hover=True):
    """Hover, then 50 pen-down moves at 240 Hz with varying pressure and tilt."""
    events = []
    if hover:
        events += [_ev("pointermove", i * DT, b=0, pressure=0.0, tiltX=0.0, tiltY=0.0, twist=0) for i in range(10)]
    start = 100.0
    events.append(_ev("pointerdown", start, pressure=0.2, tiltX=10.0, tiltY=5.0, twist=0))
    for i in range(1, 51):
        events.append(_ev("pointermove", start + i * DT, pressure=0.2 + i / 100, tiltX=10.0 + i,
                          tiltY=5.0, twist=(i if twist_varies else 0)))
    events.append(_ev("pointerup", start + 51 * DT, b=0, pressure=0.0))
    return {"meta": {"features": {"coalescedEvents": True, "predictedEvents": False}}, "events": events}


def test_sample_rate_and_varying_fields():
    s = summarise(_pen_session())
    assert s["timing"]["pen"]["rate_hz"] == pytest.approx(240, rel=0.01)
    fields = s["groups"]["pen/contact"]["fields"]
    assert fields["pressure"]["varies"] and fields["tiltX"]["varies"]
    assert fields["tiltY"]["varies"] is False                     # constant 5.0
    assert fields["altitudeAngle"]["present"] is False            # never reported


def test_paired_timestamps_count_every_sample_and_are_flagged():
    """Safari stamps a whole frame alike: 2 samples per 16.67 ms frame is ~120 samples/s, not 60."""
    frame = 1000 / 60
    events = [_ev("pointerdown", 0.0, pressure=0.1)]
    for i in range(1, 121):
        events.append(_ev("pointermove", (i // 2) * frame, pressure=0.1 + i / 1000))
    s = summarise({"events": events})
    timing = s["timing"]["pen"]
    assert timing["rate_hz"] == pytest.approx(120, rel=0.05)
    assert timing["median_interval_ms"] == pytest.approx(frame, rel=0.01)
    assert timing["zero_interval_share"] == pytest.approx(0.5, abs=0.05)
    assert any("quantised" in f for f in s["findings"])


def test_pause_between_strokes_does_not_distort_the_rate():
    frame = 1000 / 120
    first = [_ev("pointermove", i * frame) for i in range(30)]
    second = [_ev("pointermove", 5000 + i * frame) for i in range(30)]    # 5 s later
    assert summarise({"events": first + second})["timing"]["pen"]["rate_hz"] == pytest.approx(120, rel=0.05)


def test_twist_constant_vs_varying():
    assert summarise(_pen_session())["groups"]["pen/contact"]["fields"]["twist"]["varies"] is False
    assert summarise(_pen_session(twist_varies=True))["groups"]["pen/contact"]["fields"]["twist"]["varies"] is True


def test_hover_events_counted_separately():
    s = summarise(_pen_session())
    assert s["groups"]["pen/hover"]["count"] == 10
    assert any("Hover: 10 pen events" in f for f in s["findings"])


def test_no_hover_is_reported():
    s = summarise(_pen_session(hover=False))
    assert "pen/hover" not in s["groups"]
    assert any("NO events while the pen is above" in f for f in s["findings"])


def test_hover_height_is_always_flagged_unavailable():
    assert any("Hover HEIGHT" in f for f in summarise(_pen_session())["findings"])


def test_finger_only_session_says_so():
    events = [_ev("pointermove", i * 10.0, pt="touch", pressure=0.5) for i in range(5)]
    s = summarise({"events": events})
    assert s["findings"][0].startswith("NO Apple Pencil events")


def test_pen_that_never_touches():
    events = [_ev("pointermove", i * 4.0, b=0) for i in range(5)]
    assert any("never touched" in f for f in summarise({"events": events})["findings"])


def test_coalesced_share_reported():
    payload = _pen_session()
    for ev in payload["events"][::2]:
        ev["c"] = 1
    share = summarise(payload)["timing"]["pen"]["coalesced_share"]
    assert 0.4 < share < 0.6


def test_report_is_readable_text():
    text = format_report(summarise(_pen_session()))
    assert text.startswith("LAXTHYA-Ink signal probe")
    assert "pressure: varies" in text


@pytest.mark.parametrize("payload", [
    [], {"events": []}, {"events": "no"}, {"events": [1]},
    {"events": [{"k": "pointermove"}]},
    {"events": [{"k": "pointermove", "pt": "pen", "t": "x", "x": 0, "y": 0, "b": 0}]},
    {"events": [{"k": "pointermove", "pt": "pen", "t": 0, "x": 0, "y": 0, "b": True}]},
    {"meta": 3, "events": [_ev("pointermove", 0)]},
])
def test_malformed_uploads_rejected(payload):
    with pytest.raises(ProbeDataError):
        summarise(payload)


def test_fields_list_matches_page():
    # The page and the analysis must agree on which fields exist.
    html = (__import__("pathlib").Path(__file__).parent.parent
            / "laxthya_ink" / "capture" / "static" / "probe.html").read_text(encoding="utf-8")
    for name in FIELDS:
        assert f'"{name}"' in html
