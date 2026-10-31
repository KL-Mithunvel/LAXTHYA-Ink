"""Run the capture server: `python -m laxthya_ink.capture`."""

from __future__ import annotations

import socket

import uvicorn

from ..config import load_config
from .server import create_app


def lan_address() -> str | None:
    """This machine's address on the local network, or None if it cannot be found.

    A UDP `connect` sends no packet; it only makes the OS pick the outgoing interface.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))      # TEST-NET-1: never routed anywhere
            return s.getsockname()[0]
    except OSError:
        return None


def main() -> None:
    config = load_config()
    cap = config["capture"]
    ip = lan_address()
    host = ip or "<this-laptop-ip>"
    print("Capture server starting.")
    print("  iPad (same Wi-Fi as this laptop):")
    print(f"    writing app:   http://{host}:{cap['port']}/capture")
    print(f"    signal probe:  http://{host}:{cap['port']}/")
    print("  This laptop only:")
    print(f"    monitor:       http://127.0.0.1:{cap['port']}/monitor")
    print("Allow Python through the Windows firewall (private networks) if asked. Ctrl+C to stop.")
    uvicorn.run(create_app(config), host=cap["host"], port=cap["port"], log_level="info")


if __name__ == "__main__":
    main()
