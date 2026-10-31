from laxthya_ink.capture.live import LiveFeed


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _ev(i):
    return {"k": "pointermove", "x": float(i), "y": 0.0, "pressure": 0.2, "b": 1, "t": float(i), "pt": "pen", "tiltX": 3}


def _feed(max_events=100, idle_s=10.0):
    clock = Clock()
    return LiveFeed(max_events, idle_s, clock), clock


def test_cursor_advances_and_readers_only_get_new_entries():
    feed, _ = _feed()
    feed.append(1, "W001", "c1", "text", [_ev(0), _ev(1)])
    first = feed.read(0)
    assert [e["c"] for e in first["entries"]] == [1, 2] and first["cursor"] == 2
    feed.append(1, "W001", "c1", "text", [_ev(2)])
    second = feed.read(first["cursor"])
    assert [e["c"] for e in second["entries"]] == [3]
    assert feed.read(second["cursor"])["entries"] == []                  # nothing new


def test_only_monitor_fields_are_kept():
    feed, _ = _feed()
    feed.append(1, "W001", "c1", "t", [_ev(0)])
    assert set(feed.read(0)["entries"][0]["e"]) == {"k", "x", "y", "pressure", "b", "t"}


def test_replace_inserts_a_reset_marker_first():
    feed, _ = _feed()
    feed.append(1, "W001", "c1", "t", [_ev(0)])
    feed.append(1, "W001", "c1", "t", [_ev(1)], replace=True)
    kinds = [("reset" in e) for e in feed.read(0)["entries"]]
    assert kinds == [False, True, False]


def test_sessions_report_liveness_and_idle_time():
    feed, clock = _feed(idle_s=10)
    feed.append(7, "W002", "c9", "hello", [_ev(0)], canvas={"w": 800, "h": 500})
    clock.now = 4
    s = feed.read(0)["sessions"][0]
    assert (s["session_id"], s["writer_id"], s["chunk_id"], s["text"]) == (7, "W002", "c9", "hello")
    assert s["live"] is True and s["idle_s"] == 4 and s["canvas"] == {"w": 800, "h": 500} and s["events"] == 1
    clock.now = 30
    assert feed.read(0)["sessions"][0]["live"] is False


def test_the_buffer_is_bounded_and_a_slow_reader_is_told_about_the_gap():
    feed, _ = _feed(max_events=10)
    feed.append(1, "W001", "c1", "t", [_ev(i) for i in range(25)])
    r = feed.read(0)
    assert r["gap"] is True and len(r["entries"]) == 10 and r["entries"][0]["c"] == 16
    assert feed.read(r["cursor"])["gap"] is False                        # caught up


def test_a_reader_that_is_current_sees_no_gap_even_when_the_buffer_is_full():
    feed, _ = _feed(max_events=10)
    feed.append(1, "W001", "c1", "t", [_ev(i) for i in range(10)])
    cur = feed.read(0)["cursor"]
    assert feed.read(cur)["gap"] is False


def test_limit_pages_through_a_large_backlog():
    feed, _ = _feed(max_events=100)
    feed.append(1, "W001", "c1", "t", [_ev(i) for i in range(30)])
    a = feed.read(0, limit=20)
    b = feed.read(a["cursor"], limit=20)
    assert len(a["entries"]) == 20 and len(b["entries"]) == 10 and b["cursor"] == 30
