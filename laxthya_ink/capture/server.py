"""The capture web server: pages for the iPad, the laptop monitor, and the APIs behind them.

Two audiences, two rules:

* **The iPad (any device on the LAN)** may open `/capture`, register a writer, start or
  resume a session, send finished chunks and the live preview. Each chunk is stored in one
  transaction and a repeated upload is recognised, so the page can retry freely.
* **The laptop only** may open `/monitor` and read stored handwriting, notes and the live
  feed. Those endpoints answer 403 to any other address, because the server listens on the
  LAN and the monitor shows other people's handwriting.

There is no login. Run the server only on a network you trust, and stop it when done.
Uploads are saved under server-chosen names, never names from the client.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from ..config import resolve_path as resolve_dir
from ..exceptions import ConsentRequiredError, ProbeDataError, StoreError
from .live import LiveFeed
from .probe import format_report, summarise
from .prompts import load_prompt_set
from .store import Store

STATIC_DIR = Path(__file__).resolve().parent / "static"
CONSENT_DOC = "docs/CONSENT_FORM.md"
#: addresses treated as "the laptop itself"
LOCAL_HOSTS = ("127.0.0.1", "::1")


def consent_text(path: Path) -> str:
    """The part of the consent document a writer reads: from 'What this is' up to the tick-boxes."""
    text = path.read_text(encoding="utf-8")
    start = text.index("## What this is")
    end = text.index("## Your choices")
    return text[start:end].strip()


def create_app(
    config: dict,
    probe_dir: Path | None = None,
    store: Store | None = None,
    local_hosts: tuple[str, ...] = LOCAL_HOSTS,
) -> FastAPI:
    cap = config["capture"]
    out_dir = probe_dir if probe_dir is not None else resolve_dir(cap["probe_dir"])
    max_bytes = int(cap["max_upload_mb"] * 1024 * 1024)
    store = store if store is not None else Store.from_config(config)
    live = LiveFeed(cap["live_buffer_events"], cap["live_idle_s"])
    prompt_set = load_prompt_set(cap["prompt_set_id"])
    chunk_numbers = {c["id"]: i for i, c in enumerate(prompt_set["chunks"], start=1)}
    chunks_by_id = {c["id"]: c for c in prompt_set["chunks"]}
    total_chunks = len(prompt_set["chunks"])

    app = FastAPI(title="LAXTHYA-Ink capture")

    def local_only(request: Request) -> None:
        host = request.client.host if request.client else ""
        if host not in local_hosts:
            raise HTTPException(403, "this page is only available on the laptop running the server")

    async def json_body(request: Request) -> dict:
        body = await request.body()
        if len(body) > max_bytes:
            raise HTTPException(413, f"upload larger than capture.max_upload_mb ({cap['max_upload_mb']} MB)")
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise HTTPException(400, "body must be a JSON object")
        return data

    def session_or_404(session_id: int) -> dict:
        try:
            return store.get_session(session_id)
        except StoreError as exc:
            raise HTTPException(404, str(exc)) from exc

    # --- pages ---------------------------------------------------------------

    def page(name: str) -> FileResponse:
        return FileResponse(STATIC_DIR / name, headers={"Cache-Control": "no-store"})

    @app.get("/")
    def probe_page() -> FileResponse:
        return page("probe.html")

    @app.get("/capture")
    def capture_page() -> FileResponse:
        return page("capture.html")

    @app.get("/monitor", dependencies=[Depends(local_only)])
    def monitor_page() -> FileResponse:
        return page("monitor.html")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    # --- signal probe --------------------------------------------------------

    @app.post("/api/probe")
    async def upload_probe(request: Request) -> dict:
        body = await request.body()
        if len(body) > max_bytes:
            raise HTTPException(413, f"upload larger than capture.max_upload_mb ({cap['max_upload_mb']} MB)")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"not valid JSON: {exc}") from exc
        try:
            summary = summarise(payload)
        except ProbeDataError as exc:
            raise HTTPException(422, str(exc)) from exc

        report = format_report(summary)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"probe-{stamp}.json").write_bytes(body)
        (out_dir / f"probe-{stamp}.txt").write_text(report, encoding="utf-8")
        return {"saved_as": f"probe-{stamp}", "summary": summary, "report": report}

    # --- capture (the iPad) ---------------------------------------------------

    @app.get("/api/prompts")
    def get_prompts() -> dict:
        return prompt_set

    @app.get("/api/consent")
    def get_consent() -> dict:
        try:
            text = consent_text(resolve_dir(CONSENT_DOC))
        except (OSError, ValueError) as exc:
            raise HTTPException(500, f"cannot read {CONSENT_DOC}: {exc}") from exc
        return {"version": cap["consent_version"], "text": text, "has_placeholders": "[" in text}

    @app.post("/api/writers")
    async def create_writer(request: Request) -> dict:
        data = await json_body(request)
        try:
            writer_id = store.add_writer(
                consent_project=data.get("consent_project") is True,
                consent_sharing=data.get("consent_sharing") is True,
                consent_version=cap["consent_version"],
                note=str(data.get("note", ""))[:500],
            )
        except ConsentRequiredError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"writer_id": writer_id, "consent_version": cap["consent_version"]}

    @app.post("/api/sessions")
    async def start_or_resume_session(request: Request) -> dict:
        data = await json_body(request)
        writer_id = str(data.get("writer_id", ""))
        try:
            store.get_writer(writer_id)
        except StoreError as exc:
            raise HTTPException(404, str(exc)) from exc
        session = store.find_open_session(writer_id, prompt_set["id"])
        resumed = session is not None
        if session is None:
            device = data.get("device") if isinstance(data.get("device"), dict) else {}
            sid = store.start_session(
                writer_id, style=prompt_set["style"], prompt_set=prompt_set["id"], device=device,
                mm_per_px=cap["mm_per_css_px"],
                protector=data["protector"] if isinstance(data.get("protector"), bool) else None,
            )
            session = store.get_session(sid)
        return {
            "session_id": session["id"], "writer_id": writer_id, "resumed": resumed,
            "done_chunks": store.done_chunks(session["id"]), "total_chunks": total_chunks,
        }

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: int) -> dict:
        session = session_or_404(session_id)
        return {
            "session_id": session_id, "writer_id": session["writer_id"],
            "done_chunks": store.done_chunks(session_id), "total_chunks": total_chunks,
            "ended": session["ended_at"] is not None,
        }

    @app.post("/api/sessions/{session_id}/chunks/{chunk_id}")
    async def save_chunk(session_id: int, chunk_id: str, request: Request) -> dict:
        data = await json_body(request)
        session_or_404(session_id)
        if chunk_id not in chunks_by_id:
            raise HTTPException(404, f"unknown chunk {chunk_id!r} for prompt set {prompt_set['id']}")
        events = data.get("events")
        if not isinstance(events, list):
            raise HTTPException(422, "body needs an 'events' list")
        try:
            result = store.save_chunk(session_id, chunk_id, chunk_numbers[chunk_id],
                                      "\n".join(chunks_by_id[chunk_id]["lines"]), events)
        except StoreError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {**result, "done": len(store.done_chunks(session_id)), "total_chunks": total_chunks}

    @app.post("/api/sessions/{session_id}/finish")
    def finish_session(session_id: int) -> dict:
        session_or_404(session_id)
        done = len(store.done_chunks(session_id))
        result = store.finalize_session(session_id)
        return {"strokes": result["strokes"], "complete": done == total_chunks, "done": done, "total_chunks": total_chunks}

    @app.post("/api/live/{session_id}")
    async def post_live(session_id: int, request: Request) -> dict:
        data = await json_body(request)
        session = session_or_404(session_id)
        events = data.get("events")
        if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
            raise HTTPException(422, "body needs an 'events' list of objects")
        canvas = data.get("canvas") if isinstance(data.get("canvas"), dict) else None
        cursor = live.append(
            session_id, session["writer_id"], str(data.get("chunk_id", ""))[:64],
            str(data.get("text", ""))[:500], events, replace=data.get("replace") is True, canvas=canvas,
        )
        return {"cursor": cursor}

    # --- monitor (laptop only) -------------------------------------------------

    monitor = Depends(local_only)

    @app.get("/api/monitor/live", dependencies=[monitor])
    def monitor_live(after: int = 0) -> dict:
        return live.read(after)

    @app.get("/api/monitor/writers", dependencies=[monitor])
    def monitor_writers() -> list[dict]:
        out = []
        for w in store.list_writers():
            sessions = store.list_sessions(w["id"])
            out.append({**w, "sessions": len(sessions), "chunks_done": sum(s["chunks_done"] for s in sessions)})
        return out

    @app.get("/api/monitor/writers/{writer_id}/sessions", dependencies=[monitor])
    def monitor_sessions(writer_id: str) -> dict:
        try:
            writer = store.get_writer(writer_id)
            sessions = store.list_sessions(writer_id)
        except StoreError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"writer": writer, "total_chunks": total_chunks, "sessions": sessions}

    @app.get("/api/monitor/sessions/{session_id}", dependencies=[monitor])
    def monitor_session(session_id: int) -> dict:
        session = session_or_404(session_id)
        writer = store.get_writer(session["writer_id"])
        return {
            "session": session, "note": writer["note"], "total_chunks": total_chunks,
            "chunks": [
                {**c, "section": chunks_by_id.get(c["chunk_id"], {}).get("section", "")}
                for c in store.chunk_info(session_id)
            ],
        }

    @app.get("/api/monitor/sessions/{session_id}/strokes", dependencies=[monitor])
    def monitor_strokes(session_id: int, chunk: int | None = None) -> dict:
        session_or_404(session_id)
        return {"strokes": store.read_strokes(session_id, chunk)}

    return app
