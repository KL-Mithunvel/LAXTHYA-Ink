"""Plain data structure: a printer state snapshot."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass
class PrinterState:
    """A best-effort snapshot of the printer. Mutated in place by the links."""

    connected: bool = False
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    e: float = 0.0
    nozzle_temp: float = 0.0
    nozzle_target: float = 0.0
    bed_temp: float = 0.0
    bed_target: float = 0.0
    absolute_xyz: bool = True   # G90 (True) / G91 (False)
    absolute_e: bool = True     # M82 (True) / M83 (False)
    feedrate: float = 0.0       # mm/min, last F word seen
    homed: bool = False

    def copy(self) -> "PrinterState":
        return replace(self)
