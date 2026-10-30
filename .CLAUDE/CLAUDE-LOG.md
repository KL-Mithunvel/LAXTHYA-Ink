# Claude Log

## 2026-10-30 — First probe result from the iPad Pro M4
- Ran the capture server; owner uploaded one probe (`data/probe/probe-20261030-123914.json`). Results recorded in `docs/PROJECT_PLAN.md` -> Probe result 1: pressure, tilt, altitude, azimuth and hover presence all work; roll and tangential pressure constant 0; no hover height; ~106 samples/s with frame-quantised timestamps; `getCoalescedEvents` absent in Safari 26.5.
- Fixed two bugs in my own code: (1) `probe.py` reported 59 Hz because it only used gaps between distinct timestamps - now counts every in-stroke sample (106 Hz) and flags timestamp quantisation; two new tests (138 pass). (2) `probe.html` drew ink offset from the pen (viewport coordinates on a canvas below the header) - now subtracts the canvas rect, which is also saved in the upload meta. Recorded coordinates were never affected.
- Restarted the capture server so the corrected analysis is live; the page fix is served from disk.
- Second probe (`probe-20261030-125553`): same picture, ~115 samples/s; roll still constant 0 (treated as unavailable in Safari); squeeze invisible (buttons only 0/1); touch-only cancels (palm) so the capture app must ignore touch. Recorded as Probe result 2 in the plan.
- DECIDED (owner): build the real capture app on the web route.
- (resolved) Was open: is ~106 Hz without roll/hover-height enough (stay web), or go native for 240 Hz, roll, squeeze and hover height? Also re-test roll once.

## 2026-10-29 — Grill session on the capture and learning design
- Owner asked to be grilled one question at a time (`.CLAUDE/skill/grill-me`). Plan: collect a dataset by having people write a default prompt text, learn from it, then build the generator; the dataset must cover letter combinations/joins (cursive).
- Decisions (recorded in the Decisions table of `docs/PROJECT_PLAN.md`): online strokes only; iPad + stylus (paper-texture protector optional); capture app is a Safari web app with a Python backend. Record answers as we go.
- Plan impact: scan/photo route dropped; Phase 3 capture will be a web app.
- More decisions (all in the Decisions table): tiered coverage (core first); script = English + digits + full Greek alphabet + math symbols, then Tamil added; writers collected one at a time, output conditioned to one chosen writer only; first writers are healthy; old-paper recovery deferred to a later research phase.
- Later decisions (Decisions table): hybrid model, library first; styles natural + cursive + print with full coverage for natural only; local-only data with written consent; success judged by automatic checks and a blind human test; A5 and smaller pages; capture stays a Safari web app with a signals test page first; device is an iPad Pro M4 (Pencil Pro).
- Storage confirmed: every raw pen sample in SQLite plus a compressed JSON backup per session; strokes derived.
- Also decided: spring-loaded fineliner holder (printable); layout scope is plain text, then super/subscripts, then full equations, all in v1 in that order.
- Committed Phase 1 + plan as 64e78ba (main, not pushed).
- Built the signal probe: `laxthya_ink/capture/` (`probe.py` analysis, `server.py` FastAPI, `__main__.py`, `static/probe.html`), `capture:` config section, `ProbeDataError`, FastAPI/uvicorn/httpx requirements; 136 tests pass; smoke-tested the real server on localhost (GET /, health, upload, report). The smoke-test files were deleted from `data/probe/`.
- Finding while building: Pointer Events have no hover-distance field, so hover height (z) cannot come from Safari at all (only hover presence). Corrected in the plan. Owner wanted z; this needs a native app.
- Open: `httpx` deprecation warning from Starlette's TestClient (suggests httpx2) - not changed, needs owner's decision.
- Consequence flagged: the 20-30 min core estimate no longer holds with full Greek and Tamil; re-estimate after prompt design, likely several short sittings.

