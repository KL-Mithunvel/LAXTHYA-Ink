"""The capture web server: serves the iPad pages and receives what they record.

For now it has one job - the signal probe. Uploads are saved under
`capture.probe_dir` (git-ignored `data/`) with server-chosen file names, never
names from the client. The server listens on the LAN so an iPad can reach it:
run it only on a network you trust, and stop it when you are done.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from ..exceptions import ProbeDataError
from .probe import format_report, summarise

STATIC_DIR = Path(__file__).resolve().parent / "static"
REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_dir(path: str) -> Path:
    """A configured directory: absolute as given, otherwise relative to the repo root."""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def create_app(config: dict, probe_dir: Path | None = None) -> FastAPI:
    cap = config["capture"]
    out_dir = probe_dir if probe_dir is not None else resolve_dir(cap["probe_dir"])
    max_bytes = int(cap["max_upload_mb"] * 1024 * 1024)
    app = FastAPI(title="LAXTHYA-Ink capture")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "probe.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

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

    return app
