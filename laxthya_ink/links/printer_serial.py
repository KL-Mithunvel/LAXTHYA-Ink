"""Real printer link - G-code streaming to an Ender-3 V3 SE over USB serial.

Plain lines by default; `GcodeRunner` wraps them in `N<n> ...*<checksum>` when
`gcode.use_line_numbers` is on (opt-in, unverified on real hardware). Flow
control is the `ok` handshake: `send_line` then `wait_ok`. `wait_ok` tolerates
`wait` and resets its deadline on `busy:`; a `Resend:` becomes
`ResendRequested`, serviced by `GcodeRunner`'s resend buffer when numbering is
on, fatal otherwise.

Position/temps are learned from `M114` / temperature reports (`query_state()`
issues `M400` + `M114`). Coordinate/extruder modes and feedrate are tracked from
the outgoing stream because Marlin never reports them.

Ported from the Ender-3 V3 SE magnet-embed project, where this link was
verified on real hardware (COM3, 115200).
"""

from __future__ import annotations

import logging
import re
import time

from .. import ports
from ..exceptions import (
    AckTimeout,
    PrinterConnectionError,
    PrinterError,
    ResendRequested,
)
from ..gcode.util import strip_line_number
from ..state import PrinterState
from ._marlin_rx import classify, parse_position, parse_temps
from .base import PrinterLink

log = logging.getLogger(__name__)

_F_RE = re.compile(r"\bF(-?\d+(?:\.\d+)?)")


class SerialPrinter(PrinterLink):
    def __init__(
        self,
        port: str,
        baud: int = 115200,
        *,
        ack_timeout_s: float = 30.0,
        connect_settle_s: float = 2.0,
        read_timeout_s: float = 1.0,
        transport_factory=None,
    ) -> None:
        self.port = port
        self.baud = baud
        self._ack_timeout = ack_timeout_s
        self._settle = connect_settle_s
        self._read_timeout = read_timeout_s
        self._make_transport = transport_factory or self._default_transport
        self._ser = None
        self.state = PrinterState()

    # --- transport -------------------------------------------------

    def _default_transport(self):
        import serial  # pyserial; imported lazily so tests don't need it

        ser = serial.Serial()
        ser.port = self.port
        ser.baudrate = self.baud
        ser.timeout = self._read_timeout
        ser.dtr = False           # some Creality boards reset on DTR like an Arduino
        ser.open()
        return ser

    # --- PrinterLink ---------------------------------------------

    def connect(self) -> None:
        if ports.is_auto(self.port):
            try:
                self.port = ports.find_printer(self.baud)
            except ports.PortNotFound as exc:
                raise PrinterConnectionError(str(exc)) from exc
            log.info("auto-detected printer on %s", self.port)
        try:
            self._ser = self._make_transport()
        except Exception as exc:  # noqa: BLE001
            raise PrinterConnectionError(f"cannot open {self.port}: {exc}") from exc
        time.sleep(self._settle)
        _safe(self._ser.reset_input_buffer)
        self.send_line("M115")
        self.wait_ok(timeout_s=max(self._ack_timeout, 10.0))  # tolerate banner + echo lines
        self.state.connected = True
        log.info("connected to %s @ %d", self.port, self.baud)

    def disconnect(self) -> None:
        if self._ser is not None:
            _safe(self._ser.close)
        self.state.connected = False

    def send_line(self, line: str) -> None:
        if self._ser is None:
            raise PrinterConnectionError("send_line() before connect()")
        text = line.strip()
        self._track_outgoing(text)
        self._ser.write((text + "\n").encode("ascii", "replace"))

    def wait_ok(self, timeout_s: float | None = None) -> str:
        base = timeout_s or self._ack_timeout
        deadline = time.monotonic() + base
        while True:
            if time.monotonic() >= deadline:
                raise AckTimeout(f"no 'ok' within {base:g}s on {self.port}")
            raw = self._ser.readline()
            if not raw:
                continue
            line = raw.decode("ascii", "replace").strip()
            if not line:
                continue
            rx = classify(line)
            if rx.kind == "ok":
                self._absorb(line)
                return rx.raw
            if rx.kind == "busy":
                deadline = time.monotonic() + base       # printer is working - wait more
                continue
            if rx.kind == "wait":
                continue
            if rx.kind == "resend":
                raise ResendRequested(int(rx.detail))    # type: ignore[arg-type]
            if rx.kind == "error":
                raise PrinterError(str(rx.detail))
            self._absorb(line)                            # info / action

    def query_state(self) -> PrinterState:
        if self._ser is not None and self.state.connected:
            self.command("M400")
            self.command("M114")   # _absorb() picks up the position line before the ok
        return self.state.copy()

    # --- internals -----------------------------------------------

    def _track_outgoing(self, text: str) -> None:
        upper = strip_line_number(text).upper()
        head = upper.split(maxsplit=1)[0] if upper else ""
        if head == "G90":
            self.state.absolute_xyz = True
        elif head == "G91":
            self.state.absolute_xyz = False
        elif head == "M82":
            self.state.absolute_e = True
        elif head == "M83":
            self.state.absolute_e = False
        if head in ("G0", "G1"):
            m = _F_RE.search(upper)
            if m:
                self.state.feedrate = float(m.group(1))

    def _absorb(self, line: str) -> None:
        temps = parse_temps(line)
        if "nozzle" in temps:
            self.state.nozzle_temp, self.state.nozzle_target = temps["nozzle"]
        if "bed" in temps:
            self.state.bed_temp, self.state.bed_target = temps["bed"]
        pos = parse_position(line)
        if pos:
            self.state.x, self.state.y, self.state.z = pos[0], pos[1], pos[2]
            if pos[3] is not None:
                self.state.e = pos[3]


def _safe(fn) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001
        pass
