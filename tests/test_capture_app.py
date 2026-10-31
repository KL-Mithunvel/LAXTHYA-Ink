"""The capture app's API: consent, sessions, chunks, resume, live feed, and the laptop-only monitor."""

import gzip
import json

import pytest
from fastapi.testclient import TestClient

from laxthya_ink.capture.prompts import load_prompt_set
from laxthya_ink.capture.server import create_app
from laxthya_ink.capture.store import Store

PROMPTS = load_prompt_set("core-v1")
CHUNK1, CHUNK2 = PROMPTS["chunks"][0]["id"], PROMPTS["chunks"][1]["id"]


def _stroke(t0, *, x0=10.0, n=5):
    """One pen stroke: hover, down, moves, up."""
    ev = [{"k": "pointermove", "t": t0, "x": x0 - 5, "y": 20.0, "pt": "pen", "b": 0, "pressure": 0.0}]
    ev.append({"k": "pointerdown", "t": t0 + 1, "x": x0, "y": 20.0, "pt": "pen", "b": 1, "pressure": 0.08})
    for i in range(n):
        ev.append({"k": "pointermove", "t": t0 + 2 + i, "x": x0 + i, "y": 20.0 + i, "pt": "pen", "b": 1,
                   "pressure": 0.3, "tiltX": 5.0, "tiltY": 6.0, "altitudeAngle": 1.0, "azimuthAngle": 0.5})
    ev.append({"k": "pointerup", "t": t0 + 3 + n, "x": x0 + n, "y": 20.0 + n, "pt": "pen", "b": 0, "pressure": 0.0})
    return ev


@pytest.fixture
def env(config, tmp_path):
    store = Store(tmp_path / "capture.db", tmp_path / "backup")
    app = create_app(config, probe_dir=tmp_path / "probe", store=store, local_hosts=("testclient",))
    return TestClient(app), store, app


def _writer_and_session(client, **kw):
    w = client.post("/api/writers", json={"consent_project": True, "consent_sharing": False, "note": "Ann"}).json()
    s = client.post("/api/sessions", json={"writer_id": w["writer_id"], "protector": True, **kw}).json()
    return w["writer_id"], s


# --- pages and prompts ------------------------------------------------------

def test_capture_page_and_prompts(env):
    client, *_ = env
    assert "Handwriting capture" in client.get("/capture").text
    ps = client.get("/api/prompts").json()
    assert ps["id"] == "core-v1" and ps["chunks"] and ps["style"] == "natural"


def test_consent_text_is_what_writers_read_and_flags_blanks(env):
    client, *_ = env
    body = client.get("/api/consent").json()
    assert body["text"].startswith("## What this is")
    assert "Your choices" not in body["text"]
    assert body["version"] == "2026-10-30-v1"
    assert body["has_placeholders"] is True          # the draft still has [brackets]


# --- writers and sessions -------------------------------------------------

def test_no_writer_without_project_consent(env):
    client, store, _ = env
    r = client.post("/api/writers", json={"consent_project": False, "consent_sharing": True})
    assert r.status_code == 422
    assert store.list_writers() == []


def test_consent_must_be_literal_true(env):
    client, store, _ = env
    assert client.post("/api/writers", json={"consent_project": "yes"}).status_code == 422
    assert store.list_writers() == []


def test_sharing_tick_is_stored_separately(env):
    client, store, _ = env
    wid = client.post("/api/writers", json={"consent_project": True, "consent_sharing": True}).json()["writer_id"]
    assert store.get_writer(wid)["consent_sharing"] == 1 and store.get_writer(wid)["consent_version"] == "2026-10-30-v1"


def test_session_starts_then_resumes(env):
    client, store, _ = env
    wid, first = _writer_and_session(client, device={"ipad": "M4"})
    assert first["resumed"] is False and first["total_chunks"] == len(PROMPTS["chunks"])
    again = client.post("/api/sessions", json={"writer_id": wid}).json()
    assert again["resumed"] is True and again["session_id"] == first["session_id"]
    sess = store.get_session(first["session_id"])
    assert sess["device"] == {"ipad": "M4"} and sess["protector"] == 1 and sess["mm_per_px"] == pytest.approx(0.1924)


