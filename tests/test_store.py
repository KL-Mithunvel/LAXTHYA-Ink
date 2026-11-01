import gzip
import json
import sqlite3

import pytest

from laxthya_ink.capture.store import Store
from laxthya_ink.exceptions import ConsentRequiredError, StoreError


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "capture.db", tmp_path / "backup")


def _writer(store, *, sharing=False, note="", name=""):
    return store.add_writer(consent_project=True, consent_sharing=sharing,
                            consent_version="test-v1", name=name, note=note)


def _ev(kind, t, x=10.0, y=20.0, *, b=1, pt="pen", **fields):
    return {"k": kind, "t": t, "x": x, "y": y, "pt": pt, "b": b, **fields}


# --- writers and consent ----------------------------------------------------

def test_writer_ids_are_sequential_and_store_consent(store):
    a, b = _writer(store), _writer(store, sharing=True, note="Ann, ward 3")
    assert (a, b) == ("W001", "W002")
    w = store.get_writer(b)
    assert (w["consent_project"], w["consent_sharing"], w["consent_version"]) == (1, 1, "test-v1")
    assert w["note"] == "Ann, ward 3" and w["consent_at"]


def test_no_writer_without_project_consent(store):
    with pytest.raises(ConsentRequiredError):
        store.add_writer(consent_project=False, consent_sharing=True, consent_version="v")
    assert store.list_writers() == []


def test_database_itself_refuses_missing_project_consent(store):
    with sqlite3.connect(store.db_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO writers (id, created_at, consent_project, consent_sharing, consent_version, consent_at)"
            " VALUES ('W009', 'now', 0, 0, 'v', 'now')")


def test_deleted_writer_ids_are_never_reused(store):
    first, second = _writer(store), _writer(store)
    store.delete_writer(second)
    assert _writer(store) == "W003"                      # not W002 again
    assert first == "W001"


def test_note_can_be_changed_and_unknown_writer_is_an_error(store):
    w = _writer(store)
    store.set_note(w, "new note")
    assert store.get_writer(w)["note"] == "new note"
    with pytest.raises(StoreError, match="unknown writer"):
        store.set_note("W099", "x")
    with pytest.raises(StoreError, match="unknown writer"):
        store.get_writer("W099")


def test_only_opted_in_writers_are_shareable(store):
    _writer(store, sharing=False)
    yes = _writer(store, sharing=True)
    assert store.shareable_writer_ids() == [yes]


@pytest.mark.parametrize("bad", ["", "w001", "W1", "../W001", "W001/../x", "W00a"])
def test_writer_ids_with_odd_shapes_are_refused(store, bad):
    with pytest.raises(StoreError, match="invalid writer id"):
        store.get_writer(bad)
    with pytest.raises(StoreError, match="invalid writer id"):
        store.delete_writer(bad)


# --- sessions and samples -------------------------------------------------

def test_session_needs_a_known_writer_and_a_known_style(store):
    w = _writer(store)
    with pytest.raises(StoreError, match="style"):
        store.start_session(w, style="gothic", prompt_set="core")
    with pytest.raises(StoreError, match="unknown writer"):
        store.start_session("W099", style="natural", prompt_set="core")
    assert store.start_session(w, style="cursive", prompt_set="en-pairs", device={"ipad": "M4"},
                               mm_per_px=0.096, protector=True) == 1


def test_samples_keep_all_fields_in_order_and_skip_touch(store):
    sid = store.start_session(_writer(store), style="natural", prompt_set="core")
    seq = store.add_prompt(sid, "The quick brown fox")
    events = [
        _ev("pointermove", 1.0, b=0, pressure=0.0, tiltX=0.0, tiltY=0.0, altitudeAngle=1.571, azimuthAngle=0.0),
        _ev("pointerdown", 2.0, pressure=0.08, tiltX=12.0, tiltY=-3.0, altitudeAngle=1.0, azimuthAngle=0.5),
        _ev("pointermove", 3.0, pt="touch", pressure=0.5),                     # palm: dropped
        _ev("pointermove", 4.0, x=11.5, pressure=0.4, tiltX=13.0, tiltY=-3.0, altitudeAngle=1.1, azimuthAngle=0.5),
    ]
    assert store.add_samples(sid, events, prompt_seq=seq) == {"stored": 3, "skipped_touch": 1}
    assert store.add_samples(sid, [_ev("pointerup", 5.0, b=0, pressure=0.0)]) == {"stored": 1, "skipped_touch": 0}
    with sqlite3.connect(store.db_path) as conn:
        rows = conn.execute("SELECT seq, kind, t, x, pressure, tilt_x, altitude, prompt_seq FROM samples ORDER BY seq").fetchall()
    assert [r[0] for r in rows] == [1, 2, 3, 4]                                # continues across batches
    assert rows[2] == (3, "pointermove", 4.0, 11.5, 0.4, 13.0, 1.1, 1)
    assert rows[3][7] is None


