"""Capture screenshots from an Android device via ADB and decode them for OpenCV."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from . import adb


def capture_png(serial: str | None = None) -> bytes:
    """Capture the current screen as raw PNG bytes.

    Uses `adb exec-out screencap -p`, which streams PNG data directly to stdout
    without touching the device filesystem.
    """
    device = adb.require_device(serial)
    return adb.run_adb(["exec-out", "screencap", "-p"], serial=device)


def save_screenshot(path: str | Path, serial: str | None = None) -> Path:
    """Capture a screenshot and write it to `path`. Returns the written path."""
    out = Path(path)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    data = capture_png(serial)
    out.write_bytes(data)
    return out


def screenshot_to_cv2(image_bytes: bytes) -> np.ndarray:
    """Decode PNG bytes into a BGR OpenCV image array.

    Raises:
        ValueError: If the bytes could not be decoded as an image.
    """
    buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode screenshot bytes as an image.")
    return image
