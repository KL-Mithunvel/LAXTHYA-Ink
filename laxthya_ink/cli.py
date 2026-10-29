"""Command line: plan a stroke file into G-code and run it on the simulator or the printer.

    python main.py strokes.json                          # simulate (default), safe anywhere
    python main.py strokes.json --preview out.png        # + save the pen path as a picture
    python main.py strokes.json --dry-run --gcode-out job.gcode   # plan only, no link
    python main.py strokes.json --printer                # REAL printer (needs calibrated pen Z)
    python main.py --printer --ping                      # connect, M115, print state, exit
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_config
from .exceptions import (
    AckTimeout,
    InkError,
    PenNotCalibratedError,
    PrinterConnectionError,
    PrinterError,
)
from .gcode.runner import GcodeRunner
from .links.base import PrinterLink
from .links.printer_serial import SerialPrinter
from .links.printer_sim import SimPrinter
from .planner import Plan, plan_job, safe_stop_commands
from .strokes import load_strokes

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="main.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("strokes", nargs="?", help="stroke JSON file (see laxthya_ink/strokes.py)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--sim", action="store_true", help="simulated printer (default)")
    mode.add_argument("--printer", action="store_true", help="real printer over USB serial")
    p.add_argument("--dry-run", action="store_true", help="plan only; do not connect to any link")
    p.add_argument("--gcode-out", metavar="FILE", help="write the planned G-code to FILE")
    p.add_argument("--preview", metavar="PNG", help="save the pen path as a PNG")
    p.add_argument("--ping", action="store_true", help="connect, print state, exit (needs --printer)")
    p.add_argument("--port", help="serial port, overriding printer.port")
    p.add_argument("--config", help="path to a config.yaml (default: the repo's)")
    return p


def require_calibrated(config: dict) -> None:
    """Refuse a real-printer run until the pen-down Z has been measured (Dev Rule 4)."""
    if not config["pen"]["down_z_calibrated"]:
        raise PenNotCalibratedError(
            "pen.down_z_calibrated is false - measure the pen-down Z on the machine, set "
            "pen.down_z and pen.down_z_calibrated: true in config.local.yaml, then retry"
        )


def make_sim(config: dict) -> SimPrinter:
    pen = config["pen"]
    return SimPrinter(
        command_delay=config["sim"]["command_delay_s"],
        pen_contact_z=pen["down_z"] + config["sim"]["contact_tolerance_mm"],
        pen_offset=(pen["offset_x"], pen["offset_y"]),
    )


def make_serial(config: dict, port: str | None = None) -> SerialPrinter:
    pc = config["printer"]
    return SerialPrinter(
        port or pc["port"], pc["baud"],
        ack_timeout_s=pc["ack_timeout_s"], connect_settle_s=pc["connect_settle_s"],
    )


def execute(link: PrinterLink, gcode: list[str], config: dict) -> GcodeRunner:
    """Stream `gcode` to a connected `link`. On any failure or interrupt, try to
    lift the pen and park before re-raising."""
    runner = GcodeRunner(link, gcode, config)
    try:
        runner.run()
    except BaseException:
        _safe_stop(link, config)
        raise
    return runner


def _safe_stop(link: PrinterLink, config: dict) -> None:
    try:
        for line in safe_stop_commands(config):
            link.command(line)
    except Exception as exc:  # noqa: BLE001 - best effort; the original error matters more
        log.error("safe-stop failed (lift the pen by hand!): %s", exc)


def _summary(plan: Plan) -> str:
    return (f"planned {plan.stroke_count} strokes, {plan.point_count} points, "
            f"{plan.draw_length_mm:.1f} mm of pen travel, {len(plan.gcode)} G-code lines")


def _ping(config: dict, port: str | None) -> int:
    printer = make_serial(config, port)
    printer.connect()
    st = printer.query_state()
    print(f"OK: {printer.port} connected; X{st.x} Y{st.y} Z{st.z}")
    printer.disconnect()
    return 0


def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)

    if args.ping:
        if not args.printer:
            raise InkError("--ping needs --printer")
        return _ping(config, args.port)
    if not args.strokes:
        raise InkError("a stroke file is required (see --help)")

    plan = plan_job(load_strokes(args.strokes), config)
    print(_summary(plan))
    if args.gcode_out:
        Path(args.gcode_out).write_text("\n".join(plan.gcode) + "\n", encoding="utf-8")
        print(f"wrote {args.gcode_out}")

    segments = plan.segments
    if not args.dry_run:
        if args.printer:
            require_calibrated(config)
            link: PrinterLink = make_serial(config, args.port)
        else:
            link = make_sim(config)
        link.connect()
        try:
            runner = execute(link, plan.gcode, config)
        finally:
            link.disconnect()
        print(f"sent {runner.sent_lines} lines")
        if isinstance(link, SimPrinter):
            segments = link.pen_segments        # what the simulated pen actually drew
            print(f"simulated pen drew {len(segments)} strokes")

    if args.preview:
        from .viz import render_preview

        out = render_preview(segments, config, args.preview, title=Path(args.strokes).name)
        print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        return run(args)
    except KeyboardInterrupt:
        print("interrupted - pen lifted and parked if the printer was reachable", file=sys.stderr)
        return 130
    except (InkError, PrinterConnectionError, AckTimeout, PrinterError, OSError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