def test_a_malformed_event_rejects_the_whole_batch(store):
    sid = store.start_session(_writer(store), style="natural", prompt_set="core")
    with pytest.raises(StoreError, match="event 1"):
        store.add_samples(sid, [_ev("pointerdown", 1.0), {"k": "pointermove", "t": 2.0}])
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0


def test_samples_for_an_unknown_session_are_refused(store):
    with pytest.raises(StoreError):
        store.add_samples(99, [_ev("pointerdown", 1.0)])


# --- derived strokes ------------------------------------------------------

def _two_strokes_with_hover():
    return [
        _ev("pointermove", 1.0, b=0),                       # hover
        _ev("pointerdown", 2.0), _ev("pointermove", 3.0), _ev("pointermove", 4.0), _ev("pointerup", 5.0, b=0),
        _ev("pointermove", 6.0, b=0),                       # hover between strokes
        _ev("pointerdown", 7.0), _ev("pointermove", 8.0), _ev("pointercancel", 9.0, b=0),
    ]


def test_strokes_are_derived_from_samples_and_hover_stays_unassigned(store):
    sid = store.start_session(_writer(store), style="natural", prompt_set="core")
    store.add_samples(sid, _two_strokes_with_hover())
    assert store.derive_strokes(sid) == 2
    with sqlite3.connect(store.db_path) as conn:
        strokes = conn.execute("SELECT seq, n_samples, t_start, t_end, completed FROM strokes ORDER BY seq").fetchall()
        hover = conn.execute("SELECT COUNT(*) FROM samples WHERE stroke_id IS NULL").fetchone()[0]
    assert strokes == [(1, 4, 2.0, 5.0, 1), (2, 3, 7.0, 9.0, 0)]        # second was cancelled
    assert hover == 2


def test_deriving_twice_gives_the_same_result(store):
    sid = store.start_session(_writer(store), style="natural", prompt_set="core")
    store.add_samples(sid, _two_strokes_with_hover())
    assert store.derive_strokes(sid) == store.derive_strokes(sid) == 2
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM strokes").fetchone()[0] == 2


def test_a_stroke_cut_off_by_hover_is_marked_incomplete(store):
    sid = store.start_session(_writer(store), style="natural", prompt_set="core")
    store.add_samples(sid, [_ev("pointerdown", 1.0), _ev("pointermove", 2.0), _ev("pointermove", 3.0, b=0)])
    assert store.derive_strokes(sid) == 1
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT completed, n_samples FROM strokes").fetchone() == (0, 2)


# --- backup, export and deletion --------------------------------------------

def _session_with_data(store, writer):
    sid = store.start_session(writer, style="cursive", prompt_set="core", device={"ipad": "M4"})
    store.add_prompt(sid, "hello")
    store.add_samples(sid, _two_strokes_with_hover())
    store.derive_strokes(sid)
    return sid


def test_export_leaves_the_name_and_note_out_by_default(store):
    w = _writer(store, name="Ann Example", note="ward 3")
    path = store.export_session(_session_with_data(store, w))
    assert path.parent == store.backup_dir / w and path.name.endswith(".json.gz")
    text = gzip.open(path, "rt", encoding="utf-8").read()
    assert "Ann Example" not in text and "ward 3" not in text
    data = json.loads(text)
    assert "note" not in data["writer"] and "name" not in data["writer"] and data["writer"]["id"] == w
    assert data["session"]["device"] == {"ipad": "M4"}
    assert len(data["samples"]) == 9 and data["prompts"] == [{"seq": 1, "text": "hello"}]


def test_export_can_include_the_private_fields_when_asked(store):
    w = _writer(store, name="Ann Example", note="ward 3")
    path = store.export_session(_session_with_data(store, w), include_private=True)
    writer = json.loads(gzip.open(path, "rt", encoding="utf-8").read())["writer"]
    assert (writer["name"], writer["note"]) == ("Ann Example", "ward 3")


def test_exporting_an_unknown_session_is_an_error(store):
    with pytest.raises(StoreError, match="unknown session"):
        store.export_session(42)


