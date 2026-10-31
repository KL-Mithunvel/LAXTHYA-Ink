# CLAUDE.md

> **IMPORTANT:** Read `CLAUDE-COMMON.md` first — it contains general must-follow instructions (companion files, deployment model, workflow, template structure). This file contains repo-specific instructions. Anything here overrides `CLAUDE-COMMON.md`.
>
> **Also read `PROJ_STARTER.md`** — it contains the owner's personal preferences (interaction rules, coding standards, tech stack choices, commit style).

---

## ⚠ Branch Policy — these branches are never merged

> **Repo-specific — do not copy this section into new projects.**

This repo holds **two independent copies** of the template, kept as separate branches for the owner's personal use:

| Branch | Content |
|--------|---------|
| `main` | The generic template (this branch) — now also hosts the LAXTHYA-Ink project (see below) |
| `machine-vision` | The same template plus the machine-vision baseline — four gates, docs, tools, Roboflow skills |

- **Never merge, rebase, or open a PR between `main` and `machine-vision`, in either direction.** They are meant to diverge. `machine-vision` is a personal copy, not a feature branch.
- **Do not treat `machine-vision` as unmerged work.** Do not suggest merging it, syncing it, or resolving differences between the two branches.
- **To share an improvement, copy the text by hand** into the other branch's files, as its own commit on that branch, and only after asking the owner.
- **Check `git branch --show-current` before editing.** Changes belong to the branch you are on.

---

## Project Overview

**LAXTHYA-Ink** mounts a pen on a Creality Ender-3 V3 SE and makes it write text **in a specific person's own handwriting**. The motivating use is people who have recently lost control of their writing hand: capture their handwriting once, then let the printer write for them in their own hand. A second goal is to **learn a writer's style automatically from their real handwriting samples** (models and methods to be developed, Phase 3+).

- **Author:** kl mithunvel. **License:** see `LICENSE`. **Version:** `VERSION`.
- **Entry point:** `python main.py` (`laxthya_ink/cli.py`).
- **Runtime:** Python ≥ 3.12 (dev machine runs 3.13); Windows 11 host tethered to the printer over USB-C.
- **Sibling project:** the printer link is ported from the Ender-3 V3 SE magnet-embed project (`PycharmProjects/Creality-Ender-3-V3-SE-`, public at `KL-Mithunvel/Creality-Ender-3-V3-SE-`), where it was verified on real hardware (COM3, 115200).
- **Plan and phases:** `docs/PROJECT_PLAN.md`.

### Current status (2026-10-28)

Phase 1 software is done and tested on the dev machine (207 tests): stroke file → layout → G-code → simulated printer → pen-path preview. **Nothing has run on the real printer yet.** The iPad **signal probe** ran twice on the iPad Pro M4 (results in the plan). The **capture app** (consent, writer/session, 64 one-minute chunks sent as written, offline queue, resume) and the **laptop monitor** (live feed + archive) are built and API-tested, but **their pages have not been run in a browser on the iPad yet** (JavaScript syntax-checked only). The control text is generated but its size is an open owner decision (plan -> Control text v1). No learning model exists yet. Design decisions from the grill session are in `docs/PROJECT_PLAN.md`.

---

## Preflight Gates

Cleared in order, with the outcome recorded in `.CLAUDE/CLAUDE-LOG.md`, before the code each gate covers is written.

1. **Understand the writing data.** *Covers: capture and any model code.* Before touching handwriting samples, write down: **inventory** (who, how many sentences/strokes, device, format), **provenance** (when written — before or after the hand-control loss; tremor in the samples will be learned and reproduced), **coverage gaps** (characters, languages, sizes, connected vs printed writing not present), **consent** (whose data, what it may be used for). **Status: OPEN** — no samples exist yet. Consent part: form drafted (`docs/CONSENT_FORM.md`, owner to review and fill the brackets) and enforced in storage; inventory, provenance and coverage-gap records start with the first writer. *Why: precaution, no incident yet — a model inherits every flaw of its samples, and handwriting is personal data.*
2. **Survey the environment.** *Covers: model training code.* Run `python tools/compute_survey.py` and record the output; check the training stack actually uses the GPU. **Status: OPEN for training.** Last survey (2026-09-28, in the log): RTX 1000 Ada, 6 GB VRAM, torch not installed — re-run before training. *Why: from CLAUDE-COMMON — a default CPU-only install silently ignores the GPU.*
3. **Confirm where it runs.** **Status: CLEARED for the printer/planner layer (2026-10-28); OPEN for the model layer.** Recorded: runs on a Windows 11 PC tethered by USB-C to the Ender-3 V3 SE, offline, no cloud needed; the printer has no networking. Artifacts that must leave the machine: stroke JSON and G-code (the printer can also print G-code from microSD with no PC attached — the fallback if the PC cannot stay tethered). Open for models: size vs the 6 GB GPU, and whether a trained writer model must run offline on the person's own machine. *Why: from CLAUDE-COMMON — a platform choice that cannot export its artifacts is a dead end.*
4. **Calibrate the pen before the first real run.** *Covers: any `--printer` run.* Measure and record in `config.local.yaml`: `pen.offset_x/y` (pen tip relative to the nozzle tip), `pen.down_z` (nozzle Z where the tip just touches the paper), then set `pen.down_z_calibrated: true`; confirm the paper area fits the bed. **Status: OPEN.** Enforced in code (Dev Rule 4). *Why: the sibling project's Z-offset workflow was never bench-tested; a wrong pen Z means either no ink or a pen driven into the bed.*

