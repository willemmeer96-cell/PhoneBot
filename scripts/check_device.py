"""Print available ADB devices and fail clearly if nothing is connected.

Usage:
    python scripts/check_device.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running this script directly without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phonebot import adb  # noqa: E402


def main() -> int:
    try:
        devices = adb.list_devices()
    except adb.AdbError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not devices:
        print(
            "No devices/emulators found.\n"
            "Start an Android emulator and verify with 'adb devices'.",
            file=sys.stderr,
        )
        return 1

    print("Connected devices:")
    for d in devices:
        marker = "ready" if d.is_ready else d.state
        print(f"  - {d.serial}  [{marker}]")

    if not any(d.is_ready for d in devices):
        print(
            "\nNo device is in the 'ready' state. "
            "Unlock/authorize the device or restart the emulator.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
