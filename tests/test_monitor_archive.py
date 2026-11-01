"""What the monitor can show of old data: capture overview, and the saved signal probes."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laxthya_ink.capture.probe import extract_paths
from laxthya_ink.capture.prompts import load_prompt_set
from laxthya_ink.config import load_config
from laxthya_ink.capture.server import create_app
from laxthya_ink.capture.store import Store
from laxthya_ink.exceptions import ProbeDataError
from tests.test_capture_app import _stroke
from tests.test_probe import _pen_session

PROMPTS = load_prompt_set(load_config()["capture"]["prompt_set_id"])


@pytest.fixture
def env(config, tmp_path):
    store = Store(tmp_path / "capture.db", tmp_path / "backup")
    app = create_app(config, probe_dir=tmp_path / "probe", store=store, local_hosts=("testclient",))
    return TestClient(app), store, tmp_path


def _ev(kind, t, x, y, *, b=1, pt="pen", pressure=0.3):
    return {"k": kind, "t": t, "x": x, "y": y, "pt": pt, "b": b, "pressure": pressure}


# --- the drawable paths of a probe ------------------------------------------------

def test_extract_paths_separates_strokes_from_hover_trails():
    events = [
        _ev("pointermove", 1, 5, 5, b=0), _ev("pointermove", 2, 6, 5, b=0),        # hover trail 1
        _ev("pointerdown", 3, 10, 10), _ev("pointermove", 4, 12, 11), _ev("pointerup", 5, 13, 12, b=0, pressure=0),
        _ev("pointermove", 6, 20, 20, b=0),                                         # hover trail 2
        _ev("pointerdown", 7, 30, 30), _ev("pointermove", 8, 31, 31), _ev("pointercancel", 9, 31, 31, b=0),
    ]
    paths = extract_paths({"events": events})
    assert [len(s) for s in paths["strokes"]] == [3, 3]
    assert paths["strokes"][0][0] == [10, 10, 0.3, 3] and paths["strokes"][0][-1][2] == 0
    assert [len(t) for t in paths["hover"]] == [2, 1]


def test_extract_paths_ignores_touch_and_stray_pressed_moves():
    events = [
        _ev("pointermove", 1, 1, 1, pt="touch"), _ev("pointerdown", 2, 2, 2, pt="touch"),
        _ev("pointermove", 3, 9, 9),                                                # pressed move with no pointerdown
    ]
    assert extract_paths({"events": events}) == {"strokes": [], "hover": []}


def test_extract_paths_rejects_a_malformed_upload():
    with pytest.raises(ProbeDataError):
        extract_paths({"events": []})


# --- store counters ----------------------------------------------------------------

def test_store_totals_and_collected_chunks(env):
    _, store, _ = env
    assert store.totals() == {"writers": 0, "sessions": 0, "chunks": 0, "samples": 0}
    w = store.add_writer(consent_project=True, consent_sharing=False, consent_version="v")
    s1 = store.start_session(w, style="natural", prompt_set="core-v1")
    s2 = store.start_session(w, style="natural", prompt_set="core-v1")
    store.save_chunk(s1, "a", 1, "t", _stroke(1.0))
    store.save_chunk(s2, "a", 1, "t", _stroke(1.0))                                # same chunk written again in a later session
    store.save_chunk(s2, "b", 2, "t", _stroke(1.0))
    assert store.collected_chunk_ids(w) == {"a", "b"}
    assert store.totals() == {"writers": 1, "sessions": 2, "chunks": 3, "samples": 24}


# --- overview endpoint -------------------------------------------------------------

def test_overview_without_a_writer_gives_totals_and_probe_count(env):
    client, _, _ = env
    client.post("/api/probe", content=json.dumps(_pen_session()))
    o = client.get("/api/monitor/overview").json()
    assert o["totals"]["probes"] == 1 and o["totals"]["writers"] == 0
    assert o["writer"] is None and o["sections"] == [] and o["prompt_set"]["chunks"] == len(PROMPTS["chunks"])


def test_overview_for_a_writer_counts_chunks_per_section(env):
    client, _, _ = env
    wid = client.post("/api/writers", json={"consent_project": True, "name": "Ann Example", "note": "Ann"}).json()["writer_id"]
    sid = client.post("/api/sessions", json={"writer_id": wid}).json()["session_id"]
    first_two = [c["id"] for c in PROMPTS["chunks"][:2]]
    for cid in first_two:
        client.post(f"/api/sessions/{sid}/chunks/{cid}", json={"events": _stroke(1.0)})
    o = client.get(f"/api/monitor/overview?writer={wid}").json()
    sections = {s["section"]: s for s in o["sections"]}
    assert o["writer"]["id"] == wid and o["totals"]["chunks"] == 2
    assert sections["en-words"]["done"] == 2
    assert sum(s["total"] for s in o["sections"]) == len(PROMPTS["chunks"])
    assert sum(s["done"] for s in o["sections"]) == 2


def test_overview_for_an_unknown_writer_is_404(env):
    assert env[0].get("/api/monitor/overview?writer=W099").status_code == 404


# --- probe endpoints ------------------------------------------------------------------

def test_saved_probes_are_listed_and_drawable(env):
    client, _, _ = env
    assert client.get("/api/monitor/probes").json() == []
    name = client.post("/api/probe", content=json.dumps(_pen_session())).json()["saved_as"]
    listing = client.get("/api/monitor/probes").json()
    assert [p["name"] for p in listing] == [name]
    assert listing[0]["pen_events"] == 62 and listing[0]["rate_hz"] == 240 and listing[0]["size_kb"] >= 0

    detail = client.get(f"/api/monitor/probes/{name}").json()
    assert detail["name"] == name and "signal probe" in detail["report"]
    assert len(detail["strokes"]) == 1 and len(detail["strokes"][0]) == 52          # down + 50 moves + up
    assert len(detail["hover"]) == 1 and len(detail["hover"][0]) == 10


def test_an_unreadable_probe_is_listed_with_its_error_not_hidden(env):
    client, _, tmp = env
    (tmp / "probe").mkdir()
    (tmp / "probe" / "probe-20261030-111111.json").write_text("{not json", encoding="utf-8")
    item = client.get("/api/monitor/probes").json()[0]
    assert item["name"] == "probe-20261030-111111" and "error" in item
    assert client.get("/api/monitor/probes/probe-20261030-111111").status_code == 422


@pytest.mark.parametrize("name", ["../secret", "probe-1", "probe-20261030-12345", "capture", "..%2Fx", "probe-20261030-123456.json"])
def test_probe_names_are_validated_before_any_file_is_opened(env, name):
    assert env[0].get(f"/api/monitor/probes/{name}").status_code in (404, 422)


def test_missing_probe_is_404(env):
    assert env[0].get("/api/monitor/probes/probe-20990101-000000").status_code == 404


def test_new_monitor_endpoints_are_laptop_only(config, tmp_path):
    store = Store(tmp_path / "capture.db", tmp_path / "backup")
    client = TestClient(create_app(config, probe_dir=tmp_path / "p", store=store))      # default: only 127.0.0.1 / ::1
    for url in ("/api/monitor/overview", "/api/monitor/probes", "/api/monitor/probes/probe-20261030-123914"):
        assert client.get(url).status_code == 403, url


# --- the same rule when drawing a saved probe; and a check against the real iPad recording ----------------------------

def test_extract_paths_keeps_a_stroke_whole_across_a_stale_hover_sample():
    events = [
        _ev("pointerdown", 18085, 128, 126), _ev("pointermove", 18077, 129, 126, b=0),        # stale hover, arrives late
        _ev("pointermove", 18106, 128, 126), _ev("pointermove", 18122, 128, 124), _ev("pointerup", 18150, 128, 122, b=0),
    ]
    paths = extract_paths({"events": events})
    assert [len(s) for s in paths["strokes"]] == [4]                  # down + 2 pressed moves + up
    assert paths["hover"] == []                                       # the stale sample is not a hover trail either


REAL_RECORDING = Path(__file__).resolve().parent.parent / "data" / "probe" / "probe-20261030-125553.json"


@pytest.mark.skipif(not REAL_RECORDING.exists(), reason="the iPad recording is local-only (data/ is not committed)")
def test_no_pressed_sample_of_the_real_recording_is_lost_from_its_strokes():
    """Before the fix 8 mid-stroke 'unpressed' samples cut strokes short. Every sample between a pen-down and its pen-up must survive."""
    events = [e for e in json.loads(REAL_RECORDING.read_text(encoding="utf-8"))["events"] if e["pt"] == "pen"]
    expected, inside = 0, False
    for e in events:
        if e["k"] == "pointerdown":
            inside, expected = True, expected + 1
        elif e["k"] in ("pointerup", "pointercancel"):
            if inside:
                expected += 1
            inside = False
        elif e["k"] == "pointermove" and inside and e["b"] > 0:
            expected += 1
    paths = extract_paths({"events": events})
    assert len(paths["strokes"]) == 13
    assert sum(len(s) for s in paths["strokes"]) == expected
