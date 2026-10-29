"""SerialPrinter and ports, driven by a fake transport - no hardware needed."""

import collections
from types import SimpleNamespace

import pytest

from laxthya_ink import ports
from laxthya_ink.exceptions import (
    AckTimeout,
    PrinterConnectionError,
    PrinterError,
    ResendRequested,
)
from laxthya_ink.links.printer_serial import SerialPrinter


class FakeSerial:
    """Replies to each written line from a script keyed by the command word."""

    def __init__(self, script=None):
        self.script = script or {}
        self.rx = collections.deque()
        self.written: list[str] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        text = data.decode("ascii").strip()
        self.written.append(text)
        head = text.split()[0] if text else ""
        for reply in self.script.get(head, ["ok"]):
            self.rx.append((reply + "\n").encode("ascii"))

    def readline(self) -> bytes:
        return self.rx.popleft() if self.rx else b""

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def _printer(script=None, **kw) -> tuple[SerialPrinter, FakeSerial]:
    fake = FakeSerial(script)
    p = SerialPrinter("COM9", 115200, ack_timeout_s=0.2, connect_settle_s=0,
                      read_timeout_s=0, transport_factory=lambda: fake, **kw)
    return p, fake


def test_connect_does_m115_handshake():
    p, fake = _printer()
    p.connect()
    assert fake.written == ["M115"] and p.state.connected


def test_open_failure_is_a_connection_error():
    def boom():
        raise OSError("port busy")

    p = SerialPrinter("COM9", connect_settle_s=0, transport_factory=boom)
    with pytest.raises(PrinterConnectionError, match="port busy"):
        p.connect()


def test_send_before_connect_raises():
    p, _ = _printer()
    with pytest.raises(PrinterConnectionError):
        p.send_line("G28")


def test_busy_extends_the_deadline_then_ok():
    p, _ = _printer({"G28": ["echo:busy: processing", "echo:busy: processing", "ok"]})
    p.connect()
    p.send_line("G28")
    assert p.wait_ok() == "ok"


def test_missing_ok_times_out():
    p, _ = _printer({"G4": []})
    p.connect()
    p.send_line("G4 P10")
    with pytest.raises(AckTimeout):
        p.wait_ok()


def test_resend_and_error_become_exceptions():
    p, _ = _printer({"G1": ["Resend: 7"], "M999": ["Error:Printer halted"]})
    p.connect()
    p.send_line("G1 X1")
    with pytest.raises(ResendRequested) as exc:
        p.wait_ok()
    assert exc.value.line_number == 7
    p.send_line("M999")
    with pytest.raises(PrinterError, match="halted"):
        p.wait_ok()


def test_query_state_parses_m114_and_temps():
    p, _ = _printer({"M114": ["X:10.00 Y:20.00 Z:3.00 E:0.00 Count X:800", "ok T:21.0 /0.0 B:22.0 /0.0"]})
    p.connect()
    st = p.query_state()
    assert (st.x, st.y, st.z) == (10.0, 20.0, 3.0)
    assert (st.nozzle_temp, st.bed_temp) == (21.0, 22.0)


def test_modal_state_is_tracked_from_outgoing_lines():
    p, _ = _printer()
    p.connect()
    p.send_line("G91")
    p.send_line("N3 G1 X1 F900*12")
    assert p.state.absolute_xyz is False and p.state.feedrate == 900.0


def test_disconnect_closes_transport():
    p, fake = _printer()
    p.connect()
    p.disconnect()
    assert fake.closed and not p.state.connected


# --- ports ------------------------------------------------------------------

def _info(device, description="USB Serial", hwid="USB VID:PID=1A86:7523"):
    return SimpleNamespace(device=device, description=description, hwid=hwid)


def test_candidate_ports_skips_bluetooth_and_virtual():
    infos = [_info("COM3"), _info("COM4", "Standard Serial over Bluetooth link"),
             _info("COM5", hwid="BTHENUM\\x"), _info("COM6", hwid="n/a")]
    assert ports.candidate_ports(infos) == ["COM3"]


def _opener(answering: set[str]):
    def opener(port, baud, dtr):
        fake = FakeSerial({"M115": ["FIRMWARE_NAME:Marlin"] if port in answering else ["???"]})
        return fake
    return opener


def test_find_printer_picks_the_single_answering_port():
    got = ports.find_printer(comports=[_info("COM3"), _info("COM4")], opener=_opener({"COM4"}),
                             settle_s=0, listen_s=0.3)
    assert got == "COM4"


def test_find_printer_none_found():
    with pytest.raises(ports.PortNotFound, match="no printer found"):
        ports.find_printer(comports=[_info("COM3")], opener=_opener(set()), settle_s=0, listen_s=0.2)


def test_find_printer_ambiguous_is_an_error_not_a_guess():
    with pytest.raises(ports.PortNotFound, match="several"):
        ports.find_printer(comports=[_info("COM3"), _info("COM4")], opener=_opener({"COM3", "COM4"}),
                           settle_s=0, listen_s=0.3)


def test_unopenable_port_is_skipped():
    def opener(port, baud, dtr):
        if port == "COM3":
            raise OSError("busy")
        return FakeSerial({"M115": ["ok"]})

    got = ports.find_printer(comports=[_info("COM3"), _info("COM4")], opener=opener,
                             settle_s=0, listen_s=0.3)
    assert got == "COM4"


def test_auto_detection_is_used_by_connect(monkeypatch):
    monkeypatch.setattr(ports, "find_printer", lambda baud: "COM8")
    fake = FakeSerial()
    p = SerialPrinter("auto", connect_settle_s=0, ack_timeout_s=0.2, read_timeout_s=0,
                      transport_factory=lambda: fake)
    p.connect()
    assert p.port == "COM8"


def test_auto_detection_failure_is_a_connection_error(monkeypatch):
    def none_found(baud):
        raise ports.PortNotFound("no printer found")

    monkeypatch.setattr(ports, "find_printer", none_found)
    with pytest.raises(PrinterConnectionError, match="no printer found"):
        SerialPrinter("auto", transport_factory=lambda: FakeSerial()).connect()