def test_unknown_writer_is_404(env):
    assert env[0].post("/api/sessions", json={"writer_id": "W099"}).status_code == 404


# --- chunks ----------------------------------------------------------------

def test_chunk_is_stored_with_its_text_and_progress_updates(env):
    client, store, _ = env
    wid, s = _writer_and_session(client)
    sid = s["session_id"]
    r = client.post(f"/api/sessions/{sid}/chunks/{CHUNK1}", json={"events": _stroke(100.0)})
    assert r.status_code == 200 and r.json()["stored"] == 8 and r.json()["duplicate"] is False and r.json()["done"] == 1
    assert client.get(f"/api/sessions/{sid}").json()["done_chunks"] == [CHUNK1]
    info = store.chunk_info(sid)
    assert info[0]["text"] == "\n".join(PROMPTS["chunks"][0]["lines"]) and info[0]["prompt_seq"] == 1


def test_a_repeated_upload_is_not_stored_twice(env):
    client, store, _ = env
    _, s = _writer_and_session(client)
    sid = s["session_id"]
    url = f"/api/sessions/{sid}/chunks/{CHUNK1}"
    client.post(url, json={"events": _stroke(100.0)})
    again = client.post(url, json={"events": _stroke(100.0)})
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert len(store.read_strokes(sid)) == 1


def test_touch_events_are_dropped_but_pen_events_kept(env):
    client, store, _ = env
    _, s = _writer_and_session(client)
    palm = [{"k": "pointermove", "t": 1.0, "x": 1.0, "y": 1.0, "pt": "touch", "b": 1}]
    r = client.post(f"/api/sessions/{s['session_id']}/chunks/{CHUNK1}", json={"events": palm + _stroke(5.0)})
    assert r.json()["skipped_touch"] == 1 and r.json()["stored"] == 8


@pytest.mark.parametrize("events,code", [([], 422), ("nope", 422)])
def test_empty_or_bad_chunk_is_rejected_and_not_marked_done(env, events, code):
    client, _, _ = env
    _, s = _writer_and_session(client)
    r = client.post(f"/api/sessions/{s['session_id']}/chunks/{CHUNK1}", json={"events": events})
    assert r.status_code == code
    assert client.get(f"/api/sessions/{s['session_id']}").json()["done_chunks"] == []


def test_unknown_chunk_session_and_body(env):
    client, _, _ = env
    _, s = _writer_and_session(client)
    sid = s["session_id"]
    assert client.post(f"/api/sessions/{sid}/chunks/nope-999", json={"events": _stroke(1.0)}).status_code == 404
    assert client.post(f"/api/sessions/999/chunks/{CHUNK1}", json={"events": _stroke(1.0)}).status_code == 404
    assert client.post(f"/api/sessions/{sid}/chunks/{CHUNK1}", content="[1]").status_code == 400
    assert client.get("/api/sessions/999").status_code == 404


def test_resume_reports_the_chunks_already_stored(env):
    client, _, _ = env
    wid, s = _writer_and_session(client)
    client.post(f"/api/sessions/{s['session_id']}/chunks/{CHUNK1}", json={"events": _stroke(1.0)})
    resumed = client.post("/api/sessions", json={"writer_id": wid}).json()
    assert resumed["resumed"] and resumed["done_chunks"] == [CHUNK1]


def test_finish_derives_strokes_and_writes_a_backup_without_the_note(env, tmp_path):
    client, store, _ = env
    wid, s = _writer_and_session(client)
    sid = s["session_id"]
    client.post(f"/api/sessions/{sid}/chunks/{CHUNK1}", json={"events": _stroke(1.0) + _stroke(50.0, x0=40.0)})
    r = client.post(f"/api/sessions/{sid}/finish").json()
    assert r["strokes"] == 2 and r["complete"] is False and r["done"] == 1
    assert store.get_session(sid)["ended_at"]
    assert client.post("/api/sessions", json={"writer_id": wid}).json()["resumed"] is False   # finished: next is a new one
    backups = list((tmp_path / "backup" / wid).glob("*.json.gz"))
    assert len(backups) == 1 and "Ann" not in gzip.open(backups[0], "rt", encoding="utf-8").read()


