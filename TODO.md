# TODO

## In Progress
- [ ] Phase 2 — first real writing (see `docs/PROJECT_PLAN.md`): clear Gate 4, then `--printer --ping`.


## Done
- [x] LAXTHYA-Ink Phase 1 (2026-10-28) — filled `.CLAUDE/CLAUDE.md` (overview, gates, architecture, rules); `docs/PROJECT_PLAN.md`; ported the printer link layer from the Ender-3 V3 SE project; stroke format + loader; pure planner (layout, simplify, G-code, bounds checks); sim printer with pen-path recording; CLI; PNG preview; 111 tests green. Not yet committed.
- [x] Create the `machine-vision` branch holding the claude_MV baseline (four gates, docs, tools, Roboflow skills) — pushed to origin (924a9c1 on `machine-vision`).
- [x] Add generic rules from the machine-vision work to `CLAUDE-COMMON.md` — Documentation Discipline, Secrets & Credentials, Preflight Gates (with three example gates), "no hardcoded parameters" for all projects, Standard Project Layout, and a Preflight Gates slot in the skeleton and in `CLAUDE.md`.
- [x] Add baseline `.gitignore` and `tools/compute_survey.py` (generalised docstring; verified on Windows 11).

- [x] Integrate `origin/main` PR #3 (Documentation Discipline + "ok KLM" opener) — merged; removed the duplicate Documentation Discipline section, keeping the `docs/` version. The "ok KLM" opener is now on `main`.
- [x] ~~Merge `main` into `machine-vision`~~ — CANCELLED. The owner keeps the two branches as separate personal copies and never merges them. Added a "Branch Policy" section to `.CLAUDE/CLAUDE.md` so future AI sessions know.

## Not Started
- [ ] 🔴 Pause-lift: `GcodeRunner.pause()` leaves the pen on the paper (Technical Debt, Dev Rule 9); also lift on cancel inside the runner.
- [ ] 🟡 Pen calibration helper (offset + `pen.down_z`): guided paper-test tool in `tools/`, modelled on the sibling's Z-calibrate dialog.
- [ ] 🟡 Hardware smoke test: `--printer --ping`, dry run with the pen removed, stepped pen-down, sample strokes on paper (Gate 4 first).
- [ ] 🟡 Verify on this repo's hardware: `SerialPrinter`, `ports.find_printer`, `G28` then first pen move; decide on `gcode.use_line_numbers`.
- [ ] 🟢 Answer the open questions: capture source, pen mount, capture-while-able vs recover-from-old-writing.
- [ ] 🟢 Phase 3 — handwriting capture tool (Gate 1 first).
- [ ] 🟢 Phase 4 — glyph-library writer (v1).
- [ ] 🟢 Phase 5 — neural writer model (v2; Gates 2 and 3 for the model layer).
- [ ] 🟢 Use `t`/`pressure` in the planner (speed or pen-height from pressure).
- [ ] 🟢 Add `ruff` and configure it.
- [ ] Pin dependencies that silently break: record the pin, the reason, and a verification command (machine-vision Development Rule 7).
- [ ] Record failed experiments and attempts with their numbers (machine-vision Development Rule 8).
- [ ] Label provisional values as provisional in code and docs until confirmed (machine-vision Development Rule 6, needs rewording beyond hardware thresholds).
- [ ] Honest-reporting rule: state what each number was measured on, compare like with like, treat tiny deltas as noise (needs rewording without model/val-set language).
- [ ] "Rule → evidence" style: every template rule carries a one-line "why this exists".
- [ ] Housekeeping: pick one log file location and name. `CLAUDE-COMMON.md` says root `Claude_log.md`; this repo keeps `.CLAUDE/CLAUDE-LOG.md` and the index points there.
- [ ] Personal preference to decide: whether "explain before acting" gets an "unless autonomous completion was asked for" clause. (The "ok KLM" opener is done — see Done.)