---

## Running the System

```bat
:: one-time
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

:: dev machine (no hardware needed)
python -m pytest                                              :: full suite
python -m py_compile main.py laxthya_ink\*.py laxthya_ink\gcode\*.py laxthya_ink\links\*.py
python main.py tests\data\sample_strokes.json                 :: simulate (default)
python main.py tests\data\sample_strokes.json --preview data\out.png --gcode-out data\out.gcode
python main.py tests\data\sample_strokes.json --dry-run --gcode-out data\out.gcode   :: plan only

:: real printer - only after Gate 4 is cleared
python main.py --printer --ping                               :: connect, M115, print position, exit
python main.py strokes.json --printer                         :: write for real

:: iPad signal probe (capture server on the LAN; Ctrl+C to stop)
python -m laxthya_ink.capture                                 :: iPad: /capture (writing app), /  (probe); laptop only: /monitor
python -m laxthya_ink.capture.prompts                         :: regenerate the control text after changing config or the word list
python -m laxthya_ink.capture.prompts --check                 :: verify the committed text is current and fully covered
```

Activate the venv before any Python command. `ruff`/`flake8` are not configured yet; `py_compile` + `pytest` run before every commit.

---

## Architecture

| Path | Role |
|------|------|
| `main.py` | Thin entry point → `laxthya_ink.cli.main` |
| `config.yaml` | Every tunable. `config.local.yaml` (git-ignored) deep-merges over it |
| `laxthya_ink/config.py` | Load + validate config, merge local override |
| `laxthya_ink/strokes.py` | Stroke data types + JSON loader/validator (the interchange format) |
| `laxthya_ink/planner.py` | **Pure.** layout → simplify → G-code; bounds checks; `safe_stop_commands` |
| `laxthya_ink/gcode/util.py` | G-code text helpers (parse, format, N/checksum) |
| `laxthya_ink/gcode/runner.py` | `GcodeRunner`: stream lines, wait for `ok`, pause/resume/cancel, opt-in resend |
| `laxthya_ink/links/base.py` | `PrinterLink` interface |
| `laxthya_ink/links/printer_serial.py` | Real printer over pyserial |
| `laxthya_ink/links/printer_sim.py` | Fake printer; records the pen path |
| `laxthya_ink/links/_marlin_rx.py` | Parse Marlin reply lines (pure) |
| `laxthya_ink/ports.py` | `port: auto` detection by asking each port `M115` |
| `laxthya_ink/viz.py` | PNG preview of the pen path (matplotlib, lazy, Agg) |
| `laxthya_ink/cli.py` | Argument parsing, wiring, `execute()` with safe-stop on failure |
| `laxthya_ink/capture/probe.py` | **Pure.** Analyse a signal-probe upload: which pen fields vary, hover, sample rate |
| `laxthya_ink/capture/server.py` | FastAPI app: serves the probe page, receives uploads into `data/probe/` |
| `laxthya_ink/capture/static/probe.html` | The iPad page (vanilla JS): records every pointer event with every field |
| `laxthya_ink/capture/store.py` | SQLite store: writers (with consent and note), sessions, prompts, raw pen samples, derived strokes; JSON backup export; delete a writer completely |
| `laxthya_ink/capture/prompts.py` | Builds the control text (English pairs, capitals, digits, punctuation, Greek, Tamil), splits it into ~1-minute chunks, checks coverage; `prompts/core-v1.json` is the committed output, `words_en.txt` its word list |
| `laxthya_ink/capture/live.py` | In-memory live feed (bounded buffer, cursor, gap detection); never saved |
| `laxthya_ink/capture/static/capture.html` | The iPad writing app: consent, one chunk at a time, pen-only, Undo/Clear/Next, IndexedDB queue + retry, resume, live preview |
| `laxthya_ink/capture/static/monitor.html` | Laptop monitor: Live tab and Archive tab |
| `laxthya_ink/capture/__main__.py` | `python -m laxthya_ink.capture` - runs the server, prints the LAN URL |
| `tools/compute_survey.py` | Compute survey for Gate 2 |