# --- live feed and the laptop-only monitor ----------------------------------------

def test_live_events_reach_the_monitor_and_replace_clears(env):
    client, _, _ = env
    wid, s = _writer_and_session(client)
    sid = s["session_id"]
    body = {"chunk_id": CHUNK1, "text": "hello", "canvas": {"w": 900, "h": 600}, "events": _stroke(1.0)}
    assert client.post(f"/api/live/{sid}", json=body).status_code == 200
    feed = client.get("/api/monitor/live?after=0").json()
    assert len(feed["entries"]) == 8 and feed["sessions"][0]["live"] is True
    assert feed["sessions"][0]["writer_id"] == wid and feed["sessions"][0]["canvas"] == {"w": 900, "h": 600}
    client.post(f"/api/live/{sid}", json={**body, "replace": True, "events": []})
    later = client.get(f"/api/monitor/live?after={feed['cursor']}").json()
    assert [e.get("reset") for e in later["entries"]] == [True]


def test_live_needs_a_known_session_and_events(env):
    client, _, _ = env
    assert client.post("/api/live/77", json={"events": []}).status_code == 404
    _, s = _writer_and_session(client)
    assert client.post(f"/api/live/{s['session_id']}", json={"events": "x"}).status_code == 422


def test_monitor_reads_back_stored_data(env):
    client, _, _ = env
    wid, s = _writer_and_session(client)
    sid = s["session_id"]
    client.post(f"/api/sessions/{sid}/chunks/{CHUNK1}", json={"events": _stroke(1.0)})
    client.post(f"/api/sessions/{sid}/chunks/{CHUNK2}", json={"events": _stroke(1.0) + _stroke(30.0)})

    writers = client.get("/api/monitor/writers").json()
    assert writers[0]["id"] == wid and writers[0]["note"] == "Ann" and writers[0]["chunks_done"] == 2

    sess = client.get(f"/api/monitor/writers/{wid}/sessions").json()
    assert sess["total_chunks"] == len(PROMPTS["chunks"]) and sess["sessions"][0]["chunks_done"] == 2

    detail = client.get(f"/api/monitor/sessions/{sid}").json()
    assert [c["prompt_seq"] for c in detail["chunks"]] == [1, 2] and detail["chunks"][0]["section"] == "en-words"
    assert detail["note"] == "Ann"

    strokes = client.get(f"/api/monitor/sessions/{sid}/strokes?chunk=2").json()["strokes"]
    assert len(strokes) == 2 and all(s["chunk"] == 2 and s["completed"] for s in strokes)
    assert strokes[0]["points"][0][:3] == [10.0, 20.0, 0.08]
    assert len(client.get(f"/api/monitor/sessions/{sid}/strokes").json()["strokes"]) == 3


def test_monitor_404s(env):
    client, _, _ = env
    assert client.get("/api/monitor/writers/W099/sessions").status_code == 404
    assert client.get("/api/monitor/sessions/99").status_code == 404
    assert client.get("/api/monitor/sessions/99/strokes").status_code == 404


def test_monitor_page_is_served_to_the_laptop(env):
    assert "Capture monitor" in env[0].get("/monitor").text


def test_monitor_is_refused_to_other_devices_on_the_network(config, tmp_path):
    """The default only trusts 127.0.0.1 / ::1; the test client's own address is not one of them."""
    store = Store(tmp_path / "capture.db", tmp_path / "backup")
    client = TestClient(create_app(config, probe_dir=tmp_path / "p", store=store))
    for url in ("/monitor", "/api/monitor/live", "/api/monitor/writers", "/api/monitor/sessions/1",
                "/api/monitor/sessions/1/strokes", "/api/monitor/writers/W001/sessions"):
        assert client.get(url).status_code == 403, url
    # the iPad's endpoints stay open
    assert client.get("/capture").status_code == 200
    assert client.get("/api/prompts").status_code == 200
