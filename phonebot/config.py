"""Central configuration for PhoneBot.

Keep this tiny and dependency-free so every other module can import it safely.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# Environment variable that lets you pin a specific ADB device/emulator serial.
# Example (PowerShell):  $env:PHONEBOT_ADB_SERIAL = "emulator-5554"
ENV_ADB_SERIAL = "PHONEBOT_ADB_SERIAL"

# Environment variable to point directly at an adb executable when it is not on PATH.
# Example (PowerShell):
#   $env:PHONEBOT_ADB_PATH = "C:\Users\you\AppData\Local\Android\Sdk\platform-tools\adb.exe"
ENV_ADB_PATH = "PHONEBOT_ADB_PATH"

# Default confidence for template matching (0.0 - 1.0).
DEFAULT_MATCH_THRESHOLD = 0.85

# Default timeout (seconds) for a single ADB subprocess call.
DEFAULT_ADB_TIMEOUT = 30


def default_serial() -> str | None:
    """Return the ADB serial from the environment, or None if unset/empty."""
    serial = os.environ.get(ENV_ADB_SERIAL, "").strip()
    return serial or None


def _candidate_adb_paths() -> list[Path]:
    """Common locations of adb.exe / adb, most specific first."""
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Android" / "Sdk" / "platform-tools" / "adb.exe")
    home = Path.home()
    candidates += [
        home / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        home / "Android" / "Sdk" / "platform-tools" / "adb.exe",  # Linux/macOS SDK
        home / "Library" / "Android" / "sdk" / "platform-tools" / "adb",  # macOS
    ]
    android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if android_home:
        candidates.insert(0, Path(android_home) / "platform-tools" / "adb.exe")
        candidates.insert(1, Path(android_home) / "platform-tools" / "adb")
    return candidates


def adb_executable() -> str:
    """Resolve the adb executable to use.

    Order: PHONEBOT_ADB_PATH env var, then 'adb' on PATH, then common SDK
    locations. Falls back to the bare name "adb" so the caller still gets a
    clear "not found" error if nothing resolves.
    """
    explicit = os.environ.get(ENV_ADB_PATH, "").strip()
    if explicit and Path(explicit).is_file():
        return explicit

    on_path = shutil.which("adb")
    if on_path:
        return on_path

    for candidate in _candidate_adb_paths():
        if candidate.is_file():
            return str(candidate)

    return "adb"
