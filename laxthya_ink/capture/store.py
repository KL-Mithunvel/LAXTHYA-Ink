"""SQLite store for handwriting capture: writers, sessions and every raw pen sample.

Decisions this implements (docs/PROJECT_PLAN.md -> Storage, Data handling):

* **Raw samples are the record.** Every pen event the page sends is kept with every
  field the device gave, including hover samples between strokes. `strokes` is a
  derived table - `derive_strokes` rebuilds it from the samples at any time.
* **Consent is part of the writer.** Project use is required (no writer exists without
  it); research sharing is a separate optional tick. Both, the consent text version and
  the time are stored.
* **The writer's `name` and the operator's `note` never leave the database by default.**
  Both are private to the laptop: exports and backups omit them unless
  `include_private=True` is passed deliberately, so shared data stays anonymous.
* **Writer IDs (`W001`, ...) are never reused**, so a deleted writer's ID cannot be
  mistaken for a new person's on old paper records.
* **Deleting a writer removes everything**: database rows and their backup files.

Events use the same compact shape the pages upload (`k`, `t`, `x`, `y`, `pt`, `b`, and
the pointer-event fields). Touch events are dropped: the pen is the only writing input.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..config import resolve_path
from ..exceptions import ConsentRequiredError, StoreError

#: the writing styles a session can be labelled with (docs/PROJECT_PLAN.md -> Writing style)
STYLES = ("natural", "cursive", "print", "careful")

_WRITER_ID_RE = re.compile(r"^W\d{3,}$")

#: page field name -> sample column
_FIELD_COLUMNS = {
    "pressure": "pressure",
    "tiltX": "tilt_x",
    "tiltY": "tilt_y",
    "altitudeAngle": "altitude",
    "azimuthAngle": "azimuth",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS writer_seq (n INTEGER PRIMARY KEY AUTOINCREMENT);

CREATE TABLE IF NOT EXISTS writers (
    id TEXT PRIMARY KEY CHECK (id GLOB 'W[0-9][0-9][0-9]*'),
    created_at TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    consent_project INTEGER NOT NULL CHECK (consent_project = 1),
    consent_sharing INTEGER NOT NULL CHECK (consent_sharing IN (0, 1)),
    consent_version TEXT NOT NULL,
    consent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    writer_id TEXT NOT NULL REFERENCES writers(id) ON DELETE CASCADE,
    style TEXT NOT NULL CHECK (style IN ('natural', 'cursive', 'print', 'careful')),
    prompt_set TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    device TEXT NOT NULL DEFAULT '{}',
    mm_per_px REAL,
    protector INTEGER CHECK (protector IN (0, 1)),
    measured_rate_hz REAL
);

CREATE TABLE IF NOT EXISTS prompts (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);

CREATE TABLE IF NOT EXISTS session_chunks (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL,
    prompt_seq INTEGER NOT NULL,
    n_samples INTEGER NOT NULL,
    stored_at TEXT NOT NULL,
    PRIMARY KEY (session_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS strokes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    n_samples INTEGER NOT NULL,
    t_start REAL NOT NULL,
    t_end REAL NOT NULL,
    completed INTEGER NOT NULL CHECK (completed IN (0, 1))
);

CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    stroke_id INTEGER REFERENCES strokes(id) ON DELETE SET NULL,
    prompt_seq INTEGER,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    pointer_type TEXT NOT NULL,
    buttons INTEGER NOT NULL,
    t REAL NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    pressure REAL,
    tilt_x REAL,
    tilt_y REAL,
    altitude REAL,
    azimuth REAL,
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS samples_by_session ON samples (session_id, seq);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _check_writer_id(writer_id: str) -> str:
    """Writer IDs go into file paths, so only the exact `W<digits>` shape is accepted."""
    if not isinstance(writer_id, str) or not _WRITER_ID_RE.match(writer_id):
        raise StoreError(f"invalid writer id {writer_id!r} (expected W001, W002, ...)")
    return writer_id


def _parse_events(events: list[dict]) -> tuple[list[tuple], int]:
    """Turn page events into sample rows (touch dropped). Raises `StoreError` on a malformed event."""
    rows, skipped = [], 0
    for i, ev in enumerate(events):
        try:
            if ev["pt"] == "touch":
                skipped += 1
                continue
            rows.append((ev["k"], ev["pt"], int(ev["b"]), float(ev["t"]), float(ev["x"]), float(ev["y"]),
                         *(ev.get(field) for field in _FIELD_COLUMNS)))
        except (KeyError, TypeError, ValueError) as exc:
            raise StoreError(f"event {i} is malformed: {exc!r}") from exc
    return rows, skipped


def _group_strokes(samples) -> list[dict]:
    """Group ordered samples into strokes: `{"ids": [...], "t0": .., "t1": .., "done": bool}`.

    A stroke runs from a `pointerdown` through the pressed moves to a `pointerup`
    (done) or a `pointercancel` (not done). Samples outside any stroke are hover
    samples and belong to no group.

    An *unpressed* move inside an open stroke is neither part of it nor its end: Safari
    delivers hover samples late, so one stamped earlier than the pen-down can arrive just
    after it. Treating it as a lift would cut the stroke short and drop the rest of it.
    """
    groups: list[dict] = []
    current: dict | None = None
    for s in samples:
        if s["kind"] == "pointerdown":
            current = {"ids": [s["id"]], "t0": s["t"], "t1": s["t"], "done": False}
            groups.append(current)
        elif current is not None and s["kind"] == "pointermove" and s["buttons"] > 0:
            current["ids"].append(s["id"])
            current["t1"] = s["t"]
        elif current is not None and s["kind"] in ("pointerup", "pointercancel"):
            current["ids"].append(s["id"])
            current["t1"] = s["t"]
            current["done"] = s["kind"] == "pointerup"
            current = None
        elif current is not None and s["kind"] == "pointermove" and s["buttons"] == 0:
            continue                          # a stale hover sample that arrived late: ignore it
        else:
            current = None                    # a stray event ends an open stroke
    return groups


class Store:
    """The capture database. Each call opens its own short-lived connection, so it is
    safe to use from a web server's worker threads."""

    def __init__(self, db_path: str | Path, backup_dir: str | Path) -> None:
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(writers)")}
            if "name" not in columns:                   # database made before writers could give a name
                conn.execute("ALTER TABLE writers ADD COLUMN name TEXT NOT NULL DEFAULT ''")

    @classmethod
    def from_config(cls, config: dict) -> "Store":
        cap = config["capture"]
        return cls(resolve_path(cap["db_path"]), resolve_path(cap["backup_dir"]))

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:                      # commit on success, roll back on error
                yield conn
        finally:
            conn.close()

    # --- writers ---------------------------------------------------------

    def add_writer(
        self, *, consent_project: bool, consent_sharing: bool, consent_version: str, name: str = "", note: str = ""
    ) -> str:
        """Register a writer and return their ID. Refuses without project-use consent.

        `name` is what the writer typed about themselves; `note` is the operator's. Both stay private."""
        if consent_project is not True:
            raise ConsentRequiredError("a writer cannot be added without consent to project use")
        with self._conn() as conn:
            number = conn.execute("INSERT INTO writer_seq DEFAULT VALUES").lastrowid
            writer_id = f"W{number:03d}"
            now = _now()
            conn.execute(
                "INSERT INTO writers (id, created_at, name, note, consent_project, consent_sharing,"
                " consent_version, consent_at) VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
                (writer_id, now, name.strip(), note, int(bool(consent_sharing)), consent_version, now),
            )
        return writer_id

    def get_writer(self, writer_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM writers WHERE id = ?", (_check_writer_id(writer_id),)).fetchone()
        if row is None:
            raise StoreError(f"unknown writer {writer_id}")
        return dict(row)

    def set_note(self, writer_id: str, note: str) -> None:
        with self._conn() as conn:
            changed = conn.execute(
                "UPDATE writers SET note = ? WHERE id = ?", (note, _check_writer_id(writer_id))
            ).rowcount
        if not changed:
            raise StoreError(f"unknown writer {writer_id}")

    def list_writers(self) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM writers ORDER BY id")]

    def shareable_writer_ids(self) -> list[str]:
        """Writers who ticked the optional research-sharing consent; nobody else may be shared."""
        with self._conn() as conn:
            return [r["id"] for r in conn.execute(
                "SELECT id FROM writers WHERE consent_sharing = 1 ORDER BY id")]

    # --- sessions and samples ------------------------------------------

    def start_session(
        self, writer_id: str, *, style: str, prompt_set: str, device: dict | None = None,
        mm_per_px: float | None = None, protector: bool | None = None,
        measured_rate_hz: float | None = None,
    ) -> int:
        if style not in STYLES:
            raise StoreError(f"style must be one of {STYLES}, got {style!r}")
        self.get_writer(writer_id)                                   # raises if unknown
        with self._conn() as conn:
            return conn.execute(
                "INSERT INTO sessions (writer_id, style, prompt_set, started_at, device, mm_per_px,"
                " protector, measured_rate_hz) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (writer_id, style, prompt_set, _now(), json.dumps(device or {}), mm_per_px,
                 None if protector is None else int(protector), measured_rate_hz),
            ).lastrowid

    def finish_session(self, session_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (_now(), session_id))

    def add_prompt(self, session_id: int, text: str) -> int:
        """Record a prompt shown to the writer; returns its sequence number (from 1)."""
        with self._conn() as conn:
            return self._add_prompt(conn, session_id, text)

    @staticmethod
    def _add_prompt(conn: sqlite3.Connection, session_id: int, text: str, seq: int | None = None) -> int:
        if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
            raise StoreError(f"unknown session {session_id}")
        if seq is None:
            seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM prompts WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
        conn.execute("INSERT INTO prompts (session_id, seq, text) VALUES (?, ?, ?)", (session_id, seq, text))
        return seq

    def add_samples(self, session_id: int, events: list[dict], prompt_seq: int | None = None) -> dict:
        """Store pen events in order. Touch events are skipped. All-or-nothing: one
        malformed event rejects the whole batch. Returns `{"stored": n, "skipped_touch": m}`."""
        rows, skipped = _parse_events(events)
        with self._conn() as conn:
            self._add_samples(conn, session_id, rows, prompt_seq)
        return {"stored": len(rows), "skipped_touch": skipped}

    @staticmethod
    def _add_samples(conn: sqlite3.Connection, session_id: int, rows: list[tuple], prompt_seq: int | None) -> None:
        start = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM samples WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        try:
            conn.executemany(
                "INSERT INTO samples (session_id, prompt_seq, seq, kind, pointer_type, buttons, t, x, y,"
                " pressure, tilt_x, tilt_y, altitude, azimuth) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(session_id, prompt_seq, start + n, *row) for n, row in enumerate(rows)],
            )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"cannot store samples for session {session_id}: {exc}") from exc

    # --- chunks (the unit the capture page sends) ---------------------------

    def save_chunk(self, session_id: int, chunk_id: str, chunk_number: int, text: str, events: list[dict]) -> dict:
        """Store one finished chunk - its prompt and its pen samples - in a single transaction.

        Safe to repeat: a chunk already stored is not stored twice (`duplicate: True`), so
        the page can retry an upload whose answer it never saw. A chunk with no pen samples
        is refused rather than recorded as done.
        """
        rows, skipped = _parse_events(events)
        if not rows:
            raise StoreError(f"chunk {chunk_id} has no pen samples")
        with self._conn() as conn:
            if conn.execute(
                "SELECT 1 FROM session_chunks WHERE session_id = ? AND chunk_id = ?", (session_id, chunk_id)
            ).fetchone():
                return {"stored": 0, "skipped_touch": skipped, "duplicate": True}
            self._add_prompt(conn, session_id, text, seq=chunk_number)
            self._add_samples(conn, session_id, rows, prompt_seq=chunk_number)
            conn.execute(
                "INSERT INTO session_chunks (session_id, chunk_id, prompt_seq, n_samples, stored_at)"
                " VALUES (?, ?, ?, ?, ?)", (session_id, chunk_id, chunk_number, len(rows), _now()),
            )
        return {"stored": len(rows), "skipped_touch": skipped, "duplicate": False}

    def done_chunks(self, session_id: int) -> list[str]:
        """IDs of the chunks already stored for a session, in the order they were stored."""
        with self._conn() as conn:
            return [r["chunk_id"] for r in conn.execute(
                "SELECT chunk_id FROM session_chunks WHERE session_id = ? ORDER BY rowid", (session_id,))]

    def get_session(self, session_id: int) -> dict:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise StoreError(f"unknown session {session_id}")
        session = dict(row)
        session["device"] = json.loads(session["device"])
        return session

    def find_open_session(self, writer_id: str, prompt_set: str) -> dict | None:
        """The writer's latest unfinished session on this prompt set, so a reload resumes it."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM sessions WHERE writer_id = ? AND prompt_set = ? AND ended_at IS NULL"
                " ORDER BY id DESC LIMIT 1", (_check_writer_id(writer_id), prompt_set),
            ).fetchone()
        return self.get_session(row["id"]) if row else None

    def finalize_session(self, session_id: int) -> dict:
        """Close a session: derive its strokes, write the backup, stamp the end time.
        Returns `{"strokes": n, "backup": "<path>"}`. Repeating it rebuilds both."""
        self.get_session(session_id)                                  # raises if unknown
        strokes = self.derive_strokes(session_id)
        backup = self.export_session(session_id)
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET ended_at = COALESCE(ended_at, ?) WHERE id = ?", (_now(), session_id))
        return {"strokes": strokes, "backup": str(backup)}

    def derive_strokes(self, session_id: int) -> int:
        """Rebuild the `strokes` table and each sample's `stroke_id`; returns the stroke count.

        A stroke runs from a `pointerdown` through the pressed moves to a `pointerup`
        (completed) or a `pointercancel` / an unpressed move (not completed). Samples
        outside any stroke are hover samples and keep `stroke_id` NULL. Safe to repeat.
        """
        with self._conn() as conn:
            conn.execute("UPDATE samples SET stroke_id = NULL WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM strokes WHERE session_id = ?", (session_id,))
            samples = conn.execute(
                "SELECT id, kind, buttons, t FROM samples WHERE session_id = ? ORDER BY seq", (session_id,)
            ).fetchall()

            groups = _group_strokes(samples)

            for seq, g in enumerate(groups, start=1):
                stroke_id = conn.execute(
                    "INSERT INTO strokes (session_id, seq, n_samples, t_start, t_end, completed)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, seq, len(g["ids"]), g["t0"], g["t1"], int(g["done"])),
                ).lastrowid
                conn.executemany("UPDATE samples SET stroke_id = ? WHERE id = ?", [(stroke_id, i) for i in g["ids"]])
        return len(groups)

    # --- reading back (the laptop monitor) -------------------------------

    def list_sessions(self, writer_id: str) -> list[dict]:
        """A writer's sessions, newest first, each with how many chunks and samples it holds."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT s.id, s.style, s.prompt_set, s.started_at, s.ended_at,"
                " (SELECT COUNT(*) FROM session_chunks c WHERE c.session_id = s.id) AS chunks_done,"
                " (SELECT COUNT(*) FROM samples m WHERE m.session_id = s.id) AS samples"
                " FROM sessions s WHERE s.writer_id = ? ORDER BY s.id DESC", (_check_writer_id(writer_id),),
            ).fetchall()
        return [dict(r) for r in rows]

    def chunk_info(self, session_id: int) -> list[dict]:
        """The stored chunks of a session with the text each was asked to write."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT c.chunk_id, c.prompt_seq, c.n_samples, c.stored_at, p.text"
                " FROM session_chunks c LEFT JOIN prompts p ON p.session_id = c.session_id AND p.seq = c.prompt_seq"
                " WHERE c.session_id = ? ORDER BY c.prompt_seq", (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def read_strokes(self, session_id: int, prompt_seq: int | None = None) -> list[dict]:
        """Strokes rebuilt from the raw samples (works on an unfinished session too).

        Each is `{"chunk": prompt_seq, "completed": bool, "points": [[x, y, pressure, t], ...]}`.
        """
        sql = "SELECT id, prompt_seq, kind, buttons, t, x, y, pressure FROM samples WHERE session_id = ?"
        args: list = [session_id]
        if prompt_seq is not None:
            sql += " AND prompt_seq = ?"
            args.append(prompt_seq)
        with self._conn() as conn:
            rows = conn.execute(sql + " ORDER BY seq", args).fetchall()
        by_id = {r["id"]: r for r in rows}
        return [
            {
                "chunk": by_id[g["ids"][0]]["prompt_seq"],
                "completed": g["done"],
                "points": [[r["x"], r["y"], r["pressure"], r["t"]] for r in (by_id[i] for i in g["ids"])],
            }
            for g in _group_strokes(rows)
        ]

    def totals(self) -> dict:
        """Counts across everything collected: writers, sessions, stored chunks and samples."""
        with self._conn() as conn:
            return {
                "writers": conn.execute("SELECT COUNT(*) FROM writers").fetchone()[0],
                "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                "chunks": conn.execute("SELECT COUNT(*) FROM session_chunks").fetchone()[0],
                "samples": conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0],
            }

    def collected_chunk_ids(self, writer_id: str) -> set[str]:
        """Every chunk this writer has written, across all their sessions."""
        with self._conn() as conn:
            return {r["chunk_id"] for r in conn.execute(
                "SELECT DISTINCT c.chunk_id FROM session_chunks c JOIN sessions s ON s.id = c.session_id"
                " WHERE s.writer_id = ?", (_check_writer_id(writer_id),))}

    # --- backup / export / delete ---------------------------------------

    def export_session(self, session_id: int, *, include_private: bool = False) -> Path:
        """Write one session as gzip JSON under `backup_dir/<writer id>/` and return the path.

        The writer's `name` and `note` are left out unless `include_private=True`.
        """
        with self._conn() as conn:
            session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise StoreError(f"unknown session {session_id}")
            writer = dict(conn.execute("SELECT * FROM writers WHERE id = ?", (session["writer_id"],)).fetchone())
            prompts = [dict(r) for r in conn.execute(
                "SELECT seq, text FROM prompts WHERE session_id = ? ORDER BY seq", (session_id,))]
            samples = [dict(r) for r in conn.execute(
                "SELECT seq, prompt_seq, stroke_id, kind, pointer_type, buttons, t, x, y, pressure, tilt_x,"
                " tilt_y, altitude, azimuth FROM samples WHERE session_id = ? ORDER BY seq", (session_id,))]
        if not include_private:
            writer.pop("note")
            writer.pop("name")
        session = dict(session)
        session["device"] = json.loads(session["device"])

        folder = self.backup_dir / _check_writer_id(writer["id"])
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = folder / f"{writer['id']}-s{session_id}-{stamp}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump({"writer": writer, "session": session, "prompts": prompts, "samples": samples}, fh)
        return path

    def delete_writer(self, writer_id: str) -> dict:
        """Remove a writer, their sessions and samples, and their backup files.

        Returns `{"sessions": n, "samples": n, "backup_files": n}`. A trained model or a
        copy already shared with others is outside this store and must be handled separately.
        """
        _check_writer_id(writer_id)
        with self._conn() as conn:
            if conn.execute("SELECT 1 FROM writers WHERE id = ?", (writer_id,)).fetchone() is None:
                raise StoreError(f"unknown writer {writer_id}")
            sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE writer_id = ?", (writer_id,)).fetchone()[0]
            samples = conn.execute(
                "SELECT COUNT(*) FROM samples WHERE session_id IN (SELECT id FROM sessions WHERE writer_id = ?)",
                (writer_id,),
            ).fetchone()[0]
            conn.execute("DELETE FROM writers WHERE id = ?", (writer_id,))     # cascades to everything below

        folder = self.backup_dir / writer_id
        files = sum(1 for _ in folder.rglob("*") if _.is_file()) if folder.exists() else 0
        if folder.exists():
            shutil.rmtree(folder)
        return {"sessions": sessions, "samples": samples, "backup_files": files}
