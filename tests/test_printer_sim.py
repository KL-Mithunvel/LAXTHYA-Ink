import pytest

from laxthya_ink.exceptions import AckTimeout, PrinterConnectionError, PrinterError
from laxthya_ink.links.printer_sim import SimPrinter


def _sim(**kw) -> SimPrinter:
    s = SimPrinter(**kw)
    s.connect()
    return s


def test_send_before_connect_raises():
    with pytest.raises(PrinterConnectionError):
        SimPrinter().send_line("G28")


def test_wait_ok_without_a_line_times_out():
    with pytest.raises(AckTimeout):
        _sim().wait_ok()


def test_absolute_and_relative_moves():
    s = _sim()
    s.command("G1 X10 Y20 Z5")
    s.command("G91")
    s.command("G1 X-4 Z1")
    assert (s.state.x, s.state.y, s.state.z) == (6.0, 20.0, 6.0)


def test_numbered_lines_are_accepted():
    s = _sim()
    s.command("N1 G1 X7*0")
    assert s.state.x == 7.0


def test_m112_halts_until_m999():
    s = _sim()
    s.command("M112")
    with pytest.raises(PrinterError, match="halted"):
        s.send_line("G1 X1")
    s.command("M999")
    s.command("G1 X1")


def test_pen_segment_recorded_only_while_pen_is_down():
    s = _sim(pen_contact_z=1.0)
    s.command("G0 Z5")
    s.command("G0 X10 Y10")             # travelling, pen up: nothing recorded
    s.command("G1 Z1")                  # touch down
    s.command("G1 X20 Y10")
    s.command("G1 X20 Y20")
    s.command("G0 Z5")                  # lift
    s.command("G0 X50 Y50")             # travel again
    assert s.pen_segments == [[(10.0, 10.0), (20.0, 10.0), (20.0, 20.0)]]


def test_each_pen_down_starts_a_new_segment_and_a_dot_is_one_point():
    s = _sim(pen_contact_z=1.0)
    s.command("G0 Z5")
    for x in (10, 30):
        s.command(f"G0 X{x} Y0")
        s.command("G1 Z1")
        s.command("G0 Z5")
    assert s.pen_segments == [[(10.0, 0.0)], [(30.0, 0.0)]]


def test_pen_offset_shifts_recorded_tip():
    s = _sim(pen_contact_z=1.0, pen_offset=(30.0, -2.0))
    s.command("G0 Z5")
    s.command("G0 X10 Y10")
    s.command("G1 Z1")
    assert s.pen_segments == [[(40.0, 8.0)]]


def test_homing_is_not_drawing():
    s = _sim(pen_contact_z=1.0)        # sim home Z is 0.0, below the contact height
    s.command("G28")
    s.command("G0 Z5")
    assert s.pen_segments == []


def test_pen_tracking_disabled_by_default():
    s = _sim()
    s.command("G1 Z0")
    assert s.pen_segments == []
