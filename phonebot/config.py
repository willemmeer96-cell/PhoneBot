"""Central configuration for PhoneBot.

Keep this tiny and dependency-free so every other module can import it safely.
"""

from __future__ import annotations

import os

# Environment variable that lets you pin a specific ADB device/emulator serial.
# Example (PowerShell):  $env:PHONEBOT_ADB_SERIAL = "emulator-5554"
ENV_ADB_SERIAL = "PHONEBOT_ADB_SERIAL"

# Default confidence for template matching (0.0 - 1.0).
DEFAULT_MATCH_THRESHOLD = 0.85

# Default timeout (seconds) for a single ADB subprocess call.
DEFAULT_ADB_TIMEOUT = 30


def default_serial() -> str | None:
    """Return the ADB serial from the environment, or None if unset/empty."""
    serial = os.environ.get(ENV_ADB_SERIAL, "").strip()
    return serial or None
