# LAXTHYA-Ink — Project Plan

Pen on a Creality Ender-3 V3 SE, writing in a specific person's own handwriting. Written 2026-10-28. Each phase lists goal, steps, files and success criteria (CLAUDE-COMMON → Documentation Discipline).

## Decisions recorded

| Decision | Choice | Why |
|----------|--------|-----|
| Pen lift | Z axis only, no servo | Simplest on a stock Ender; a spring-loaded holder absorbs bed unevenness |
| Printer control | Ported from the sibling magnet-embed project (serial ok-handshake, sim twin, runner) | Verified on real hardware there |
| Stroke format | JSON, y-up, baseline y=0, optional `t` and `pressure` per point | One format for capture, model and planner |
| Style learning | **v1 glyph/template library, v2 neural** (RNN-MDN or diffusion, fine-tuned per person) | Library needs little data; a person with limited ability can only give a short session |
| Bed levelling | None — a single calibrated pen-down Z | Stock firmware turns mesh compensation off after every `G28` |
| Stack | Python, YAML config, pytest, SQLite if a database is needed | `PROJ_STARTER.md` |
| Capture mode (2026-10-29) | **Online strokes only** (ordered points + time + pressure); no scan/photo route | Cursive joins are movements; images lose stroke order and direction |
| Capture route (2026-10-30) | **Web app, confirmed after two probes.** Accepts: ~115 samples/s with frame-quantised time (interpolate within a frame), pressure, tilt, altitude, azimuth, hover presence (x, y only). Gives up: 240 Hz, barrel roll, squeeze, hover height. Capture app must ignore `pointerType: touch`. Native can be added later without losing collected data | Probe results 1 and 2 |
| Capture device (2026-10-29) | iPad + stylus; a paper-texture screen protector may be added for feel | Owner already has an iPad |
| Coverage (2026-10-29) | **Tiered.** Core session first (about 20-30 min): every lowercase letter pair at least 2x, capitals, digits, basic punctuation. Optional extended session later: common triples and frequent words. Literal "all permutations" is infeasible (676 pairs, 17,576 triples); the model generalises to unseen combinations | A short core must be enough for a person with limited hand control; time per writer is the constraint |
| Script (2026-10-29) | First version: **English (Latin) + digits + a basic set of engineering Greek letters and symbols** (e.g. Ω, π). Exact symbol set still to be decided. No other scripts for now | Prove the whole chain on one script first |
| Symbol set (2026-10-29) | **Full Greek alphabet** (24 letters, upper and lower case) plus the math/engineering symbols, in the core session. Supersedes the "minimal set" recommendation. **Consequence:** the 20-30 min core estimate no longer holds; re-estimate once the prompt text is designed, and consider splitting the core into two short sittings | Owner's call: the full set |
| Writers (2026-10-29) | Core sessions are collected **one writer at a time**, over time (no fixed headcount). At output time the owner **picks one specific writer and the printer writes in that person's hand only**. A combined (multi-writer) model is acceptable internally, but generation must be conditioned so the result is that one person's style and nothing blended | Output is personal: it must be recognisably that one person |
| First writers (2026-10-29) | **Healthy writers, capture while able.** Impaired-hand capture is not a first target | Clean data proves the chain first |
| Old paper writing (2026-10-29) | **Later research phase, not now.** Owner hopes a big model trained on all collected handwriting will predict a person's strokes from normal old paper writing. Treated as a hypothesis: it can supply stroke-order priors, but it will not recover that person's own timing or exact joins. Reopens the scan route (offline-to-online recovery) at that time | Do not let it shape v1 |
| Tamil (2026-10-29) | **Tamil added to scope** alongside English, digits and Greek. Tamil coverage unit and prompt design still to be decided (247 letters: 12 vowels, 18 consonants, 216 combined, 1 aytham). Supersedes "no other scripts for now" | Owner's call |
| Tamil timing (2026-10-29) | **Collect English+Greek and Tamil from every writer now, as separate sittings; get printing working on English first.** Avoids calling writers back | Recruiting each writer is the expensive step |
| Tamil coverage (2026-10-29) | **All 247 letters, a few repeats each** (12 vowels, 18 consonants, 216 consonant+vowel, aytham). Common words and sequences go in an extended sitting | Every letter and sign attachment is seen at least a few times |
| Model approach (2026-10-29) | **Hybrid, library first.** Glyph/join library gives a printable result after the first writer's core session; a neural stroke generator is trained in parallel from a pretrained base and adapted per writer. Neural from scratch is not viable with few writers. Public-dataset availability for Greek symbols and Tamil is **unverified** | Early result plus a higher ceiling later |
| Writing style (2026-10-29) | **Three labelled sets per writer:** (1) **natural**, as they normally write, normal speed (primary); (2) **cursive**, requested; (3) **separated/print**, requested. Every stroke file carries its style label. For a writer who does not write cursive, the cursive set is optional and flagged as low-fidelity. A few slow-and-careful lines may also be kept as a separate label | More join and shape data, without losing the person's real hand |
| Style tiers (2026-10-29) | **Full coverage for natural only** (English pairs, Greek, digits, Tamil). Cursive and print are **shorter, English-only** sets (every letter pair once plus a few words and digits) in the extended tier | Keeps the core as short as possible |
| Data handling (2026-10-29) | **Local only, written consent.** Backend on the owner's laptop, iPad on the same Wi-Fi; files under git-ignored `data/<writer-id>/`, a writer ID instead of a name in any file; a one-page consent form (what is collected, that a model can imitate their hand, who can use it, deletion of data and model on request) confirmed before the first stroke. Encrypted backup is a later addition. Clears the consent part of Gate 1 once the form exists | Handwriting is personal data and a model of it can imitate the person (Dev Rule 7) |
| Evaluation (2026-10-29) | **Both.** Automatic checks for daily tuning (handwriting-recogniser legibility, writer-identification model, stroke-shape distance to held-out real samples); a **blind human test per writer** (people who know them) as the final judgement. Known limit: the pen line width is near constant, so stroke thickness will not match ink on paper unless the pen mount has spring-loaded pressure response | Needs both a finish line and a fast feedback loop |
| Page size (2026-10-29) | **A5 and smaller for v1** (bed is 220 x 220 mm; A4 does not fit in one pass). A4 would need a two-pass paper jig: a later phase. Writing size is set by `writing.scale_mm_per_unit` | Hardware limit of the bed |
| Capture signals (2026-10-29) | **Stay with the Safari web app; build a test page first** that logs everything the iPad and Pencil report (position, time, pressure, tilt, hover height, roll, sample rate). Go native only if hover or roll are missing and the owner still wants them. **Correction (2026-10-29, while building the probe):** Pointer Events have no distance-above-screen field at all, so hover **height (z)** cannot come from Safari under any circumstances; only hover *presence* (pen moves with nothing pressed) can. Hover height would need a native app (believed available there; unverified). The probe tests the rest. Extra signals help the style model; the printer uses only x, y and pen up/down | Verify before building more |
| Capture device (2026-10-29) | **iPad Pro M4** (works with Apple Pencil Pro; hover support expected, to be verified) | Owner's device |
| Storage (2026-10-29) | **Every raw pen sample in SQLite, plus a compressed JSON backup per session.** All fields the device gives (x, y, time, pressure, tilt, and hover height/roll if available), including hover samples between strokes. Strokes are a derived table (which samples belong to which pen-down), recomputable. Per-session context: prompt, style set, iPad and Pencil model, mm per pixel, protector fitted, measured sample rate | Nothing is lost if the cutting rule or a needed signal changes later |
| Pen mount (2026-10-29) | **Spring-loaded holder with a fineliner**, designed as a printable part for the Ender. Tilt is captured for the style model but the printer holds the pen vertical, so tilt cannot be reproduced. Spring rate and `pen.down_z` to be tuned at Gate 4 | Forgiving of bed unevenness; consistent light contact |
| Layout (2026-10-29) | **All three are in v1 scope**, delivered in order, each working before the next starts: (a) plain single-baseline text with mixed English/digits/Greek/Tamil/symbols; (b) superscripts and subscripts (scale + baseline shift, small extra prompt set); (c) full equations (fractions, roots, stacked layout; own layout engine and capture prompts for expressions) | Owner's call: all three. Order follows dependency |
| Capture software (2026-10-29) | Web app in Safari (Pointer Events + Python backend), not native Swift | No Mac needed, shareable by link, fits thin-frontend preference. Verify sample rate/timestamps on the real iPad before building more |

