"""Simpele 'eerste bot'-loop: zoek een template, tap erop, wacht, herhaal.

Dit is het minimale woodcutting-patroon (kap een boom, wacht, opnieuw). Exact
dezelfde loop werkt voor fishing, mining, enz. -- verwissel alleen de template.

Let op:
- Vision-based en dus fragiel: houd resolutie en orientatie stabiel, en knip je
  template uit een screenshot in exact die staat.
- Het automatiseren van een live game-account kan tegen de voorwaarden van de game
  ingaan en tot een ban leiden. Gebruik dit voor experimenteren op een wegwerp-account.

Gebruik (roep Python via het volledige pad aan i.v.m. de Windows-sandbox):
    python scripts/woodcutting.py templates/tree.png
    python scripts/woodcutting.py templates/tree.png --threshold 0.8 --min-wait 4 --max-wait 7
    python scripts/woodcutting.py templates/tree.png --max-actions 50

Stoppen: Ctrl+C.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from phonebot import adb, config, input as bot_input, screenshot, vision  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Tap een template herhaaldelijk (woodcutting-stijl).")
    p.add_argument("template", help="Pad naar de template-afbeelding, bv. templates/tree.png")
    p.add_argument("--threshold", type=float, default=config.DEFAULT_MATCH_THRESHOLD,
                   help=f"Match-drempel 0.0-1.0 (default {config.DEFAULT_MATCH_THRESHOLD})")
    p.add_argument("--min-wait", type=float, default=3.0,
                   help="Minimale wachttijd (s) na een tap, terwijl de actie loopt (default 3)")
    p.add_argument("--max-wait", type=float, default=6.0,
                   help="Maximale wachttijd (s) na een tap (default 6)")
    p.add_argument("--max-actions", type=int, default=0,
                   help="Stop na dit aantal taps (0 = oneindig, default)")
    p.add_argument("--max-misses", type=int, default=5,
                   help="Stop na dit aantal keer achter elkaar niets vinden (default 5)")
    return p.parse_args()


def grab_screen(serial: str | None = None):
    """Maak een screenshot en geef 'm terug als OpenCV-beeld."""
    return screenshot.screenshot_to_cv2(screenshot.capture_png(serial))


def jittered_point(match: vision.Match) -> tuple[int, int]:
    """Geef een licht willekeurig punt binnen de match, i.p.v. altijd exact het midden.

    Menselijker en robuuster: we mikken binnen de middelste helft van de match-box.
    """
    cx, cy = match.center
    dx = random.randint(-match.width // 4, match.width // 4)
    dy = random.randint(-match.height // 4, match.height // 4)
    return (cx + dx, cy + dy)


def main() -> int:
    args = parse_args()

    if args.min_wait > args.max_wait:
        print("ERROR: --min-wait mag niet groter zijn dan --max-wait.", file=sys.stderr)
        return 1

    template_path = Path(args.template)
    if not template_path.is_file():
        print(f"ERROR: template niet gevonden: {template_path}", file=sys.stderr)
        return 1

    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        print(f"ERROR: kon template niet als afbeelding lezen: {template_path}", file=sys.stderr)
        return 1

    try:
        serial = adb.require_device()
    except adb.AdbError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Start woodcutting-loop op {serial} met template '{template_path.name}' "
          f"(drempel {args.threshold:.2f}). Stop met Ctrl+C.")

    actions = 0
    misses = 0
    try:
        while True:
            try:
                screen = grab_screen(serial)
                match = vision.find_template(screen, template, threshold=args.threshold)
            except (adb.AdbError, ValueError) as exc:
                print(f"ERROR bij screenshot/match: {exc}", file=sys.stderr)
                return 1

            if match is None:
                misses += 1
                print(f"  geen match ({misses}/{args.max_misses}) -- opnieuw proberen...")
                if misses >= args.max_misses:
                    print("Gestopt: te vaak niets gevonden. "
                          "Check resolutie/orientatie/UI-state of de template.")
                    return 2
                time.sleep(random.uniform(1.0, 2.0))
                continue

            misses = 0
            x, y = jittered_point(match)
            actions += 1
            print(f"  [{actions}] match conf {match.confidence:.3f} -> tap ({x}, {y})")
            try:
                bot_input.tap(x, y, serial=serial)
            except adb.AdbError as exc:
                print(f"ERROR bij tap: {exc}", file=sys.stderr)
                return 1

            if args.max_actions and actions >= args.max_actions:
                print(f"Klaar: {actions} acties uitgevoerd (--max-actions bereikt).")
                return 0

            wait = random.uniform(args.min_wait, args.max_wait)
            print(f"      wacht {wait:.1f}s...")
            time.sleep(wait)
    except KeyboardInterrupt:
        print(f"\nGestopt door gebruiker na {actions} acties.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