```
 capture (later)      writer model (later)
        \                  /
         v                v
   stroke JSON  ──►  strokes.load_strokes
                          │  lines of strokes (writing units, y up, baseline y=0)
                          ▼
                   planner.plan_job      ← config.yaml (paper, pen, motion, park)
                   layout → simplify → nozzle coords → G-code
                          │  Plan(gcode, segments, ...)
                          ▼
                   cli.execute → GcodeRunner ──► PrinterLink
                          │                        ├─ SimPrinter  (dev: records pen_segments)
                          │ on failure/Ctrl-C      └─ SerialPrinter (USB, Marlin, ok-handshake)
                          └─► safe_stop_commands (lift pen, park)
```

- **Threading:** none yet. `GcodeRunner.run()` is blocking and thread-safe for `pause/resume/cancel`, ready for a future UI worker thread.
- **Sim vs real:** `--sim` (default) or `--printer`. Both implement `PrinterLink` and raise the same exceptions.

---

## Key Modules

- **`strokes`** — `Point(x, y, t=None, pressure=None)`, `Stroke(points)`, `Line = list[Stroke]`. `load_strokes(path)` / `parse_lines(data)` → `list[Line]`; raises `StrokeDataError`. Reads one file.
- **`planner`** — `plan_job(lines, config) -> Plan(gcode, segments, stroke_count, point_count, draw_length_mm)`; `layout`, `simplify`, `dedupe`, `pen_heights(config) -> (down, up, safe)`, `safe_stop_commands(config) -> list[str]`. Raises `WritingAreaError`, `OutOfEnvelopeError`. No I/O.
- **`GcodeRunner(link, lines, config, lock=None)`** — `run()`, `pause()`, `resume()`, `cancel()`, `.paused/.cancelled/.finished/.sent_lines`. Raises `AckTimeout`, `PrinterError`, `ResendRequested`. Skips blank/comment-only lines. A cancel does **not** move the pen.
- **`capture.probe.summarise(payload) -> dict`** / **`format_report(summary)`** — raises `ProbeDataError`. **`capture.server.create_app(config, probe_dir=None)`** — `GET /`, `GET /api/health`, `POST /api/probe` (400 bad JSON, 413 too large, 422 bad events); writes `probe-<timestamp>.json/.txt` under `capture.probe_dir`, server-chosen names only.
- **`capture.store.Store(db_path, backup_dir)`** / `Store.from_config(config)` — `add_writer(consent_project, consent_sharing, consent_version, note)` → `W001`… (raises `ConsentRequiredError` without project consent; IDs never reused); `get_writer`, `set_note`, `list_writers`, `shareable_writer_ids`; `start_session(writer_id, style, prompt_set, device, mm_per_px, protector, measured_rate_hz)` (style in `natural/cursive/print/careful`); `add_prompt`; `add_samples(session_id, events, prompt_seq)` (skips touch, all-or-nothing); `derive_strokes(session_id)` (idempotent); `export_session(session_id, include_note=False)` → `backup_dir/<writer>/…json.gz`; `delete_writer(writer_id)` → counts, removes rows and backups. Raises `StoreError`.
- **Capture API** (`capture.server.create_app(config, probe_dir=None, store=None, local_hosts=('127.0.0.1','::1'))`). iPad/LAN: `GET /capture`, `/api/prompts`, `/api/consent`; `POST /api/writers` (422 without project consent), `/api/sessions` (starts or resumes), `GET /api/sessions/{id}`, `POST /api/sessions/{id}/chunks/{chunk_id}` (idempotent; 404 unknown chunk, 422 empty), `/api/sessions/{id}/finish`, `/api/live/{id}`. **Laptop only (403 elsewhere):** `GET /monitor`, `/api/monitor/live?after=`, `/writers`, `/writers/{id}/sessions`, `/sessions/{id}`, `/sessions/{id}/strokes?chunk=`.
- **Store additions:** `save_chunk`, `done_chunks`, `get_session`, `find_open_session`, `finalize_session`, `list_sessions`, `chunk_info`, `read_strokes`.
- **`PrinterLink`** — `connect`, `disconnect`, `send_line`, `wait_ok`, `query_state`, `command`. Raises `PrinterConnectionError`, `AckTimeout`, `PrinterError`, `ResendRequested`.
- **`SimPrinter(pen_contact_z, pen_offset, command_delay)`** — also exposes `.sent`, `.moves`, `.pen_segments` (pen-tip polylines while Z ≤ contact).
- **`cli.execute(link, gcode, config)`** — runs the job; on any exception/interrupt it sends the safe-stop commands, then re-raises. **`cli.require_calibrated(config)`** raises `PenNotCalibratedError`.

