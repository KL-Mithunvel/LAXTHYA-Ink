import pytest

from laxthya_ink.exceptions import OutOfEnvelopeError, WritingAreaError
from laxthya_ink.gcode.util import parse_words
from laxthya_ink.planner import (
    dedupe,
    layout,
    pen_heights,
    plan_job,
    safe_stop_commands,
    simplify,
)
from laxthya_ink.strokes import Point, Stroke, load_strokes


def _line(*strokes):
    """A line from polylines given as [(x, y), ...]."""
    return [Stroke([Point(x, y) for x, y in s]) for s in strokes]


# --- geometry ---------------------------------------------------------------

def test_simplify_removes_collinear_points():
    pts = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]
    assert simplify(pts, 0.01) == [(0.0, 0.0), (3.0, 0.0)]


def test_simplify_keeps_a_corner():
    pts = [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0)]
    assert simplify(pts, 0.1) == pts


def test_simplify_closed_loop_keeps_shape():
    loop = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    assert simplify(loop, 0.1) == loop             # degenerate start==end segment must not collapse it


def test_simplify_zero_tolerance_is_noop():
    pts = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    assert simplify(pts, 0) == pts


def test_dedupe_drops_close_points_but_keeps_last():
    pts = [(0.0, 0.0), (0.001, 0.0), (1.0, 0.0), (1.001, 0.0)]
    assert dedupe(pts, 0.02) == [(0.0, 0.0), (1.0, 0.0), (1.001, 0.0)]


def test_dedupe_single_point_stays():
    assert dedupe([(3.0, 4.0)], 0.02) == [(3.0, 4.0)]


# --- layout -----------------------------------------------------------------

def test_layout_places_first_baseline_one_spacing_below_top(config):
    config["writing"]["simplify_tolerance_mm"] = 0
    paper, spacing = config["paper"], config["writing"]["line_spacing_mm"]
    polys = layout([_line([(0, 0), (4, 0)])], config)
    top = paper["origin_y"] + paper["height_mm"]
    assert polys == [[(paper["origin_x"], top - spacing), (paper["origin_x"] + 4, top - spacing)]]


def test_layout_second_line_is_lower(config):
    polys = layout([_line([(0, 0), (4, 0)]), _line([(0, 0), (4, 0)])], config)
    assert polys[0][0][1] - polys[1][0][1] == pytest.approx(config["writing"]["line_spacing_mm"])


def test_layout_scale_applies(config):
    config["writing"]["scale_mm_per_unit"] = 2.0
    config["writing"]["simplify_tolerance_mm"] = 0
    (poly,) = layout([_line([(0, 0), (5, 0)])], config)
    assert poly[1][0] - poly[0][0] == pytest.approx(10.0)


@pytest.mark.parametrize("pts", [[(0, 0), (500, 0)], [(-1, 0), (3, 0)], [(0, 0), (0, 500)]])
def test_layout_refuses_points_off_the_paper(config, pts):
    with pytest.raises(WritingAreaError, match="outside the paper"):
        layout([_line(pts)], config)


def test_layout_refuses_too_many_lines(config):
    n = int(config["paper"]["height_mm"] / config["writing"]["line_spacing_mm"]) + 1
    with pytest.raises(WritingAreaError):
        layout([_line([(0, 0), (1, 0)])] * n, config)


# --- G-code -----------------------------------------------------------------

def test_plan_structure_for_one_stroke(config):
    config["start"]["home"] = False
    plan = plan_job([_line([(0, 0), (10, 0)])], config)
    down, up, safe = pen_heights(config)
    zs = [parse_words(g).get("Z") for g in plan.gcode if g.startswith(("G0", "G1")) and "Z" in g]
    # safe, lower to down, lift to up, safe again
    assert zs == [safe, down, up, safe]
    assert plan.gcode[0].startswith(";")
    assert plan.gcode[-1] == "M400"
    assert plan.stroke_count == 1 and plan.point_count == 2
    assert plan.draw_length_mm == pytest.approx(10.0)


def test_home_line_follows_config(config):
    config["start"]["home"] = True
    assert "G28" in plan_job([_line([(0, 0), (1, 0)])], config).gcode
    config["start"]["home"] = False
    assert "G28" not in plan_job([_line([(0, 0), (1, 0)])], config).gcode


def test_pen_offset_is_subtracted_from_nozzle_target(config):
    config["start"]["home"] = False
    config["pen"]["offset_x"] = 30.0
    config["pen"]["offset_y"] = -4.0
    config["writing"]["simplify_tolerance_mm"] = 0
    plan = plan_job([_line([(0, 0), (4, 0)])], config)
    tip_start = plan.segments[0][0]
    travel = next(g for g in plan.gcode if g.startswith("G0") and "X" in g and "Y" in g)
    words = parse_words(travel)
    assert words["X"] == pytest.approx(tip_start[0] - 30.0)
    assert words["Y"] == pytest.approx(tip_start[1] + 4.0)


def test_nozzle_outside_machine_is_refused(config):
    config["pen"]["offset_x"] = 100.0      # nozzle would need x = 40 - 100 < 0
    with pytest.raises(OutOfEnvelopeError, match="outside the machine"):
        plan_job([_line([(0, 0), (4, 0)])], config)


def test_feed_is_only_repeated_when_it_changes(config):
    config["start"]["home"] = False
    config["writing"]["simplify_tolerance_mm"] = 0
    plan = plan_job([_line([(0, 0), (1, 0), (2, 0), (3, 0)])], config)
    draws = [g for g in plan.gcode if g.startswith("G1 X")]
    assert len(draws) == 3
    assert sum("F" in g for g in draws) == 1


def test_dwell_emitted_when_configured(config):
    config["pen"]["down_dwell_ms"] = 150
    assert "G4 P150" in plan_job([_line([(0, 0), (1, 0)])], config).gcode


def test_single_point_stroke_is_a_dot(config):
    config["start"]["home"] = False
    plan = plan_job([_line([(0, 0)])], config)
    assert plan.stroke_count == 1
    assert not any(g.startswith("G1 X") for g in plan.gcode)     # lowered and lifted, no drawing move
    assert any(g.startswith("G1 Z") for g in plan.gcode)


def test_pen_below_min_z_refused(config):
    config["pen"]["min_z"] = 0.0
    config["pen"]["down_z"] = -1.0
    with pytest.raises(OutOfEnvelopeError, match="min_z"):
        pen_heights(config)


def test_pen_up_above_machine_refused(config):
    config["machine"]["z_max"] = 6.0
    with pytest.raises(OutOfEnvelopeError, match="z_max"):
        pen_heights(config)


def test_safe_stop_lifts_before_moving_xy(config):
    cmds = safe_stop_commands(config)
    z_idx = next(i for i, g in enumerate(cmds) if parse_words(g).get("Z") is not None)
    xy_idx = next(i for i, g in enumerate(cmds) if "X" in parse_words(g))
    assert z_idx < xy_idx
    assert parse_words(cmds[z_idx])["Z"] == config["park"]["safe_z"]


def test_sample_file_plans(config, sample_strokes_path):
    plan = plan_job(load_strokes(sample_strokes_path), config)
    assert plan.stroke_count == 4
