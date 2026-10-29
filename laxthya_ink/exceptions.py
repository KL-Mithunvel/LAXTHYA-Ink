"""Exception types shared across the package.

Simulated and real links raise the *same* types so callers cannot tell them apart
(Dev Rule 2).
"""

from __future__ import annotations


class InkError(Exception):
    """Base class for every error this package raises."""


# --- printer link ---------------------------------------------------------

class PrinterConnectionError(InkError):
    """Could not open or handshake with the printer."""


class AckTimeout(InkError):
    """The printer did not return `ok` within the timeout, and was not busy/waiting."""


class PrinterError(InkError):
    """The firmware reported an `Error:` line."""


class ResendRequested(InkError):
    """The firmware asked for a line resend.

    Plain-line streaming cannot satisfy this and treats it as fatal; with
    `gcode.use_line_numbers` on, `GcodeRunner` replays from its buffer instead.
    """

    def __init__(self, line_number: int, message: str = ""):
        self.line_number = line_number
        super().__init__(message or f"firmware requested resend from line {line_number}")


# --- stroke data and planning ------------------------------------------

class StrokeDataError(InkError):
    """A stroke file is missing fields, malformed, or holds non-finite numbers."""


class WritingAreaError(InkError):
    """The strokes, once laid out, fall outside the configured paper area."""


class OutOfEnvelopeError(InkError):
    """A planned nozzle position or Z is outside the machine limits or the allowed pen heights."""


class PenNotCalibratedError(InkError):
    """A real-printer run was requested while `pen.down_z_calibrated` is false (Dev Rule 4)."""
