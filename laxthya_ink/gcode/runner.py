"""Stream G-code lines to a `PrinterLink`, one at a time, waiting for `ok`.

`run()` is blocking and meant to be driven on a worker thread when a UI exists.
`pause()`, `resume()` and `cancel()` are safe to call from another thread; a
cancel stops streaming but does NOT move the pen - the caller sends
`planner.safe_stop_commands()` afterwards (see `cli.execute`).

**Line numbers / checksum / resend (opt-in via `gcode.use_line_numbers`,
default off).** Plain-line streaming has no way to service a `Resend:` - it is
fatal. With numbering on, every line is sent as `N<n> ...*<checksum>` and a small
buffer of recently sent lines lets a `ResendRequested` be replayed instead of
ending the run. Unverified on real hardware - bench-test before enabling.

Ported from the Ender-3 V3 SE magnet-embed project (sentinel and firmware-pause
handling removed - a handwriting job has neither).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

from ..exceptions import ResendRequested
from ..links.base import PrinterLink
from .util import build_numbered_line, strip_comment

log = logging.getLogger(__name__)

#: how many recently sent numbered lines are kept for a resend replay
_RESEND_BUFFER = 64


class GcodeRunner:
    def __init__(
        self,
        link: PrinterLink,
        lines: Sequence[str],
        config: dict,
        lock: threading.Lock | None = None,
    ) -> None:
        self.link = link
        self.lines = list(lines)
        self._ack_timeout = config["printer"]["ack_timeout_s"]
        self._use_numbers = bool(config["gcode"]["use_line_numbers"])
        self._next_n = 1
        self._sent_buffer: dict[int, str] = {}
        # Shared with any out-of-band sender so its send/`ok` cannot interleave
        # with a streamed line's - both read replies off the same connection.
        self._lock = lock if lock is not None else threading.Lock()

        self._resume_evt = threading.Event()
        self._resume_evt.set()            # set == running, clear == paused
        self._cancel_evt = threading.Event()

        self.total_lines = len(self.lines)
        self.sent_lines = 0
        self.current_line = 0
        self.finished = False

    # --- control (call from any thread) --------------------------------

    def pause(self) -> None:
        self._resume_evt.clear()

    def resume(self) -> None:
        self._resume_evt.set()

    def cancel(self) -> None:
        self._cancel_evt.set()
        self._resume_evt.set()            # unblock a paused run so it can exit

    @property
    def paused(self) -> bool:
        return not self._resume_evt.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_evt.is_set()

    # --- run ---------------------------------------------------------

    def run(self) -> None:
        if self._use_numbers:
            with self._lock:
                self.link.send_line(build_numbered_line(0, "M110 N0"))
                self.link.wait_ok(self._ack_timeout)
            self._next_n = 1

        for index, raw in enumerate(self.lines, start=1):
            self.current_line = index
            if self._cancel_evt.is_set():
                return
            self._resume_evt.wait()
            if self._cancel_evt.is_set():
                return

            bare = strip_comment(raw).strip()
            if not bare:
                continue                  # blank or pure comment - don't bother the printer

            self._transmit(raw.strip(), bare)
            self.sent_lines += 1

        self.finished = True

    # --- send ---------------------------------------------------------

    def _transmit(self, raw: str, bare: str) -> None:
        """Send one line, numbered/checksummed and resend-capable if
        `gcode.use_line_numbers` is on, plain otherwise."""
        if self._use_numbers:
            self._send_numbered(bare)
        else:
            with self._lock:
                self.link.send_line(raw)
                self.link.wait_ok(self._ack_timeout)

    def _send_numbered(self, bare: str) -> None:
        n = self._next_n
        self._next_n += 1
        self._sent_buffer[n] = bare
        if len(self._sent_buffer) > _RESEND_BUFFER:
            del self._sent_buffer[min(self._sent_buffer)]
        with self._lock:
            self._send_and_resolve(n, build_numbered_line(n, bare))

    def _send_and_resolve(self, n: int, text: str) -> None:
        """Send `text` (already numbered) and wait for `ok`; on a resend request,
        replay every buffered line from the requested number through the last
        one sent, in order, handling any further resend during the replay.
        Must be called with `self._lock` held. Raises `ResendRequested`
        unchanged if the firmware wants a line no longer in the buffer."""
        self.link.send_line(text)
        try:
            self.link.wait_ok(self._ack_timeout)
        except ResendRequested as exc:
            from_n = int(exc.line_number)
            for k in range(from_n, self._next_n):
                bare_k = self._sent_buffer.get(k)
                if bare_k is None:
                    raise
                self._send_and_resolve(k, build_numbered_line(k, bare_k))
