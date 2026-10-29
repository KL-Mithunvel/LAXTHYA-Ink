"""Find the printer on the serial ports, so `port: auto` works in config.

Each candidate port is *asked* rather than guessed from its USB chip: the printer
answers ``M115`` with a Marlin banner (opened with DTR low, the same gentle way
`SerialPrinter` opens it, so the board is not reset). Only read-only commands are
ever sent - never a move. Several ports answering is an error, not a coin toss.
The serial opener and the port list are injectable so the tests need no hardware.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

log = logging.getLogger(__name__)

AUTO = "auto"


class PortNotFound(Exception):
    """No (or no single) matching device; the message says what was tried."""


def is_auto(port: object) -> bool:
    return isinstance(port, str) and port.strip().lower() == AUTO


def candidate_ports(comports=None) -> list[str]:
    """Device names worth probing: Bluetooth and virtual ports are skipped."""
    if comports is None:
        from serial.tools import list_ports

        comports = list_ports.comports()
    out: list[str] = []
    for info in comports:
        desc = (getattr(info, "description", "") or "").lower()
        hwid = getattr(info, "hwid", "") or ""
        if "bluetooth" in desc or hwid.upper().startswith("BTHENUM") or hwid == "n/a":
            continue
        out.append(info.device)
    return sorted(out)


def _default_opener(port: str, baud: int, dtr: bool | None):
    import serial  # pyserial; lazy so the sim and tests don't need it

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = 0.3
    if dtr is not None:
        ser.dtr = dtr
    ser.open()
    return ser


def _ask(ser, command: bytes, matches: Callable[[str], bool], listen_s: float) -> bool:
    """Send `command` (retried every second) and watch replies for `listen_s`."""
    end = time.monotonic() + listen_s
    next_send = 0.0
    while time.monotonic() < end:
        if time.monotonic() >= next_send:
            ser.write(command)
            next_send = time.monotonic() + 1.0
        raw = ser.readline()
        if raw and matches(raw.decode("ascii", "replace")):
            return True
    return False


def _probe(port, baud, command, matches, *, dtr, settle_s, listen_s, opener) -> bool:
    try:
        ser = opener(port, baud, dtr)
    except Exception as exc:  # noqa: BLE001 - busy / vanished / no permission: just not ours
        log.debug("skip %s: %s", port, exc)
        return False
    try:
        time.sleep(settle_s)
        try:
            ser.reset_input_buffer()
        except Exception:  # noqa: BLE001
            pass
        return _ask(ser, command, matches, listen_s)
    except Exception as exc:  # noqa: BLE001
        log.debug("probe %s failed: %s", port, exc)
        return False
    finally:
        try:
            ser.close()
        except Exception:  # noqa: BLE001
            pass


def _is_printer_reply(text: str) -> bool:
    t = text.strip().lower()
    return "firmware_name" in t or t == "ok" or t.startswith("ok ")


def _pick(kind: str, tried: list[str], hits: list[str]) -> str:
    if len(hits) == 1:
        return hits[0]
    if not hits:
        seen = ", ".join(tried) if tried else "no usable serial ports"
        raise PortNotFound(f"no {kind} found (tried: {seen}) - plug it in, or set the port by hand")
    raise PortNotFound(
        f"several ports answered as the {kind} ({', '.join(hits)}) - set the port by hand"
    )


def find_printer(
    baud: int = 115200, *, comports=None, opener=None, settle_s: float = 1.0, listen_s: float = 3.0
) -> str:
    opener = opener or _default_opener
    tried = candidate_ports(comports)
    hits = [
        p for p in tried
        if _probe(p, baud, b"M115\n", _is_printer_reply,
                  dtr=False, settle_s=settle_s, listen_s=listen_s, opener=opener)
    ]
    return _pick("printer", tried, hits)
