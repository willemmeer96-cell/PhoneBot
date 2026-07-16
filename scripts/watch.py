"""Reactieve watcher: kijk continu of een template op het scherm verschijnt en tik erop.

Ideaal voor STATISCHE UI (waar vision betrouwbaar is): auto-continue dialogen,
level-up-vensters wegklikken, een knop indrukken zodra die verschijnt, enz.

Je geeft een of meer templates op met --watch. Elke cyclus wordt het scherm
gescand; verschijnt een template, dan tikt de bot op het midden ervan. Een cooldown
voorkomt dat hetzelfde ding meerdere keren snel achter elkaar wordt aangetikt.

Gebruik (Python via volledig pad i.v.m. Windows-sandbox):
    python scripts/watch.py --watch templates/continue.png
    python scripts/watch.py --watch continue.png --watch levelup.png --cooldown 3
    python scripts/watch.py --watch dialog.png --once          # wacht, tik 1x, stop

Stoppen: Ctrl+C.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from phonebot import adb, config, input as bot_input, recorder, screenshot, vision  # noqa: E402


class Watch:
    """Een te bewaken template met z'n eigen laatste-trigger-tijd."""

    def __init__(self, path: Path, image) -> None:
        self.path = path
        self.image = image
        self.last_trigger = 0.0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Kijk of templates verschijnen en tik erop.")
    p.add_argument("--watch", action="append", required=True, metavar="TEMPLATE.png",
                   help="Template om te bewaken (meerdere keren te gebruiken)")
    p.add_argument("--threshold", type=float, default=config.DEFAULT_MATCH_THRESHOLD,
                   help=f"Match-drempel 0.0-1.0 (default {config.DEFAULT_MATCH_THRESHOLD})")
    p.add_argument("--interval", type=float, default=1.0,
                   help="Seconden tussen scans (default 1.0)")
    p.add_argument("--cooldown", type=float, default=3.0,
                   help="Min. seconden voordat DEZELFDE template opnieuw mag triggeren (default 3)")
    p.add_argument("--once", action="store_true",
                   help="Stop na de eerste succesvolle tik (wacht-tot-X-en-klik)")
    p.add_argument("--max-triggers", type=int, default=0,
                   help="Stop na dit aantal tikken totaal (0 = oneindig)")
    p.add_argument("--log", action="store_true",
                   help="Schrijf een run-logboek + roterende screenshots naar outputs/debug/")
    p.add_argument("--keep-frames", type=int, default=20,
                   help="Aantal recente screenshots bij --log (default 20)")
    return p.parse_args()


def load_watches(paths: list[str]) -> list[Watch]:
    watches: list[Watch] = []
    for pstr in paths:
        path = Path(pstr)
        if not path.is_file():
            raise FileNotFoundError(f"template niet gevonden: {path}")
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"kon template niet als afbeelding lezen: {path}")
        watches.append(Watch(path, img))
    return watches


def main() -> int:
    args = parse_args()

    try:
        watches = load_watches(args.watch)
        serial = adb.require_device()
    except (FileNotFoundError, ValueError, adb.AdbError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    rec = recorder.Recorder("watch", keep_frames=args.keep_frames, enabled=args.log)
    if args.log and rec.dir is not None:
        print(f"Logboek: {rec.dir}")

    names = ", ".join(w.path.name for w in watches)
    print(f"Watcher op {serial}. Bewaakt: {names}. Stop met Ctrl+C.")

    triggers = 0
    try:
        while True:
            try:
                screen = screenshot.screenshot_to_cv2(screenshot.capture_png(serial))
            except (adb.AdbError, ValueError) as exc:
                print(f"ERROR bij screenshot: {exc}", file=sys.stderr)
                return 1

            now = time.monotonic()
            for w in watches:
                if now - w.last_trigger < args.cooldown:
                    continue
                try:
                    match = vision.find_template(screen, w.image, threshold=args.threshold)
                except ValueError as exc:
                    print(f"ERROR ({w.path.name}): {exc}", file=sys.stderr)
                    return 1
                if match is None:
                    continue

                w.last_trigger = now
                triggers += 1
                cx, cy = match.center
                msg = (f"[{triggers}] '{w.path.name}' verschenen (conf {match.confidence:.3f}) "
                       f"-> tik ({cx}, {cy})")
                print(f"  {msg}")
                rec.frame(screen, msg)
                bot_input.tap(cx, cy, serial=serial)

                if args.once:
                    rec.log("Klaar: eerste tik gedaan (--once).")
                    print("Klaar: eerste tik gedaan (--once).")
                    return 0
                if args.max_triggers and triggers >= args.max_triggers:
                    rec.log(f"Klaar: {triggers} tikken (--max-triggers).")
                    print(f"Klaar: {triggers} tikken (--max-triggers bereikt).")
                    return 0

            time.sleep(args.interval)
    except KeyboardInterrupt:
        rec.log(f"Gestopt door gebruiker na {triggers} tikken.")
        print(f"\nGestopt door gebruiker na {triggers} tikken.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