---

## Key Conventions

- **Stroke coordinates** are *writing units*: x right, **y up**, baseline y = 0, descenders negative. A tablet reports y down — flip it at capture, never in the planner. Mapping to mm: `x_mm = paper.origin_x + x * scale`; `y_mm = baseline_y + y * scale`, where `scale = writing.scale_mm_per_unit` and line `i` (0-based) has `baseline_y = paper.origin_y + paper.height_mm − (i + 1) * writing.line_spacing_mm`.
- **Pen-tip vs nozzle coordinates:** the paper area, layout and previews are in **pen-tip** bed coordinates. G-code is in **nozzle** coordinates. `pen_tip = nozzle + (pen.offset_x, pen.offset_y)`, so `nozzle = pen_tip − offset`. Worked example: offset (30, −4), pen tip target (40, 208) → nozzle `X10 Y212`.
- **Z heights:** `pen.down_z` = nozzle Z with the tip on the paper; pen-up = `down_z + lift_mm`; `park.safe_z` must clear pen-up. Example: down 5, lift 3 → up 8, safe 20.
- **`pen.down_z_calibrated`** is `false` in the committed `config.yaml` and stays false; only `config.local.yaml` may set it true.
- **Config precedence:** `config.local.yaml` (git-ignored, deep-merged) over `config.yaml`.
- **Sentinels:** none. `None` for `t`/`pressure` means "not captured".
- **Secrets:** this project has none today, so there is no `.env`/`.env.example`. Add both the moment an external service is used (CLAUDE-COMMON → Secrets & Credentials).

---

## Data Files

