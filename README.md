# LAXTHYA-Ink

A pen mounted on a Creality Ender-3 V3 SE that writes **in a person's own handwriting** — for example for someone who has recently lost control of their writing hand. A longer-term goal is to learn a writer's style automatically from their real samples.

**Status:** the plotting pipeline works on the dev machine against a simulated printer (111 tests). It has not yet run on the real printer, and handwriting capture and the learning models are not built. See `docs/PROJECT_PLAN.md`.

## Quick start

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

python -m pytest
python main.py tests\data\sample_strokes.json --preview data\out.png
```

That plans the sample strokes, streams them to a simulated printer with a pen, and saves the path the simulated pen drew.

More modes: `--dry-run --gcode-out job.gcode` (plan only), `--printer` (real hardware — refused until the pen is calibrated, see below), `--printer --ping` (connect and print position).

## How it works

```
stroke JSON → planner (layout, simplify, G-code) → runner → printer (sim or USB serial)
```

A stroke file holds lines of strokes in writing units (x right, y up, baseline at y = 0). The planner scales them onto the configured paper area, converts pen-tip positions to nozzle positions using the measured pen offset, and emits G-code that travels with the pen up, lowers it with Z, draws, and lifts. Every limit (paper area, machine volume, Z heights) is checked before anything is sent.

## Before the first real run

Real-printer runs are refused until `pen.down_z_calibrated` is true. Measure the pen offset and the Z where the pen tip just touches the paper, and put them in `config.local.yaml` (git-ignored):

```yaml
printer: {port: COM3}
pen: {offset_x: 30.0, offset_y: 0.0, down_z: 3.2, down_z_calibrated: true}
```

Then follow the smoke-test order in `.CLAUDE/CLAUDE.md` → Deployment Notes.

## Documents

| File | What |
|------|------|
| `.CLAUDE/CLAUDE.md` | Project brief — gates, architecture, modules, conventions, rules |
| `docs/PROJECT_PLAN.md` | Phased plan, decisions, open questions, how printer control works |
| `TODO.md` | Task tracker |
| `.CLAUDE/CLAUDE-LOG.md` | Session log |

Handwriting samples are personal data: keep them under the git-ignored `data/` folder.
