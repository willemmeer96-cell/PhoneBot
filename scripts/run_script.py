"""Voer een JSON-script van stappen uit tegen de emulator.

Scriptformaat (zie ook build_script.py die deze bestanden maakt):

    {
      "loop": true,
      "steps": [
        {"type": "tap", "x": 1544, "y": 620, "label": "chop"},
        {"type": "wait", "min": 3.0, "max": 6.0},
        {"type": "tap_region", "box": [100, 200, 300, 260], "mode": "random"},
        {"type": "tap_template", "template": "templates/x.png", "threshold": 0.85},
        {"type": "tap_template", "template": "templates/a.png",
         "templates": ["templates/b.png", "templates/c.png"], "threshold": 0.85},
        {"type": "swipe", "x1": 100, "y1": 200, "x2": 100, "y2": 800, "ms": 400}
      ]
    }

Stap-types:
  tap           x, y
  wait          min[, max]   (random tussen min en max seconden; max weglaten = vast)
  tap_region    box [x1,y1,x2,y2][, mode=random|center, padding]
                (tikt binnen een vaste veilige rechthoek, zonder beeldherkenning)
  swipe         x1, y1, x2, y2[, ms]
  tap_template  template[, templates, threshold]
                (zoekt een of meer alternatieve templates en tikt de beste match;
                 niet gevonden = overslaan)
  tap_all_template  template[, templates, threshold, region, delay, repeat, max_taps]
                (tikt ALLE treffers aan i.p.v. alleen de beste -> bv. "drop alles wat
                 op een log lijkt" met tap-to-drop aan. 'region' [x1,y1,x2,y2] beperkt
                 het zoeken tot bv. je inventory; 'repeat' scant opnieuw tot er niets
                 meer gevonden wordt; 'max_taps' is de veiligheidsrem)
  wait_template template[, threshold, timeout, poll, tap]
                (wacht tot het beeld verschijnt tot 'timeout' sec, tikt er dan op
                 tenzij tap=false -> "if gevonden tik, anders wacht tot het er is")
  if_template   template[, threshold], then: [...stappen...], else: [...stappen...]
                (gevonden -> then-stappen; niet gevonden -> else-stappen; mag genest)

Gebruik (Python via volledig pad i.v.m. Windows-sandbox):
    python scripts/run_script.py mijnscript.json
    python scripts/run_script.py mijnscript.json --max-loops 20

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
    p = argparse.ArgumentParser(description="Voer een JSON-stappenscript uit.")
    p.add_argument("script", help="Pad naar het .json-script")
    p.add_argument("--max-loops", type=int, default=0,
                   help="Stop na dit aantal keer de sequentie (0 = oneindig)")
    p.add_argument("--log", action="store_true",
                   help="Schrijf een run-logboek + roterende screenshots naar outputs/debug/")
    p.add_argument("--keep-frames", type=int, default=20,
                   help="Aantal recente screenshots dat bewaard blijft bij --log (default 20)")
    return p.parse_args()


def step_template_names(step: dict) -> list[str]:
    """Return primary + OR-template names for a step, without duplicates."""
    names: list[str] = []
    if step.get("template"):
        names.append(step["template"])
    for tmpl in step.get("templates", []) or []:
        if tmpl and tmpl not in names:
            names.append(tmpl)
    return names


def collect_template_names(steps: list[dict]):
    """Loop alle template-namen af, ook in geneste then/else-takken."""
    for step in steps:
        yield from step_template_names(step)
        for branch in ("then", "else"):
            if isinstance(step.get(branch), list):
                yield from collect_template_names(step[branch])


PROJECT_ROOT = Path(__file__).resolve().parent.parent  # phonebot-repo (bevat templates/)


def resolve_template(tmpl: str, base: Path) -> Path:
    """Vind een template-pad: absoluut, anders naast het script, anders in de project-root.

    Zo werkt een relatief pad als 'templates/x.png' ook als het script in outputs/ of
    ergens anders staat -- de templates zelf leven altijd in <project>/templates/.
    """
    p = Path(tmpl)
    if p.is_absolute():
        return p
    for cand in (base / tmpl, PROJECT_ROOT / tmpl):
        if cand.is_file():
            return cand
    return base / tmpl  # laat imread falen met een duidelijk pad


def load_templates(steps: list[dict], base: Path) -> dict[str, "cv2.Mat"]:
    """Laad alle template-afbeeldingen die de stappen gebruiken, vooraf."""
    cache: dict[str, "cv2.Mat"] = {}
    for tmpl in collect_template_names(steps):
        if tmpl in cache:
            continue
        path = resolve_template(tmpl, base)
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"kon template niet lezen: {path}")
        cache[tmpl] = img
    return cache


def _find_on_screen(step: dict, serial: str, templates: dict[str, "cv2.Mat"]):
    """Maak een screenshot en zoek primary/OR templates.

    Geeft (Match | None, screen, template_name | None). Als meerdere templates
    matchen, wint de hoogste confidence.
    """
    threshold = float(step.get("threshold", config.DEFAULT_MATCH_THRESHOLD))
    screen = screenshot.screenshot_to_cv2(screenshot.capture_png(serial))
    best = None
    best_name = None
    for name in step_template_names(step):
        match = vision.find_template(screen, templates[name], threshold=threshold)
        if match is not None and (best is None or match.confidence > best.confidence):
            best = match
            best_name = name
    return best, screen, best_name


def _find_all_in_region(screen, step: dict, templates: dict[str, "cv2.Mat"],
                        threshold: float) -> list[vision.Match]:
    """Vind ALLE matches van primary+OR templates, eventueel binnen 'region'.

    Coordinaten komen terug in volledige-scherm-ruimte. Treffers die elkaar
    overlappen (bv. twee OR-templates op hetzelfde slot) worden ontdubbeld.
    """
    region = step.get("region")
    if region:
        x1, y1, x2, y2 = [int(v) for v in region]
        left, right = sorted([x1, x2])
        top, bottom = sorted([y1, y2])
        sub = screen[top:bottom, left:right]
        off_x, off_y = left, top
    else:
        sub, off_x, off_y = screen, 0, 0
    if sub is None or sub.size == 0:
        return []

    found: list[vision.Match] = []
    for nm in step_template_names(step):
        for m in vision.find_all_templates(sub, templates[nm], threshold=threshold, max_results=40):
            found.append(vision.Match(x=m.x + off_x, y=m.y + off_y, width=m.width,
                                      height=m.height, confidence=m.confidence))

    found.sort(key=lambda m: m.confidence, reverse=True)
    kept: list[vision.Match] = []
    for m in found:
        if any(abs(m.x - k.x) < k.width * 0.5 and abs(m.y - k.y) < k.height * 0.5 for k in kept):
            continue
        kept.append(m)
    return kept


def run_step(step: dict, serial: str, templates: dict[str, "cv2.Mat"],
             rec: recorder.Recorder) -> None:
    kind = step.get("type")
    name = Path(step["template"]).name if step.get("template") else ""
    if kind == "tap":
        bot_input.tap(step["x"], step["y"], serial=serial)
    elif kind == "tap_region":
        x1, y1, x2, y2 = [int(v) for v in step["box"]]
        left, right = sorted([x1, x2])
        top, bottom = sorted([y1, y2])
        padding = max(0, int(step.get("padding", 4)))
        if right - left > padding * 2:
            left += padding
            right -= padding
        if bottom - top > padding * 2:
            top += padding
            bottom -= padding
        if str(step.get("mode", "random")).lower() == "center":
            x = (left + right) // 2
            y = (top + bottom) // 2
        else:
            x = random.randint(left, right)
            y = random.randint(top, bottom)
        print(f"      (tap_region -> {x},{y})")
        bot_input.tap(x, y, serial=serial)
    elif kind == "wait":
        lo = float(step.get("min", 1.0))
        hi = float(step.get("max", lo))
        time.sleep(random.uniform(min(lo, hi), max(lo, hi)))
    elif kind == "swipe":
        bot_input.swipe(step["x1"], step["y1"], step["x2"], step["y2"],
                        duration_ms=int(step.get("ms", 300)), serial=serial)
    elif kind == "tap_template":
        match, screen, matched_name = _find_on_screen(step, serial, templates)
        hit = Path(matched_name).name if matched_name else name
        rec.frame(screen, f"tap_template {hit} {'gevonden' if match else 'niet gevonden'}")
        if match is None:
            print(f"      (template(s) '{step_template_names(step)}' niet gevonden -> overslaan)")
        else:
            print(f"      (match '{matched_name}' conf {match.confidence:.3f})")
            bot_input.tap(*match.center, serial=serial)
    elif kind == "tap_all_template":
        # Tik ALLE treffers aan (bv. alle logs weg-droppen met tap-to-drop).
        threshold = float(step.get("threshold", config.DEFAULT_MATCH_THRESHOLD))
        delay = float(step.get("delay", 0.25))
        repeat = bool(step.get("repeat", True))
        max_taps = int(step.get("max_taps", 40))
        total = 0
        for _round in range(20 if repeat else 1):
            screen = screenshot.screenshot_to_cv2(screenshot.capture_png(serial))
            matches = _find_all_in_region(screen, step, templates, threshold)
            rec.frame(screen, f"tap_all {name}: {len(matches)} gevonden (totaal {total})")
            if not matches:
                break
            for m in matches:
                if total >= max_taps:
                    break
                bot_input.tap(*m.center, serial=serial)
                total += 1
                time.sleep(delay)
            if not repeat or total >= max_taps:
                break
            time.sleep(0.4)  # scherm laten bijwerken voor de her-scan
        print(f"      (tap_all_template -> {total} getikt)")
    elif kind == "wait_template":
        # Wacht tot het beeld verschijnt (tot timeout); tik er dan op (tenzij tap=false).
        timeout = float(step.get("timeout", 10.0))
        poll = float(step.get("poll", 0.5))
        do_tap = bool(step.get("tap", True))
        deadline = time.monotonic() + timeout
        while True:
            match, screen, matched_name = _find_on_screen(step, serial, templates)
            if match is not None:
                hit = Path(matched_name).name if matched_name else name
                rec.frame(screen, f"wait_template {hit} verschenen")
                print(f"      (match '{matched_name}' conf {match.confidence:.3f})")
                if do_tap:
                    bot_input.tap(*match.center, serial=serial)
                return
            if time.monotonic() >= deadline:
                rec.frame(screen, f"wait_template {name} TIMEOUT na {timeout}s")
                print(f"      (wait_template '{step['template']}' timeout na {timeout}s)")
                return
            time.sleep(poll)
    elif kind == "if_template":
        # if gevonden -> 'then'-stappen, anders -> 'else'-stappen.
        match, screen, matched_name = _find_on_screen(step, serial, templates)
        branch = step.get("then") if match is not None else step.get("else")
        found = f"{matched_name} gevonden -> then" if match is not None else "niet gevonden -> else"
        rec.frame(screen, f"if {name} {found}")
        print(f"      (if_template '{step['template']}' {found})")
        if isinstance(branch, list):
            run_steps(branch, serial, templates, rec, indent="        ")
    else:
        print(f"      (onbekend stap-type '{kind}' -> overslaan)")


def run_steps(steps: list[dict], serial: str, templates: dict[str, "cv2.Mat"],
              rec: recorder.Recorder, indent: str = "  ") -> None:
    for i, step in enumerate(steps, 1):
        desc = describe(step)
        print(f"{indent}[{i}] {desc}")
        rec.log(f"{indent.strip()}[{i}] {desc}")
        run_step(step, serial, templates, rec)


def describe(step: dict) -> str:
    kind = step.get("type", "?")
    label = f" [{step['label']}]" if step.get("label") else ""
    if kind == "tap":
        return f"tap ({step['x']},{step['y']}){label}"
    if kind == "tap_region":
        return f"tap_region {step.get('box')} mode={step.get('mode', 'random')}{label}"
    if kind == "wait":
        return f"wait {step.get('min')}..{step.get('max', step.get('min'))}s"
    if kind == "swipe":
        return f"swipe ({step['x1']},{step['y1']})->({step['x2']},{step['y2']})"
    if kind == "tap_template":
        extra = len(step.get("templates", []) or [])
        suffix = f" +{extra} OR" if extra else ""
        return f"tap_template {step.get('template')}{suffix}{label}"
    if kind == "tap_all_template":
        extra = len(step.get("templates", []) or [])
        suffix = f" +{extra} OR" if extra else ""
        where = " in region" if step.get("region") else ""
        return f"tap_all_template {step.get('template')}{suffix}{where}{label}"
    if kind == "wait_template":
        extra = len(step.get("templates", []) or [])
        suffix = f" +{extra} OR" if extra else ""
        return (f"wait_template {step.get('template')} "
                f"(timeout {step.get('timeout', 10)}s, tap={step.get('tap', True)}){suffix}")
    if kind == "if_template":
        n_then = len(step.get("then", []) or [])
        n_else = len(step.get("else", []) or [])
        extra = len(step.get("templates", []) or [])
        suffix = f" +{extra} OR" if extra else ""
        return f"if_template {step.get('template')}{suffix} (then {n_then}, else {n_else})"
    return kind


def main() -> int:
    args = parse_args()
    script_path = Path(args.script)
    if not script_path.is_file():
        print(f"ERROR: script niet gevonden: {script_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(script_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: ongeldige JSON: {exc}", file=sys.stderr)
        return 1

    steps = data.get("steps", [])
    if not steps:
        print("ERROR: script heeft geen 'steps'.", file=sys.stderr)
        return 1
    loop = bool(data.get("loop", False))

    try:
        templates = load_templates(steps, script_path.parent)
        serial = adb.require_device()
    except (ValueError, adb.AdbError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    rec = recorder.Recorder(f"script_{script_path.stem}", keep_frames=args.keep_frames,
                            enabled=args.log)
    if args.log and rec.dir is not None:
        print(f"Logboek: {rec.dir}")

    print(f"Script '{script_path.name}' op {serial}: {len(steps)} stappen, "
          f"loop={'aan' if loop else 'uit'}. Stop met Ctrl+C.")

    loops = 0
    try:
        while True:
            loops += 1
            print(f"--- ronde {loops} ---")
            rec.log(f"--- ronde {loops} ---")
            try:
                run_steps(steps, serial, templates, rec)
            except (adb.AdbError, ValueError, KeyError) as exc:
                rec.log(f"ERROR: {exc}")
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            if not loop:
                rec.log("Klaar (geen loop).")
                print("Klaar (geen loop).")
                return 0
            if args.max_loops and loops >= args.max_loops:
                rec.log(f"Klaar: {loops} rondes (--max-loops).")
                print(f"Klaar: {loops} rondes (--max-loops bereikt).")
                return 0
    except KeyboardInterrupt:
        rec.log(f"Gestopt door gebruiker na {loops} ronde(s).")
        print(f"\nGestopt door gebruiker na {loops} ronde(s).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
