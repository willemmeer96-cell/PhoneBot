"""Thin wrapper around the ADB command-line tool using subprocess.

No game logic here: this module only knows how to talk to ADB.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from . import config


class AdbError(RuntimeError):
    """Raised when an ADB command fails or no usable device is available."""


@dataclass(frozen=True)
class Device:
    """A single ADB device entry."""

    serial: str
    state: str  # e.g. "device", "offline", "unauthorized"

    @property
    def is_ready(self) -> bool:
        return self.state == "device"


def run_adb(
    args: list[str],
    serial: str | None = None,
    timeout: int = config.DEFAULT_ADB_TIMEOUT,
) -> bytes:
    """Run an ADB command and return raw stdout bytes.

    Args:
        args: ADB sub-command and its arguments, e.g. ["shell", "input", "tap", "1", "2"].
        serial: Optional device serial. Falls back to PHONEBOT_ADB_SERIAL when None.
        timeout: Seconds before the call is aborted.

    Raises:
        AdbError: If adb is not installed, times out, or returns a non-zero exit code.
    """
    resolved = serial or config.default_serial()
    cmd = ["adb"]
    if resolved:
        cmd += ["-s", resolved]
    cmd += args

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AdbError(
            "ADB not found. Install Android platform-tools and make sure 'adb' is on your PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"ADB command timed out after {timeout}s: {' '.join(cmd)}") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.decode(errors="replace").strip()
        raise AdbError(
            f"ADB command failed (exit {completed.returncode}): {' '.join(cmd)}\n{stderr}"
        )

    return completed.stdout


def list_devices() -> list[Device]:
    """Return all devices reported by `adb devices` (any state)."""
    output = run_adb(["devices"]).decode(errors="replace")
    devices: list[Device] = []
    # First line is the "List of devices attached" header; skip it.
    for line in output.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append(Device(serial=parts[0], state=parts[1]))
    return devices


def require_device(serial: str | None = None) -> str:
    """Return a usable device serial or raise a clear error.

    If `serial` (or PHONEBOT_ADB_SERIAL) is given, verify it is present and ready.
    Otherwise auto-select when exactly one ready device exists.
    """
    resolved = serial or config.default_serial()
    devices = list_devices()
    ready = [d for d in devices if d.is_ready]

    if resolved:
        for d in devices:
            if d.serial == resolved:
                if d.is_ready:
                    return d.serial
                raise AdbError(
                    f"Device '{resolved}' is present but not ready (state: {d.state})."
                )
        raise AdbError(
            f"Requested device '{resolved}' not found. Connected: "
            f"{[d.serial for d in devices] or 'none'}"
        )

    if not ready:
        if devices:
            raise AdbError(
                "No ready device. Connected but not usable: "
                + ", ".join(f"{d.serial} ({d.state})" for d in devices)
            )
        raise AdbError(
            "No devices/emulators connected. Start an emulator and check 'adb devices'."
        )

    if len(ready) > 1:
        raise AdbError(
            "Multiple ready devices found: "
            + ", ".join(d.serial for d in ready)
            + f". Set {config.ENV_ADB_SERIAL} or pass a serial to pick one."
        )

    return ready[0].serial
