"""Slimme woodcutting-loop: hak in vaste boom-vakken, drop als je inventory vol is.

Combineert alles wat we geleerd hebben:
  - BOOM = tap_region (vaste vakken op het scherm). Geen template-herkenning van
    bomen -- die wuiven en matchen niet. Sta stil met de camera van boven, dan
    staan de bomen altijd op dezelfde plek. Meerdere vakken = rotatie, dus als een
    boom even weg is pakt 'ie een ander.
  - LOGS tellen = template (inventory-iconen zijn wel betrouwbaar). Vol -> droppen.
  - DROPPEN = elke gevonden log aantikken (tap-to-drop AAN zetten in de game).
  - Menselijk: willekeurige tik-punten, wisselende wachttijden, af en toe een pauze.

Config (JSON), bv. chop_config.json:
    {
      "tree_regions": [[1100,330,1320,520], [1650,430,1900,620]],
      "inventory_region": [2116, 580, 2596, 1219],
      "log_template": "templates/willow_log.png",
      "full_count": 28,
      "threshold": 0.85,
      "chop_wait": [4.0, 7.0],
      "break_every": [40, 90],
      "break_time": [8.0, 30.0]
    }

Gebruik (Python via volledig pad i.v.m. Windows-sandbox):
    python scripts/chop.py chop_config.json
    python scripts/chop.py chop_config.json --log --max-chops 500

Coordinaten meet je makkelijk met de builder (sleep een tap_region en lees de box).
Stoppen: Ctrl+C.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from phonebot import adb, config, input as bot_input, recorder, screenshot, vision  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Slimme tree-chopper (tap_region + drop-when-full).")
    p.add_argument("config", help="Pad naar het JSON-config-bestand")
    p.add_argument("--max-chops", type=int, default=0, help="Stop na dit aantal hak-acties (0 = oneindig)")
    p.add_argument("--log", action="store_true", help="Run-logboek + roterende screenshots (outputs/debug/)")
    p.add_argument("--keep-frames", type=int, default=20, help="Aantal recente screenshots bij --log")
    return p.parse_args()


def rand_point(box: list[int], pad: int = 6) -> tuple[int, int]:
    """Willekeurig punt binnen een box [x1,y1,x2,y2], met marge."""
    x1, y1, x2, y2 = box
    left, right = sorted((int(x1), int(x2)))
    top, bottom = sorted((int(y1), int(y2)))
    if right - left > pad * 2:
        left, right = left + pad, right - pad
    if bottom - top > pad * 2:
        top, bottom = top + pad, bottom - pad
    return random.randint(left, right), random.randint(top, bottom)


def count_logs(screen, log_tmpl, region: list[int], threshold: float) -> int:
    x1, y1, x2, y2 = [int(v) for v in region]
    sub = screen[y1:y2, x1:x2]
    if sub.size == 0:
        return 0
    return len(vision.find_all_templates(sub, log_tmpl, threshold=threshold, max_results=40))


def drop_logs(log_tmpl, region: list[int], threshold: float, serial: str,
              rec: recorder.Recorder, drop_delay: tuple[float, float]) -> int:
    """Tik alle logs weg (tap-to-drop). Rescant tot de inventory leeg is."""
    x1, y1, x2, y2 = [int(v) for v in region]
    dropped = 0
    for _ in range(40):
        screen = screenshot.screenshot_to_cv2(screenshot.capture_png(serial))
        sub = screen[y1:y2, x1:x2]
        matches = vision.find_all_templates(sub, log_tmpl, threshold=threshold, max_results=40)
        rec.frame(screen, f"droppen: {len(matches)} logs over (al {dropped} gedropt)")
        if not matches:
            break
        for m in matches:
            cx, cy = m.center
            bot_input.tap(cx + x1, cy + y1, serial=serial)
            dropped += 1
            time.sleep(random.uniform(*drop_delay))
        time.sleep(random.uniform(0.3, 0.6))
    return dropped


def main() -> int:
    args = parse_args()
    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        print(f"ERROR: config niet gevonden: {cfg_path}", file=sys.stderr)
        return 1
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: ongeldige JSON: {exc}", file=sys.stderr)
        return 1

    tree_regions = cfg.get("tree_regions") or []
    inv_region = cfg.get("inventory_region")
    log_path = cfg.get("log_template")
    if not tree_regions or not inv_region or not log_path:
        print("ERROR: config mist tree_regions, inventory_region of log_template.", file=sys.stderr)
        return 1

    full_count = int(cfg.get("full_count", 28))
    threshold = float(cfg.get("threshold", config.DEFAULT_MATCH_THRESHOLD))
    chop_wait = tuple(cfg.get("chop_wait", [4.0, 7.0]))
    drop_delay = tuple(cfg.get("drop_delay", [0.15, 0.35]))
    break_every = tuple(cfg.get("break_every", [40, 90]))
    break_time = tuple(cfg.get("break_time", [8.0, 30.0]))

    log_tmpl_path = (Path(__file__).resolve().parent.parent / log_path)
    log_tmpl = cv2.imread(str(log_tmpl_path if log_tmpl_path.is_file() else log_path), cv2.IMREAD_COLOR)
    if log_tmpl is None:
        print(f"ERROR: kon log-template niet lezen: {log_path}", file=sys.stderr)
        return 1

    try:
        serial = adb.require_device()
    except adb.AdbError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    rec = recorder.Recorder("chop", keep_frames=args.keep_frames, enabled=args.log)
    if args.log and rec.dir is not None:
        print(f"Logboek: {rec.dir}")
    print(f"Chopper op {serial}: {len(tree_regions)} boom-vak(ken), vol = {full_count} logs. "
          "Stop met Ctrl+C.")

    chops = 0
    since_break = 0
    next_break = random.randint(int(break_every[0]), int(break_every[1]))
    last_count = -1
    stuck = 0
    try:
        while True:
            screen = screenshot.screenshot_to_cv2(screenshot.capture_png(serial))
            logs = count_logs(screen, log_tmpl, inv_region, threshold)

            # 1) vol? -> droppen
            if logs >= full_count:
                print(f"Inventory vol ({logs}) -> droppen...")
                n = drop_logs(log_tmpl, inv_region, threshold, serial, rec, drop_delay)
                print(f"  {n} logs gedropt.")
                last_count = 0
                continue

            # 2) anti-stuck: stijgt het aantal logs nog?
            if logs == last_count:
                stuck += 1
            else:
                stuck = 0
            last_count = logs
            if stuck and stuck % 8 == 0:
                rec.frame(screen, f"mogelijk vast: {logs} logs, {stuck} cycli geen groei")
                print(f"  (let op: {stuck} cycli geen nieuwe log -- boom weg of verplaatst?)")

            # 3) hak in een willekeurig boom-vak
            box = random.choice(tree_regions)
            x, y = rand_point(box)
            chops += 1
            since_break += 1
            print(f"  [{chops}] hak op ({x},{y})  logs={logs}")
            rec.frame(screen, f"[{chops}] hak ({x},{y}) logs={logs}")
            bot_input.tap(x, y, serial=serial)

            if args.max_chops and chops >= args.max_chops:
                print(f"Klaar: {chops} hak-acties (--max-chops).")
                return 0

            time.sleep(random.uniform(chop_wait[0], chop_wait[1]))

            # 4) af en toe een menselijke pauze
            if since_break >= next_break:
                pause = random.uniform(break_time[0], break_time[1])
                print(f"  -- pauze {pause:.0f}s --")
                rec.log(f"pauze {pause:.0f}s na {since_break} hakken")
                time.sleep(pause)
                since_break = 0
                next_break = random.randint(int(break_every[0]), int(break_every[1]))
    except KeyboardInterrupt:
        rec.log(f"Gestopt door gebruiker na {chops} hakken.")
        print(f"\nGestopt door gebruiker na {chops} hakken.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