## 2026-10-28 — Start LAXTHYA-Ink: plotter pipeline on the dev machine
- Read the sibling Ender-3 V3 SE magnet-embed project (local copy of `KL-Mithunvel/Creality-Ender-3-V3-SE-`) for how printer control works: serial at 115200, DTR low, `M115` handshake, one line then wait for `ok`, `busy`/`wait`/`resend`/`error` handling, sim twin, runner, port auto-detect.
- Filled `.CLAUDE/CLAUDE.md` for this project (overview, four preflight gates with status, architecture, modules, conventions, deployment, debt, rules 1-9). Kept the Branch Policy section unchanged apart from noting `main` now also hosts this project.
- Gate outcomes: Gate 3 (where it runs) cleared for the printer/planner layer — Windows 11 PC tethered by USB-C, offline; model layer still open. Gates 1, 2 and 4 are OPEN (no samples yet; training survey not re-run; pen uncalibrated).
- Added `docs/PROJECT_PLAN.md` (five phases, decisions, open questions, printer-control reference).
- Built Phase 1 in `laxthya_ink/`: config + validation, stroke format/loader, pure planner, runner, `PrinterLink` + serial + sim (sim records the pen path), ports, preview, CLI; `config.yaml`; `requirements*.txt`; `pyproject.toml`; 111 tests (all pass); `.venv` created. Ran the CLI on `tests/data/sample_strokes.json` and inspected the preview PNG: L, box, dot and diagonal land where planned.
- Decisions: Z-only pen lift; no bed mesh / heater / extrusion commands; `pen.down_z_calibrated` stays false in the committed config and gates `--printer`; safe-stop (lift + park) on failure or interrupt; stroke coordinates y-up, baseline 0.
- Not done: nothing run on real hardware; pause does not lift the pen (debt); no `.env.example` (no secrets yet, noted in CLAUDE.md); nothing committed yet.
- Housekeeping: `.gitignore` now ignores `config.local.yaml`. `.CLAUDE/CLAUDE_INDEX.md` lists the new files.

## 2026-09-28 — Record the never-merge branch policy
- Owner clarified that `main` and `machine-vision` are separate personal copies and are never to be merged. Added a "Branch Policy" section (marked repo-specific, not to be copied into new projects) at the top of `.CLAUDE/CLAUDE.md` on `main`, and matching notices on `machine-vision`.
- Cancelled the TODO item to merge `main` into `machine-vision`; recorded the reason there. The earlier merge of `origin/main` into `main` is unaffected — that was the same branch on the remote.
- Improvements are shared between the branches by copying text by hand as a separate commit on the target branch, after asking the owner.

## 2026-09-28 — Move claude_MV to a branch; bring generic rules back to main
- Created and pushed branch `machine-vision` (924a9c1) with the full contents of KL-Mithunvel/claude_MV. `main` stays the generic template.
- Reviewed the vision material for generic value and applied the selected items to `main`:
  - `.CLAUDE/CLAUDE-COMMON.md`: added Documentation Discipline (non-code docs go in `docs/`, not `project/` — decided to match the new Standard Project Layout), Secrets & Credentials, and Preflight Gates with three generic example gates (understand the existing state, survey the environment, confirm where it will run). Added a "no hardcoded parameters" rule for all projects, a Preflight Gates slot in the template skeleton, and a Standard Project Layout section.
  - `.CLAUDE/CLAUDE.md`: added a `## Preflight Gates` placeholder section.
  - New `.gitignore` (generic subset — vision image/weights blocks left on the branch) and `tools/compute_survey.py` (docstring generalised; ran it on this machine, works on Windows: RTX 1000 Ada, 6 GB VRAM, torch not installed).
  - `.CLAUDE/CLAUDE_INDEX.md` now committed on `main` with a Tooling and Defaults section.
- Edited `CLAUDE-COMMON.md` at the owner's request, despite the `update-docs` skill's note that it is normally not edited.
- Not applied (recorded in `TODO.md`): dependency-pin rule, failed-experiments rule, provisional-values rule, honest-reporting rule, rule → evidence style, log-file naming housekeeping, and the personal-preference items.
- Left for later: merging `main` into `machine-vision` will conflict in `CLAUDE-COMMON.md` and `CLAUDE_INDEX.md`.
- Decision: `compute_survey.py` was run with system Python because this repo has no venv; it is standard library only and read-only.
- Push of `main` was rejected: `origin/main` already had PR #3 (Documentation Discipline + "ok KLM" opener in `PROJ_STARTER.md`, merged 2026-06-18). Merged it into local `main` (no force-push). Git merged cleanly but left two Documentation Discipline sections in `CLAUDE-COMMON.md`; removed the remote's copy and kept the `docs/` version (owner's decision). The "ok KLM" opener is now active on `main`.
