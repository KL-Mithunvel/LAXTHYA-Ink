# Claude Log

## 2026-10-31 — Ink skips: cause found in the recordings and fixed
- Owner: "sometimes when I write it does skips". Checked the four probe recordings: few frame stalls, no pen dropouts or cancels, so not the pen or Safari being slow.
- Found the cause: inside strokes Safari delivers unpressed `pointermove` samples whose timestamps are earlier than the sample before (stale hover samples arriving after the pen-down; 34 in 59 strokes). The capture page drew no segment into/out of them (holes, and strokes starting late); `store._group_strokes` ended the stroke there and dropped the rest (old logic kept 40% of stroke samples, left 34 of 59 strokes unclosed on the real recordings); the monitor live line and the probe archive had the same flaw. Earlier archive view of the probe strokes was truncated for this reason.
- Fix: unpressed moves inside an open stroke are recorded but neither drawn nor treated as a lift, in all four places; `capture.html` now draws smooth midpoint curves (display only) and wraps `setPointerCapture` in try/catch. Added regression tests (stale-sample store/probe tests, one that checks no sample of the real recording is lost) and a stale-sample case in the real-browser test.
- Real-browser testing (Playwright + Edge, scratchpad): first run 35/38, then 40/40; also checked the pages visually. Added a favicon route (browser 404 noise).
- Mistake caught and corrected: my first performance measurement ("no stalls") was invalid because synthetic pen events made `setPointerCapture` throw, so nothing was drawn; after fixing and making the harness prove it draws (188,803 ink pixels), the result still holds in Edge (about 0.03 ms per sample, no long tasks, no frame gaps). It is not a measurement of Safari on the iPad.
- 254 tests pass. Needs the owner to try the iPad again.

## 2026-10-31 — Name entered on the tablet; laptop shows who is writing
- Owner asked for acceptance of the consent and the writer's name to be entered on the tablet, and for the laptop to show live writing and what each user wrote before (the monitor's Live and Archive views already existed; names now appear in them).
- `writers.name` column (migration `ALTER TABLE` when an older database lacks it; verified on the real, empty `data/capture.db`); `add_writer(name=)`; `POST /api/writers` requires a non-blank name up to 100 characters; `export_session(include_private=)` replaces `include_note` and drops both name and note by default; `LiveFeed` carries `writer_name`; monitor endpoints return names.
- Privacy decision: no endpoint reachable from the tablet returns a name (writer IDs are short and guessable on the LAN), so a resumed session shows only the ID; names appear only on the laptop-only monitor. Tested.
- Consent text now says the writer types their name, kept only on the laptop and never in backups or shared files; version bumped to 2026-10-31-v2 (config).
- `capture.html`: start screen is consent text, 'Your choice' ticks, 'Your name' (required; Start stays disabled until the required tick and a name), optional 'For the operator' (note, protector); welcome card with the writer ID; 'name · ID' shown in the writing bar. `monitor.html`: names in the live list, archive list and overview.
- 249 tests pass; node syntax check and element-id check pass for all three pages.

## 2026-10-31 — Option B control text and the monitor's view of old data
- Committed the capture app as f9629e7.
- Owner chose option B for the English text. Downloaded the first20hours/google-10000-english (no-swears) list into a fresh folder, read its licence (research use allowed, redistribution unclear), so it is kept out of git under `data/wordlists/` with a pinned-checksum `tools/fetch_wordlist.py`; only the generated text is committed (it stores its natural pairs, so the coverage check needs no list).
- Rewrote `capture/prompts.py`: pool = most frequent words, natural pairs = pairs in at least N words, greedy pick by gain per letter, fillers removed. First try (whole 10k list) picked acronyms (usb gtk wto pdt bmw xhtml); fixed by restricting to the top 3,000, 4+ letters, a vowel, at most 3 consonants in a row (config). Result `core-v2`: 52 chunks, 229 real words, 317 natural pairs x2, 359 rare pairs deferred, about 52.6 min (was 64 chunks, 67.5 min). Set id bumped to core-v2; core-v1.json removed (no data had been collected against it).
- Owner also asked to view old collected data in the monitor. Added `/api/monitor/overview` (totals; one writer's progress per section), `/api/monitor/probes` and `/probes/{name}` (saved probe uploads: verdict, drawn strokes, hover trails; names validated), `Store.totals`/`collected_chunk_ids`, `probe.extract_paths`, and the page: Signal probes list, overview cards and per-section bars, probe drawing. A test caught a bug in my new `extract_paths` (a pressed move with no stroke was drawn as hover); fixed. All laptop-only.
- Reviewed two further probe uploads (`probe-20261030-140902`/`140918`, the same 21 s session sent twice): roll still constant 0. Four uploads now; roll and squeeze treated as unavailable in Safari.
- 240 tests pass. Not verified: the pages in a real browser or on the iPad; writing speed.
- Dev note: two helper scripts failed their own safety asserts mid-way and partly applied (config edit; filter patch); both were detected, the partial state inspected and the remaining edits applied.

## 2026-10-30 — Capture storage and consent form
- Committed the probe work as 05a202b.
- Owner decisions: consent scope = project use + anonymised research sharing; consent recorded by tick-box in the app; each writer has a free-text note. Implemented sharing as a separate optional tick and kept the note out of all exports/backups by default (a name in it would break anonymity); both choices flagged to the owner and recorded in the plan.
- Built `laxthya_ink/capture/store.py` (SQLite): writers with consent fields (DB refuses a writer without project consent), never-reused IDs, sessions (style natural/cursive/print/careful), prompts, raw samples (touch dropped, all-or-nothing batches), derived strokes (idempotent, hover samples unassigned), gzip JSON backup per session, complete writer deletion (rows + backup files). 24 tests; total 162 pass.
- Config: `capture.db_path`, `backup_dir`, `consent_version`; moved the path helper into `config.resolve_path`.
- Drafted `docs/CONSENT_FORM.md` (version 2026-10-30-v1). It contains commitments written on the owner's behalf (no use for anything the writer must sign, no handing the model to others, telling writers who received shared data) - owner must review/edit and fill the [brackets] before real use.
- Not done at that point: capture app pages and endpoints; prompt text design. (Done later the same day, below.)
- Owner asked for the capture GUI with the control text split into small chunks sent to the laptop, plus a laptop view of progress (old data and live). Decisions: chunk ~1 minute; English text designed with a coverage check.
- Built: `capture/prompts.py` (+ `words_en.txt`, committed `prompts/core-v1.json`), `capture/live.py`, store chunk/read methods (`save_chunk` idempotent and atomic, `read_strokes`, `list_sessions`, ...), server endpoints, `static/capture.html` (iPad app: consent with two ticks, pen-only, undo/clear/next, IndexedDB queue with retry, resume, breaks, live preview) and `static/monitor.html` (Live + Archive). Config: `prompts:` section, `capture.prompt_set_id`, `mm_per_css_px`, live settings. 207 tests pass; JS syntax-checked with node; API walked end to end against the real server with a throwaway DB, including 403 for the monitor from the LAN address.
- Security decision: the monitor/archive endpoints are laptop-only (127.0.0.1 / ::1) because the server listens on the LAN and they expose handwriting and notes.
- Finding: the generated English text is 269 filler strings (about half the letters are gibberish) and the whole core is an estimated 67 minutes; real words cover only 299 of 676 pairs twice. Recorded with options in the plan; owner decision pending. Time estimate rests on an assumed 90 units/min.
- Not verified: the pages in a real browser / on the iPad; writing speed; mm per CSS pixel.

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
