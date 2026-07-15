"""Find a template on the current screen and tap its center when confident.

Usage:
    python scripts/tap_template.py templates/example.png [threshold]

Exit codes:
    0  template found and tapped
    1  error (no device, missing file, decode failure, ...)
    2  template not found above the threshold
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from phonebot import adb, config, input as bot_input, screenshot, vision  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/tap_template.py <template.png> [threshold]", file=sys.stderr)
        return 1

    template_path = Path(sys.argv[1])
    threshold = config.DEFAULT_MATCH_THRESHOLD
    if len(sys.argv) > 2:
        try:
            threshold = float(sys.argv[2])
        except ValueError:
            print(f"ERROR: threshold must be a number, got '{sys.argv[2]}'.", file=sys.stderr)
            return 1

    if not template_path.is_file():
        print(f"ERROR: template not found: {template_path}", file=sys.stderr)
        return 1

    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        print(f"ERROR: could not read template as an image: {template_path}", file=sys.stderr)
        return 1

    try:
        screen = screenshot.screenshot_to_cv2(screenshot.capture_png())
    except (adb.AdbError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        match = vision.find_template(screen, template, threshold=threshold)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if match is None:
        print(
            f"Template not found (below threshold {threshold:.2f}). "
            "Check resolution, scale and UI state.",
            file=sys.stderr,
        )
        return 2

    cx, cy = match.center
    print(f"Match at ({match.x}, {match.y}) size {match.width}x{match.height} "
          f"confidence {match.confidence:.3f} -> tapping center ({cx}, {cy})")

    try:
        bot_input.tap(cx, cy)
    except adb.AdbError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Tap sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
