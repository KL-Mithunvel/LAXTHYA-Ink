import threading

import pytest

from laxthya_ink.exceptions import ResendRequested
from laxthya_ink.gcode.runner import GcodeRunner
from laxthya_ink.gcode.util import strip_line_number
from laxthya_ink.links.printer_sim import SimPrinter


def _connected_sim() -> SimPrinter:
    s = SimPrinter()
    s.connect()
    return s


def test_streams_lines_and_skips_comments_and_blanks(config):
    sim = _connected_sim()
    runner = GcodeRunner(sim, ["; header", "G90", "", "G1 X5 Y6 ; tail", "  "], config)
    runner.run()
    assert sim.sent == ["G90", "G1 X5 Y6 ; tail"]
    assert runner.finished and runner.sent_lines == 2
    assert (sim.state.x, sim.state.y) == (5.0, 6.0)


def test_cancel_before_run_sends_nothing(config):
    sim = _connected_sim()
    runner = GcodeRunner(sim, ["G1 X1", "G1 X2"], config)
    runner.cancel()
    runner.run()
    assert sim.sent == [] and not runner.finished and runner.cancelled


def test_pause_blocks_until_resume(config):
    sim = _connected_sim()
    runner = GcodeRunner(sim, ["G1 X1", "G1 X2"], config)
    runner.pause()
    assert runner.paused
    worker = threading.Thread(target=runner.run)
    worker.start()
    worker.join(timeout=0.2)
    assert worker.is_alive() and sim.sent == []        # still waiting on resume
    runner.resume()
    worker.join(timeout=2)
    assert not worker.is_alive() and runner.finished


def test_cancel_unblocks_a_paused_run(config):
    runner = GcodeRunner(_connected_sim(), ["G1 X1"], config)
    runner.pause()
    worker = threading.Thread(target=runner.run)
    worker.start()
    runner.cancel()
    worker.join(timeout=2)
    assert not worker.is_alive() and not runner.finished


def test_numbered_mode_sends_checksummed_lines(config):
    config["gcode"]["use_line_numbers"] = True
    sim = _connected_sim()
    GcodeRunner(sim, ["G1 X3", "G1 X4"], config).run()
    assert sim.sent[0].startswith("N0 M110 N0*")
    assert [strip_line_number(s) for s in sim.sent[1:]] == ["G1 X3", "G1 X4"]
    assert sim.state.x == 4.0


class _ResendOnce(SimPrinter):
    """Asks for a resend of line 2 the first time it sees it."""

    def __init__(self):
        super().__init__()
        self._asked = False

    def wait_ok(self, timeout_s=None):
        if self.sent and self.sent[-1].startswith("N2 ") and not self._asked:
            self._asked = True
            self._acks.clear()
            raise ResendRequested(2)
        return super().wait_ok(timeout_s)


def test_resend_is_replayed_from_the_buffer(config):
    config["gcode"]["use_line_numbers"] = True
    sim = _ResendOnce()
    sim.connect()
    GcodeRunner(sim, ["G1 X1", "G1 X2", "G1 X3"], config).run()
    bodies = [strip_line_number(s) for s in sim.sent]
    assert bodies.count("G1 X2") == 2                  # sent, resent
    assert sim.state.x == 3.0


def test_resend_without_numbering_is_fatal(config):
    class _AlwaysResend(SimPrinter):
        def wait_ok(self, timeout_s=None):
            raise ResendRequested(1)

    sim = _AlwaysResend()
    sim.connect()
    with pytest.raises(ResendRequested):
        GcodeRunner(sim, ["G1 X1"], config).run()
