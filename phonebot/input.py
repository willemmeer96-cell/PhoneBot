"""Send taps and swipes to an Android device via ADB `input`."""

from __future__ import annotations

from . import adb


def tap(x: int, y: int, serial: str | None = None) -> None:
    """Tap the screen at pixel coordinate (x, y)."""
    device = adb.require_device(serial)
    adb.run_adb(["shell", "input", "tap", str(int(x)), str(int(y))], serial=device)


def swipe(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int = 300,
    serial: str | None = None,
) -> None:
    """Swipe from (x1, y1) to (x2, y2) over `duration_ms` milliseconds."""
    device = adb.require_device(serial)
    adb.run_adb(
        [
            "shell",
            "input",
            "swipe",
            str(int(x1)),
            str(int(y1)),
            str(int(x2)),
            str(int(y2)),
            str(int(duration_ms)),
        ],
        serial=device,
    )
