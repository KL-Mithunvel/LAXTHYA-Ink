"""In-memory live feed: what the iPad is writing right now, for the laptop monitor.

Best effort and never saved. The durable record is the chunk upload (`Store.save_chunk`);
this only lets someone watch. The page posts small batches of pen events every few
hundred milliseconds; the monitor polls with the last cursor it saw.

A bounded buffer keeps memory fixed. A monitor that falls further behind than the buffer
is told (`gap: true`) and redraws from what is left.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

#: pen-event fields the monitor needs: kind, position, pressure, buttons, time
_KEYS = ("k", "x", "y", "pressure", "b", "t")


class LiveFeed:
    def __init__(self, max_events: int, idle_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._entries: deque[dict] = deque(maxlen=max_events)
        self._cursor = 0
        self._sessions: dict[int, dict] = {}
        self._idle_s = idle_s
        self._clock = clock
        self._lock = threading.Lock()

    def append(
        self, session_id: int, writer_id: str, chunk_id: str, text: str, events: list[dict],
        *, replace: bool = False, canvas: dict | None = None, writer_name: str = "",
    ) -> int:
        """Add a batch from the page. `replace=True` first clears what the monitor shows for
        this session (the writer undid or cleared strokes). Returns the new cursor."""
        with self._lock:
            now = self._clock()
            meta = self._sessions.setdefault(session_id, {"session_id": session_id, "events": 0})
            meta.update(writer_id=writer_id, writer_name=writer_name, chunk_id=chunk_id, text=text, last_seen=now)
            if canvas:
                meta["canvas"] = canvas
            if replace:
                self._cursor += 1
                self._entries.append({"c": self._cursor, "sid": session_id, "chunk": chunk_id, "reset": True})
            for ev in events:
                self._cursor += 1
                row = {key: ev.get(key) for key in _KEYS}
                self._entries.append({"c": self._cursor, "sid": session_id, "chunk": chunk_id, "e": row})
                meta["events"] += 1
            return self._cursor

    def read(self, after: int = 0, limit: int = 5000) -> dict:
        """Entries newer than `after`, at most `limit`, plus who is live.

        `gap` is true when entries between `after` and the oldest retained one were dropped.
        """
        with self._lock:
            now = self._clock()
            oldest = self._entries[0]["c"] if self._entries else self._cursor + 1
            gap = after + 1 < oldest and after < self._cursor
            fresh = [e for e in self._entries if e["c"] > after][:limit]
            sessions = [
                {**meta, "idle_s": round(now - meta["last_seen"], 1), "live": now - meta["last_seen"] <= self._idle_s}
                for meta in self._sessions.values()
            ]
            for s in sessions:
                s.pop("last_seen", None)
            if fresh:
                cursor = fresh[-1]["c"]
            else:
                cursor = self._cursor if gap else max(after, 0)
            return {
                "cursor": cursor,
                "latest": self._cursor,
                "gap": gap,
                "entries": fresh,
                "sessions": sorted(sessions, key=lambda s: s["idle_s"]),
            }
