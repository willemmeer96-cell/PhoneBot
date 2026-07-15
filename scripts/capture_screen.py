"""Capture a screenshot and save it to outputs/screenshot.png.

Usage:
    python scripts/capture_screen.py [optional/output/path.png]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phonebot import adb, screenshot  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "screenshot.png"


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT

    try:
        saved = screenshot.save_screenshot(out_path)
    except adb.AdbError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Screenshot saved to: {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