def test_deleting_a_writer_removes_rows_and_backups_but_not_others(store):
    gone, kept = _writer(store), _writer(store)
    gone_sid, kept_sid = _session_with_data(store, gone), _session_with_data(store, kept)
    store.export_session(gone_sid)
    store.export_session(kept_sid)

    assert store.delete_writer(gone) == {"sessions": 1, "samples": 9, "backup_files": 1}
    with sqlite3.connect(store.db_path) as conn:
        for table, expected in (("writers", 1), ("sessions", 1), ("samples", 9), ("strokes", 2), ("prompts", 1)):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == expected, table
    assert not (store.backup_dir / gone).exists()
    assert (store.backup_dir / kept).exists()
    with pytest.raises(StoreError, match="unknown writer"):
        store.delete_writer(gone)


def test_from_config_uses_the_configured_paths(config, tmp_path):
    config["capture"]["db_path"] = str(tmp_path / "x.db")
    config["capture"]["backup_dir"] = str(tmp_path / "bk")
    s = Store.from_config(config)
    assert s.db_path == tmp_path / "x.db" and s.backup_dir == tmp_path / "bk"


# --- the writer's own name ---------------------------------------------------------

def test_name_is_stored_trimmed_and_defaults_to_empty(store):
    named, anonymous = _writer(store, name="  Ann Example  "), _writer(store)
    assert store.get_writer(named)["name"] == "Ann Example"
    assert store.get_writer(anonymous)["name"] == ""


def test_a_database_made_before_names_existed_is_upgraded_in_place(store, tmp_path):
    old_writer = _writer(store, note="kept")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("ALTER TABLE writers DROP COLUMN name")          # the shape of an older database
    upgraded = Store(store.db_path, store.backup_dir)
    assert upgraded.get_writer(old_writer)["name"] == "" and upgraded.get_writer(old_writer)["note"] == "kept"
    new_writer = upgraded.add_writer(consent_project=True, consent_sharing=False, consent_version="v", name="Bo")
    assert upgraded.get_writer(new_writer)["name"] == "Bo"
    Store(store.db_path, store.backup_dir)                            # opening again is harmless


# --- stale hover samples (the 'skips'): Safari delivers a hover sample stamped BEFORE the pen-down just after it ---------

def _stale_sample_stroke():
    """The exact shape seen in the iPad recordings: down at t=18085, then a late hover sample stamped 18077."""
    return [
        _ev("pointermove", 18060.0, b=0),
        _ev("pointerdown", 18085.0, x=128.0, y=126.0),
        _ev("pointermove", 18077.0, x=129.0, y=126.0, b=0),          # stale: earlier than the pen-down, unpressed
        _ev("pointermove", 18106.0, x=128.0, y=126.0),
        _ev("pointermove", 18122.0, x=128.0, y=124.0),
        _ev("pointermove", 18130.0, x=128.0, y=123.0, b=0),          # a second stale one, mid-stroke
        _ev("pointermove", 18139.0, x=128.0, y=122.0),
        _ev("pointerup", 18150.0, x=128.0, y=122.0, b=0),
    ]


def test_a_stale_hover_sample_inside_a_stroke_does_not_cut_the_stroke_short(store):
    sid = store.start_session(_writer(store), style="natural", prompt_set="core")
    store.add_samples(sid, _stale_sample_stroke())
    assert store.derive_strokes(sid) == 1
    (stroke,) = store.read_strokes(sid)
    assert stroke["completed"] is True
    assert [p[3] for p in stroke["points"]] == [18085.0, 18106.0, 18122.0, 18139.0, 18150.0]   # every pressed sample + the up
    with sqlite3.connect(store.db_path) as conn:
        n, done = conn.execute("SELECT n_samples, completed FROM strokes").fetchone()
        raw = conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    assert (n, done) == (5, 1)
    assert raw == 8                                                   # nothing is thrown away: the stale samples stay in the raw record


def test_hover_after_a_lost_pointerup_still_does_not_join_the_next_stroke(store):
    sid = store.start_session(_writer(store), style="natural", prompt_set="core")
    store.add_samples(sid, [_ev("pointerdown", 1.0), _ev("pointermove", 2.0), _ev("pointermove", 3.0, b=0),
                            _ev("pointerdown", 9.0), _ev("pointermove", 10.0), _ev("pointerup", 11.0, b=0)])
    assert store.derive_strokes(sid) == 2
    first, second = store.read_strokes(sid)
    assert first["completed"] is False and len(first["points"]) == 2      # never closed
    assert second["completed"] is True and len(second["points"]) == 3
