"""Slimmere woodcutting-loop: chop -> bij volle inventory de logs droppen -> door.

Boom aantikken kan op drie manieren (kies er een):
  --marker KLEUR  : detecteer een gekleurde tile-marker (magenta/cyan/white) en tik
                    daarop. MEEST ROBUUST: tikt alleen als de marker gevonden is, dus
                    geen blinde tik op lege grond -> geen gewandel. Markeer de
                    boom-tegel in de game met die kleur (niet groen: te dicht bij gras).
  --tree-xy X,Y   : vaste tik-coordinaat. Robuust bij wuivende bomen, maar breekt als
                    je personage wegloopt of de camera draait.
  --tree TREE.png : template van de boom (werkt matig: boomkronen wuiven).
En altijd:
  --log LOG.png   : een enkel log-icoon uit je inventory (om te tellen + te droppen)

Vereist dat 'tap to drop' AAN staat in de game (Settings), zodat een log droppen
gewoon een tik op de log is. Staat het uit, zet het aan -- of we gaan terug naar
het long-press-menu (input.long_press bestaat daarvoor nog).

Werking per cyclus:
  1. tel de logs in je inventory (via de log-template)
  2. is de inventory vol (>= --full logs)? dan drop-fase: tik elke gevonden log weg,
     opnieuw scannen tot leeg
  3. anders: zoek de boom en tik erop; wacht terwijl je chopt

Let op:
- Houd resolutie en orientatie stabiel; knip templates in exact die staat.
- Automatiseren van een live game-account kan tegen de voorwaarden ingaan en tot een
  ban leiden. Gebruik dit op een wegwerp-account.

Gebruik (Python via volledig pad i.v.m. Windows-sandbox):
    python scripts/powerchop.py --tree templates/tree.png --log templates/log.png
    python scripts/powerchop.py --tree ... --log ... --full 27 --min-wait 3 --max-wait 6

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

# HSV-kleurbereiken (OpenCV: H 0-179) voor felle, on-natuurlijke tile-markers.
# (lower_hsv, upper_hsv, min_area). Groen bewust weggelaten: te dicht bij gras/boom.
MARKER_PRESETS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], int]] = {
    "magenta": ((140, 80, 80), (175, 255, 255), 300),
    "cyan": ((85, 80, 80), (105, 255, 255), 300),
    "white": ((0, 0, 210), (179, 40, 255), 300),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Power-chop: chop en drop bij volle inventory.")
    p.add_argument("--tree", help="Template van de boom (om te choppen)")
    p.add_argument("--tree-xy", metavar="X,Y",
                   help="Vaste tik-coordinaat i.p.v. template, bv. 1560,615 "
                        "(robuust bij wuivende bomen; sta wel stil naast de boom)")
    p.add_argument("--marker", choices=sorted(MARKER_PRESETS),
                   help="Detecteer een gekleurde tile-marker en tik daarop. "
                        "ROBUUST: tikt alleen als de marker gevonden is (geen gewandel). "
                        "Markeer de boom-tegel in de game met deze kleur.")
    p.add_argument("--log", required=True, help="Template van een enkel log-icoon in de inventory")
    p.add_argument("--threshold", type=float, default=config.DEFAULT_MATCH_THRESHOLD,
                   help=f"Match-drempel 0.0-1.0 (default {config.DEFAULT_MATCH_THRESHOLD})")
    p.add_argument("--full", type=int, default=27,
                   help="Aantal logs waarbij de inventory als vol geldt (default 27)")
    p.add_argument("--min-wait", type=float, default=3.0, help="Min. chop-wachttijd (s)")
    p.add_argument("--max-wait", type=float, default=6.0, help="Max. chop-wachttijd (s)")
    p.add_argument("--max-cycles", type=int, default=0,
                   help="Stop na dit aantal chop-cycli (0 = oneindig)")
    p.add_argument("--max-misses", type=int, default=6,
                   help="Stop na zoveel keer achter elkaar geen boom vinden (default 6)")
    return p.parse_args()


def load_template(path_str: str) -> cv2.Mat:
    path = Path(path_str)
    if not path.is_file():
        raise FileNotFoundError(f"template niet gevonden: {path}")
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"kon template niet als afbeelding lezen: {path}")
    return img


def grab(serial: str | None):
    return screenshot.screenshot_to_cv2(screenshot.capture_png(serial))


def drop_inventory(log_tmpl, threshold: float, serial: str | None) -> int:
    """Tik elke gevonden log weg (tap-to-drop). Geeft het aantal gedropte logs terug.

    We scannen opnieuw na elke ronde omdat de inventory verandert; klaar zodra er
    geen logs meer gevonden worden.
    """
    dropped = 0
    # Ruime bovengrens zodat een vastlopende drop niet oneindig doorgaat.
    for _ in range(40):
        screen = grab(serial)
        logs = vision.find_all_templates(screen, log_tmpl, threshold=threshold, max_results=40)
        if not logs:
            break
        for log in logs:
            bot_input.tap(*log.center, serial=serial)
            dropped += 1
            time.sleep(random.uniform(0.15, 0.35))  # klein tikje tussen drops
        time.sleep(random.uniform(0.3, 0.6))  # scherm laten bijwerken, dan opnieuw scannen
    print(f"      {dropped} logs gedropt.")
    return dropped


def main() -> int:
    args = parse_args()
    if args.min_wait > args.max_wait:
        print("ERROR: --min-wait mag niet groter zijn dan --max-wait.", file=sys.stderr)
        return 1

    if sum(bool(x) for x in (args.tree, args.tree_xy, args.marker)) != 1:
        print("ERROR: geef precies EEN van --tree, --tree-xy of --marker op.", file=sys.stderr)
        return 1

    tree_xy: tuple[int, int] | None = None
    if args.tree_xy:
        try:
            xs, ys = args.tree_xy.split(",")
            tree_xy = (int(xs), int(ys))
        except ValueError:
            print("ERROR: --tree-xy moet 'x,y' zijn, bv. 1560,615", file=sys.stderr)
            return 1

    try:
        tree_tmpl = load_template(args.tree) if args.tree else None
        log_tmpl = load_template(args.log)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        serial = adb.require_device()
    except adb.AdbError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Power-chop op {serial}. Vol = {args.full} logs. Stop met Ctrl+C.")

    cycles = 0
    misses = 0
    try:
        while True:
            try:
                screen = grab(serial)
            except (adb.AdbError, ValueError) as exc:
                print(f"ERROR bij screenshot: {exc}", file=sys.stderr)
                return 1

            # 1) inventory vol? eerst droppen.
            logs = vision.find_all_templates(screen, log_tmpl, threshold=args.threshold, max_results=40)
            if len(logs) >= args.full:
                print(f"Inventory vol ({len(logs)} logs) -> droppen...")
                drop_inventory(log_tmpl, args.threshold, serial)
                continue

            # 2) boom choppen: marker-kleur, vaste coordinaat, of template.
            if args.marker is not None:
                lower, upper, min_area = MARKER_PRESETS[args.marker]
                blobs = vision.find_color_blobs(screen, lower, upper, min_area=min_area)
                if not blobs:
                    misses += 1
                    print(f"  marker '{args.marker}' niet gevonden ({misses}/{args.max_misses})...")
                    if misses >= args.max_misses:
                        print("Gestopt: marker te vaak niet gevonden. "
                              "Check de kleur/opacity van je tile-marker.")
                        return 2
                    time.sleep(random.uniform(1.0, 2.0))
                    continue
                misses = 0
                cycles += 1
                marker = blobs[0]  # grootste blob
                print(f"  [{cycles}] marker op {marker.center} (logs nu: {len(logs)})")
                bot_input.tap(*marker.center, serial=serial)
            elif tree_xy is not None:
                cycles += 1
                print(f"  [{cycles}] tik boom op {tree_xy} (logs nu: {len(logs)})")
                bot_input.tap(*tree_xy, serial=serial)
            else:
                trees = vision.find_all_templates(
                    screen, tree_tmpl, threshold=args.threshold, max_results=20
                )
                if not trees:
                    misses += 1
                    print(f"  geen boom ({misses}/{args.max_misses})...")
                    if misses >= args.max_misses:
                        print("Gestopt: te vaak geen boom gevonden.")
                        return 2
                    time.sleep(random.uniform(1.0, 2.0))
                    continue

                misses = 0
                cycles += 1
                tree = trees[0]  # hoogste confidence = de boom waar je naast staat
                print(f"  [{cycles}] {len(trees)} match(es) -> chop beste conf {tree.confidence:.3f} "
                      f"(logs nu: {len(logs)})")
                bot_input.tap(*tree.center, serial=serial)

            if args.max_cycles and cycles >= args.max_cycles:
                print(f"Klaar: {cycles} cycli (--max-cycles bereikt).")
                return 0

            time.sleep(random.uniform(args.min_wait, args.max_wait))
    except KeyboardInterrupt:
        print(f"\nGestopt door gebruiker na {cycles} chop-cycli.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