## Open questions for the owner

1. ~~**Capture source**~~ — decided 2026-10-29: iPad + stylus, online strokes only (see Decisions). The "recover from old paper writing" route is therefore out of scope unless the owner reopens it.
2. **Pen mount:** rigid clip, spring-loaded holder, or nozzle replaced? Which pen?
3. **Two data situations to support separately:** *capture while able* (best — clean live samples) vs *recover from old writing* (scans of letters, signatures).

## Phase 1 — Pen plotter pipeline on the dev machine  ✅ done 2026-10-28

- **Goal:** strokes → G-code → simulated printer → pen-path preview, all tested without hardware.
- **Steps:** port link layer; define stroke format; write planner; simulated pen tracking; CLI.
- **Files:** everything under `laxthya_ink/`, `config.yaml`, `main.py`, `tests/`.
- **Success:** `pytest` green (111 tests); `python main.py tests\data\sample_strokes.json --preview …` shows the strokes in place; the simulated pen path equals the planned path to 3 decimals.

## Phase 2 — First real writing

- **Goal:** the printer draws clean pen-up/pen-down text from a stroke file, on paper.
- **Steps:** clear Gate 4 (measure pen offset and `pen.down_z`); `--printer --ping`; dry run with the pen removed; step the pen down in small increments; run the sample strokes; tune `draw_feed`, `simplify_tolerance_mm`, `line_spacing_mm`. Add pause-lift (Technical Debt). Consider a guided Z-calibration helper (the sibling's paper-test dialog is the model).
- **Files:** `config.local.yaml` (not tracked), `laxthya_ink/gcode/runner.py`, `laxthya_ink/cli.py`, a calibration tool in `tools/`.
- **Success:** the sample strokes drawn on paper match the preview within the pen-width; the printer ends with the pen up and parked; failures mid-job lift the pen.

## Phase 3 — Capture handwriting

- **Goal:** record a person's handwriting as stroke JSON.
- **Steps:** clear Gate 1 first. Prompted-sentence capture tool (tablet/stylus → stroke JSON, y flipped to up); a store under `data/<writer>/`; a scan-to-strokes route if the owner needs it; consent and provenance notes per writer.
- **Files:** `laxthya_ink/capture/` (new), `data/` (not tracked), docs on the data inventory.
- **Success:** a writer completes a prompted session; the strokes replay faithfully through the planner and the simulator.

## Phase 4 — Learn the writer's style (v1: glyph library)

- **Goal:** type text, get it written in the person's hand from a short sample.
- **Steps:** segment samples into letters/connections; build a per-writer glyph library; stitch with baseline, slant, spacing and natural variation; evaluate by eye and by metrics (e.g. stroke-shape distance, legibility by a handwriting recogniser).
- **Files:** `laxthya_ink/writer/` (new), tests with synthetic data.
- **Success:** a sentence typed as text comes out in the writer's style and is legible; two renderings of one word are not identical.

## Phase 5 — Neural writer model (v2)

- **Goal:** more natural, fully automatic style learning.
- **Steps:** clear Gates 1–3 for the model layer; start from a model pretrained on public handwriting and fine-tune per person; compare with the glyph library on the same held-out text; export so it runs offline.
- **Success:** beats the glyph library on blind comparison for the same writer, runs on the owner's machine.

## Reference: how printer control works (from the sibling project)

- USB serial at 115200; open with **DTR low** so Creality boards do not reset; wait ~2 s, flush, send `M115` and wait for `ok`.
- **One line at a time, then wait for `ok`** (Marlin's flow control). `busy:` and `wait` extend the wait; `Resend:` needs numbered lines; `Error:` is fatal. `M400` then `M114` reads the position.
- A host-side runner owns pausing; the sim twin accepts the same lines and raises the same exceptions.
- Stock V3 SE firmware turns bed-mesh compensation off at every `G28` — we avoid mesh entirely.
- `M112` halts Marlin until reset; a UI should keep an emergency stop one click away.

## Probe result 1 - iPad Pro M4 + Apple Pencil Pro, Safari 26.5 (2026-10-30)

Source: `data/probe/probe-20261030-123914.json` (3,542 events, 14 strokes; git-ignored).

| Signal | Result |
|--------|--------|
| Position (x, y) | Yes, 0.5 CSS px steps (one device pixel) |
| Pressure | Yes, 0 to 0.61 (1,328 distinct values); 0 while hovering |
| Tilt X / Y, altitude, azimuth | Yes, all vary during contact. While hovering altitude is constant (1.571) - **no tilt before touchdown** |
| Hover presence | Yes: 634 events with nothing pressed, so the path between strokes is visible (x, y only) |
| Hover height (z) | **Impossible from Safari** (no such field) |
| Barrel roll (`twist`) | Reported but constant 0. Either Safari does not expose Pencil Pro roll, or the roll move was not done - **to re-test** |
| Tangential pressure | Constant 0 - not usable |
| Sample rate | About **106 samples/s** in strokes (about 2 samples per 16.7 ms frame). `getCoalescedEvents` does **not exist** in this Safari, so the 240 Hz sensor stream is not reachable |
| Timestamps | **Quantised to the frame**: 43% of consecutive samples share a timestamp, so exact in-frame times are lost (interpolate) |
| `getPredictedEvents` | Present (not needed) |

Reading: the web route gives position, pressure, tilt and hover presence at about 106 samples/s with frame-quantised time. It cannot give 240 Hz sampling, hover height, or (so far) roll. Whether that is enough is the owner's decision (see the open question in the log).

Two bugs found in the probe itself and fixed the same day: the sample rate was first reported as 59 Hz because the analysis ignored samples sharing a timestamp; and ink was drawn offset from the pen because the page used viewport coordinates on a canvas below the header (recorded coordinates were always correct).

## Probe result 2 - same iPad Pro M4 + Pencil Pro, fixed page (2026-10-30)

Source: `data/probe/probe-20261030-125553.json` (3,937 events, 13 pen strokes; git-ignored).

- Confirms result 1: pressure, tilt X/Y, altitude, azimuth and hover presence work; about **115 samples/s**; timestamps frame-quantised (47% shared); no `getCoalescedEvents`.
- **Barrel roll (`twist`) stayed 0 for every pen and touch event again.** Taken with result 1, treat roll as **not available from Safari** unless a later test proves otherwise. Pencil Pro squeeze is also not visible: pen `buttons` only ever took the values 0 and 1.
- All 13 pen strokes ended cleanly (`pointerup`); none were cancelled. The 6 `pointercancel` events were all **touch** (palm or finger), 55 touch events in total, so the capture app must **ignore `pointerType: touch`** while writing.
- Pressure is 0 only on the last few samples of a stroke (the lift); never mid-stroke. Pen-down pressure starts at 0.08.
- The saved `canvasRect.top` is 60 px: exactly the header height that caused the ink offset fixed earlier. The fixed page was in use for this run.
