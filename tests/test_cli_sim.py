"""End to end on the simulator: strokes -> plan -> stream -> simulated pen path."""

import pytest

from laxthya_ink.cli import execute, main, make_sim, require_calibrated
from laxthya_ink.exceptions import AckTimeout, PenNotCalibratedError
from laxthya_ink.planner import plan_job
from laxthya_ink.strokes import load_strokes


def test_simulated_pen_path_matches_the_plan(config, sample_strokes_path):
    plan = plan_job(load_strokes(sample_strokes_path), config)
    sim = make_sim(config)
    sim.connect()
    execute(sim, plan.gcode, config)

    assert len(sim.pen_segments) == plan.stroke_count
    for drawn, planned in zip(sim.pen_segments, plan.segments):
        assert len(drawn) == len(planned)
        for (dx, dy), (px, py) in zip(drawn, planned):
            assert dx == pytest.approx(px, abs=1e-3)      # G-code carries 3 decimals
            assert dy == pytest.approx(py, abs=1e-3)


def test_pen_is_up_and_parked_after_a_job(config, sample_strokes_path):
    plan = plan_job(load_strokes(sample_strokes_path), config)
    sim = make_sim(config)
    sim.connect()
    execute(sim, plan.gcode, config)
    assert sim.state.z == config["park"]["safe_z"]
    assert (sim.state.x, sim.state.y) == (config["park"]["x"], config["park"]["y"])
    assert sim.state.z > config["pen"]["down_z"]


def test_pen_offset_still_draws_on_the_planned_spot(config, sample_strokes_path):
    config["pen"]["offset_x"] = 25.0
    config["pen"]["offset_y"] = 3.0
    plan = plan_job(load_strokes(sample_strokes_path), config)
    sim = make_sim(config)
    sim.connect()
    execute(sim, plan.gcode, config)
    assert sim.pen_segments[0][0] == pytest.approx(plan.segments[0][0], abs=1e-3)


def test_failure_mid_job_lifts_the_pen_and_parks(config, sample_strokes_path):
    plan = plan_job(load_strokes(sample_strokes_path), config)

    class _DiesWhilePenDown(type(make_sim(config))):
        def wait_ok(self, timeout_s=None):
            # fail on the first drawing move, while the pen is on the paper
            if self.pen_segments and self.sent[-1].startswith("G1 X") and not getattr(self, "_died", False):
                self._died = True
                raise AckTimeout("simulated cable pull")
            return super().wait_ok(timeout_s)

    pen = config["pen"]
    sim = _DiesWhilePenDown(pen_contact_z=pen["down_z"] + config["sim"]["contact_tolerance_mm"])
    sim.connect()
    with pytest.raises(AckTimeout):
        execute(sim, plan.gcode, config)
    assert sim.state.z == config["park"]["safe_z"]          # safe-stop ran


def test_require_calibrated_refuses_default(config):
    with pytest.raises(PenNotCalibratedError):
        require_calibrated(config)
    config["pen"]["down_z_calibrated"] = True
    require_calibrated(config)


def test_main_sim_with_outputs(sample_strokes_path, tmp_path, capsys):
    png, gcode = tmp_path / "out.png", tmp_path / "job.gcode"
    code = main([str(sample_strokes_path), "--preview", str(png), "--gcode-out", str(gcode)])
    out = capsys.readouterr().out
    assert code == 0
    assert "simulated pen drew 4 strokes" in out
    assert png.stat().st_size > 0
    assert gcode.read_text(encoding="utf-8").splitlines()[-1] == "M400"


def test_main_dry_run_needs_no_link(sample_strokes_path, capsys):
    assert main([str(sample_strokes_path), "--dry-run"]) == 0
    assert "planned 4 strokes" in capsys.readouterr().out


def test_main_printer_refused_while_uncalibrated(sample_strokes_path, capsys):
    assert main([str(sample_strokes_path), "--printer"]) == 1
    assert "down_z_calibrated" in capsys.readouterr().err


def test_main_reports_bad_input_without_traceback(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert main([str(bad)]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_main_needs_a_stroke_file(capsys):
    assert main([]) == 1
    assert "stroke file is required" in capsys.readouterr().err


def test_ping_needs_printer(capsys):
    assert main(["--ping"]) == 1
    assert "--printer" in capsys.readouterr().err