| Path | Tracked | Notes |
|------|---------|-------|
| `config.yaml` | yes | Defaults and placeholders only |
| `config.local.yaml` | **no** | Real COM port, measured pen offset / Z |
| `tests/data/sample_strokes.json` | yes | Tiny synthetic fixture (not anyone's handwriting) |
| `data/capture.db`, `data/backup/` | **no** | Writers, consent, notes, raw samples; per-writer gzip JSON backups. **Personal data (Dev Rule 7).** The note may hold a name and is never in a backup |
| `laxthya_ink/capture/prompts/core-v1.json` | yes | The generated control text (not personal data). Regenerate with `python -m laxthya_ink.capture.prompts`; a test fails if it is stale |
| `data/probe/` | **no** | Signal-probe uploads (`probe-*.json` raw events, `probe-*.txt` verdict) |
| `data/` | **no** | Generated G-code and previews; **all handwriting samples and trained models go here (Dev Rule 7)** |

---

## Platform Constraints

- Developed on Windows 11; the serial code is OS-neutral (`COMx` vs `/dev/ttyUSB0` comes from config). Not yet run on Linux/Raspberry Pi.
- `pyserial` and `matplotlib` are imported lazily, so the planner, sim and tests do not need them at import time.
- Hardware: Ender-3 V3 SE, Marlin, USB-C, 115200 baud, no networking. Dev-mode equivalent: `SimPrinter`.

---

## Deployment Notes

| | Dev machine | Deployment target |
|--|-------------|-------------------|
| OS | Windows 11 | Same PC, tethered to the printer |
| Python | 3.13 (`.venv`) | same |
| Hardware | none — `SimPrinter` | Ender-3 V3 SE + pen mount |
| Entry point | `python main.py file.json` | `python main.py file.json --printer` |

- **Transfer:** same machine (or `git pull`); no remote device.
- **Pre-deploy checklist (dev machine):** `pytest` green; `python main.py tests\data\sample_strokes.json --preview ...` and inspect the PNG; planned G-code reviewed (`--dry-run --gcode-out`); Gate 4 cleared.
- **Hardware impact of a change:** state which parts touch the serial port, Z heights or the pen mount versus pure logic (CLAUDE-COMMON → Deployment Model).
- **Hardware smoke test, in order:** (1) `python main.py --printer --ping`; (2) a dry-run job with the pen **removed**, watching the moves; (3) the pen in, `pen.down_z` set a few mm too high, then lowered in small steps; (4) the sample strokes on paper.
- **Dev vs target config differences:** `printer.port`, `pen.offset_*`, `pen.down_z`, `pen.down_z_calibrated`, `paper.*` — all in `config.local.yaml`.

---

## Known Technical Debt

- **Pause leaves the pen where it is.** `GcodeRunner.pause()` only stops sending lines; if the pen is down the ink bleeds, and nothing lifts it. Needs a pause-lift (Dev Rule 9).
- **Unverified in this repo on hardware:** `SerialPrinter`/`ports.find_printer` (verified only in the sibling project), `gcode.use_line_numbers` resend, and `G28` followed by the first pen move with a pen mounted.
- **Z-offset calibration workflow does not exist yet** — the sibling project's paper-test dialog was never bench-tested and was not ported (`TODO.md`).
- **`t` and `pressure` are loaded but unused** by the planner.
- **Sim homes to Z = 0**, a stand-in; `SimPrinter` deliberately does not count homing as drawing.
- **`httpx` deprecation warning in tests:** Starlette's `TestClient` warns that using `httpx` is deprecated and suggests `httpx2`. Not changed yet - needs the owner's decision (deprecated-API rule). Affects `tests/test_capture_server.py` only.
- **The capture server listens on the LAN (`capture.host: 0.0.0.0`) with no authentication.** The monitor and archive are laptop-only, but the iPad endpoints are open: anyone on the same network who knows a session number could post samples or create a writer. Acceptable at home while it runs; do not run it on a shared or public network.
- **Capture and monitor pages are untested in a real browser** (only syntax-checked, and the API they call is tested). First iPad run may find layout or interaction bugs.
- **Control text is too long and half-gibberish in English** (67 min, 269 fillers) - open owner decision, see `docs/PROJECT_PLAN.md`.
- **The live preview is not persisted** and a monitor that falls behind the 30,000-event buffer redraws from what is left.
- **A session finished early cannot be resumed** (the page only calls finish at the last chunk; stopping mid-way leaves it open and resumable).
- **No linter configured** (`ruff` recommended; flagged per CLAUDE-COMMON).

---

## Development Rules

1. **Dev machine first, hardware last** (CLAUDE-COMMON → Deployment Model). State which parts of a change touch hardware.
2. **Every driver has a simulated equivalent** producing the same data shape and exceptions. The sim also strips `N<n>…*<checksum>` like real Marlin.
3. **No hardcoded parameters** — ports, feeds, heights, paper size, tolerances live in `config.yaml`.
4. **A real-printer run is refused until `pen.down_z_calibrated` is true** (`cli.require_calibrated`). Never set it true in the committed config.
5. **The planner is pure and checks everything before motion:** paper area, machine volume, Z limits, `pen.min_z`. Nothing is sent to a printer if planning raises.
6. **Never send heater, extrusion or bed-mesh commands** (`M104/M109/M140/M190`, `E` words, `G29`, `M420`). A pen needs none; the stock firmware also drops mesh compensation after every `G28`, which is irrelevant here.
7. **Handwriting samples are personal data:** only under git-ignored `data/`, never committed, never sent to an external service without the owner's explicit approval.
8. **Stroke coordinates are y-up with the baseline at y = 0**; fix orientation at capture.
9. **On failure, interrupt or cancel, lift the pen and park** (`safe_stop_commands`). *(Cancel and pause paths in the runner still owe this — see Technical Debt.)*

---

## Project TODO List

See `TODO.md` — the tracker. Legend: 🔴 Bug / rule violation | 🟡 Incomplete feature | 🟢 Not started | ✅ Done

---

## User Rules

See `CLAUDE-COMMON.md` → Standard User Rules and `PROJ_STARTER.md` for the full rule set.

### Project-Specific Overrides

- **Log file location:** this repo keeps the session log at `.CLAUDE/CLAUDE-LOG.md` (not root `Claude_log.md`), and `TODO.md` at the root. Append a dated entry every session.
- **Project plan** lives in `docs/PROJECT_PLAN.md` (no separate `project/` folder).
