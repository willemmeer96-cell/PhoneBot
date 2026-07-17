"""Visuele script-builder: prik tap-punten, regio's en if-condities op een screenshot.

Toont een screenshot van de emulator. Daarmee bouw je een stappen-script (zoals
GnomeBot), inclusief condities:

  - KLIK op het beeld          -> 'tap' op dat punt
  - SLEEP een rechthoek        -> knipt een template en maakt (zie radio) een
                                  'tap_template' of 'wait_template' stap
  - knop 'If-conditie'         -> volgende sleep wordt de conditie; daarna kies je
                                  met de radio of nieuwe stappen in de THEN- of
                                  ELSE-tak van die if komen
  - knop 'Wacht'               -> 'wait' (random tussen min/max)
  - Verwijder / Ververs        -> stap wissen / nieuwe screenshot
  - 'Loop' / 'Opslaan' / 'Draai'

Coordinaten worden op device-resolutie opgeslagen (schaal-onafhankelijk).

Gebruik (Python via volledig pad i.v.m. Windows-sandbox):
    python scripts/build_script.py
"""

from __future__ import annotations

import json
import os
import copy
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from phonebot import adb, config, screenshot, vision  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
OUTPUTS = ROOT / "outputs"
RUN_SCRIPT = Path(__file__).resolve().parent / "run_script.py"
SUB = 2  # screenshot op halve grootte tonen (device = canvas * SUB)


def step_template_names(step: dict) -> list[str]:
    names: list[str] = []
    if step.get("template"):
        names.append(step["template"])
    for tmpl in step.get("templates", []) or []:
        if tmpl and tmpl not in names:
            names.append(tmpl)
    return names


def or_suffix(step: dict) -> str:
    extra = len(step.get("templates", []) or [])
    return f" +{extra} OR" if extra else ""


def describe(step: dict) -> str:
    t = step["type"]
    label = f" [{step['label']}]" if step.get("label") else ""
    if t == "tap":
        return f"tap ({step['x']},{step['y']}){label}"
    if t == "tap_region":
        x1, y1, x2, y2 = step["box"]
        return f"tap_region ({x1},{y1})-({x2},{y2}) mode={step.get('mode', 'random')}{label}"
    if t == "wait":
        return f"wait {step['min']}..{step['max']}s{label}"
    if t == "tap_template":
        return f"tap_template {Path(step['template']).name}{or_suffix(step)} @ {step.get('threshold', 0.85)}{label}"
    if t == "tap_all_template":
        where = " in zoekgebied" if step.get("region") else " (heel scherm)"
        return (f"tap_all {Path(step['template']).name}{or_suffix(step)} "
                f"@ {step.get('threshold', 0.85)}{where}{label}")
    if t == "wait_template":
        return (
            f"wait_template {Path(step['template']).name}{or_suffix(step)} @ {step.get('threshold', 0.85)} "
            f"(max {step.get('timeout', 10)}s, tap={step.get('tap', True)}){label}"
        )
    if t == "if_template":
        return f"if {Path(step['template']).name}{or_suffix(step)}? @ {step.get('threshold', 0.85)}{label}"
    if t == "swipe":
        return f"swipe ({step['x1']},{step['y1']})->({step['x2']},{step['y2']}){label}"
    return f"{t}{label}"


class Builder:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("PhoneBot script builder")
        self.steps: list[dict] = []
        self.full = None
        self.photo: tk.PhotoImage | None = None
        self.drag_start: tuple[int, int] | None = None
        self.pending_if = False
        self.pending_or_step: dict | None = None
        self.pending_region_step: dict | None = None
        self.active_if: int | None = None          # index in self.steps van de actieve if
        self.rows: list[tuple] = []                 # (container, index, depth, top_index)

        try:
            self.serial = adb.require_device()
        except adb.AdbError as exc:
            messagebox.showerror("Geen device", str(exc))
            root.destroy()
            return

        self.canvas = tk.Canvas(root, bg="black", cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        side = tk.Frame(root, padx=8, pady=8)
        side.grid(row=0, column=1, sticky="ns")

        tk.Label(side, text="Stappen").pack(anchor="w")
        list_frame = tk.Frame(side)
        list_frame.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(list_frame, width=46, height=22)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        self.loop_var = tk.BooleanVar(value=True)
        tk.Checkbutton(side, text="Loop (herhaal sequentie)", variable=self.loop_var).pack(anchor="w", pady=(6, 2))

        tk.Label(side, text="Nieuwe stappen in:").pack(anchor="w")
        self.target = tk.StringVar(value="main")
        row = tk.Frame(side); row.pack(anchor="w")
        for text, val in [("hoofdlijst", "main"), ("THEN", "then"), ("ELSE", "else")]:
            tk.Radiobutton(row, text=text, variable=self.target, value=val).pack(side="left")

        tk.Label(side, text="Sleep maakt:").pack(anchor="w", pady=(4, 0))
        self.drag_mode = tk.StringVar(value="tap_template")
        tk.Radiobutton(side, text="tap_template", variable=self.drag_mode, value="tap_template").pack(anchor="w")
        tk.Radiobutton(side, text="wait_template", variable=self.drag_mode, value="wait_template").pack(anchor="w")
        tk.Radiobutton(side, text="tap_region", variable=self.drag_mode, value="tap_region").pack(anchor="w")
        tk.Radiobutton(side, text="tap_all_template (alles tikken)",
                       variable=self.drag_mode, value="tap_all_template").pack(anchor="w")

        button_groups = [
            [
                ("If-conditie", self.start_if),
                ("OR-template", self.start_or_template),
            ],
            [
                ("Zoekgebied", self.start_region),
                ("Geen zoekgebied", self.clear_region),
            ],
            [
                ("Wacht", self.add_wait),
                ("Swipe", self.add_swipe),
            ],
            [
                ("Bewerk", self.edit_selected),
                ("Test template", self.test_selected_template),
            ],
            [
                ("Thr set", self.set_selected_threshold),
                ("Thr +0.02", self.raise_selected_threshold),
            ],
            [
                ("Thr -0.02", self.lower_selected_threshold),
                ("Dupliceer", self.duplicate_selected),
            ],
            [
                ("Omhoog", self.move_selected_up),
                ("Omlaag", self.move_selected_down),
            ],
            [
                ("Verwijder", self.delete_selected),
                ("Ververs", self.refresh),
            ],
            [
                ("Open", self.open_script),
                ("Opslaan", self.save),
            ],
            [
                ("Draai 1 ronde", self.run_once),
                ("Draai loop", self.run_now),
            ],
        ]
        for group in button_groups:
            row = tk.Frame(side)
            row.pack(fill="x", pady=1)
            for text, cmd in group:
                tk.Button(row, text=text, command=cmd, width=13).pack(side="left", padx=1)

        self.hint = tk.Label(side, text="Klik = tap  |  Sleep = template", fg="gray")
        self.hint.pack(anchor="w", pady=(6, 0))

        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        self.refresh()

    # ---------- screenshot / tekenen ----------
    def refresh(self) -> None:
        OUTPUTS.mkdir(exist_ok=True)
        png = OUTPUTS / "_builder.png"
        try:
            screenshot.save_screenshot(png, serial=self.serial)
        except adb.AdbError as exc:
            messagebox.showerror("Screenshot mislukt", str(exc))
            return
        self.full = cv2.imread(str(png))
        self.photo = tk.PhotoImage(file=str(png)).subsample(SUB, SUB)
        self.canvas.config(width=self.photo.width(), height=self.photo.height())
        self.redraw()

    def _draw_markers(self, steps: list[dict], number_prefix: str = "") -> None:
        for i, step in enumerate(steps, 1):
            tag = f"{number_prefix}{i}"
            if step["type"] == "tap":
                x, y = step["x"] // SUB, step["y"] // SUB
                self.canvas.create_oval(x - 9, y - 9, x + 9, y + 9, outline="#ff3b3b", width=2)
                self.canvas.create_text(x, y, text=tag, fill="#ff3b3b")
            elif step.get("box"):
                x1, y1, x2, y2 = (v // SUB for v in step["box"])
                colour = {
                    "tap_region": "#35d16f",
                    "wait_template": "#ffd23b",
                    "if_template": "#c07bff",
                    "tap_all_template": "#3bffd1",
                }.get(step["type"], "#3bd1ff")
                self.canvas.create_rectangle(x1, y1, x2, y2, outline=colour, width=2)
                self.canvas.create_text(x1 + 10, y1 + 8, text=tag, fill=colour)
            if step.get("region"):
                # zoekgebied van tap_all_template: groot gestippeld kader
                rx1, ry1, rx2, ry2 = (v // SUB for v in step["region"])
                self.canvas.create_rectangle(rx1, ry1, rx2, ry2, outline="#3bff8c",
                                             width=2, dash=(6, 3))
                self.canvas.create_text(rx1 + 26, ry1 + 10, text=f"{tag} zoekgebied", fill="#3bff8c")
            for alt_i, box in enumerate(step.get("boxes", []) or [], 1):
                x1, y1, x2, y2 = (v // SUB for v in box)
                self.canvas.create_rectangle(x1, y1, x2, y2, outline="#ff8c3b", width=2, dash=(3, 2))
                self.canvas.create_text(x1 + 12, y1 + 10, text=f"{tag}O{alt_i}", fill="#ff8c3b")
            if step["type"] == "if_template":
                self._draw_markers(step.get("then", []), f"{tag}T")
                self._draw_markers(step.get("else", []), f"{tag}E")

    def redraw(self) -> None:
        self.canvas.delete("all")
        if self.photo is not None:
            self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self._draw_markers(self.steps)
        self.rebuild_rows()

    def rebuild_rows(self) -> None:
        self.rows = []
        self.listbox.delete(0, tk.END)
        for i, step in enumerate(self.steps):
            self.rows.append((self.steps, i, 0, i))
            self.listbox.insert(tk.END, f"{i + 1}. {describe(step)}")
            if step["type"] == "if_template":
                for branch in ("then", "else"):
                    self.rows.append((None, -1, 1, i))
                    self.listbox.insert(tk.END, f"    {branch}:")
                    for j, sub in enumerate(step.get(branch, [])):
                        self.rows.append((step[branch], j, 2, i))
                        self.listbox.insert(tk.END, f"        {describe(sub)}")

    def on_select(self, _e: tk.Event) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        _c, _idx, _depth, top = self.rows[sel[0]]
        self.active_if = top if self.steps[top]["type"] == "if_template" else None

    def selected_row(self) -> tuple[list, int, int, int] | None:
        sel = self.listbox.curselection()
        if not sel:
            return None
        container, idx, depth, top = self.rows[sel[0]]
        if container is None or idx < 0:
            return None
        return container, idx, depth, top

    def selected_step(self) -> dict | None:
        row = self.selected_row()
        if row is None:
            return None
        container, idx, _depth, _top = row
        return container[idx]

    # ---------- stappen toevoegen ----------
    def target_container(self) -> list | None:
        where = self.target.get()
        if where == "main":
            return self.steps
        if self.active_if is None or self.steps[self.active_if]["type"] != "if_template":
            messagebox.showinfo("Geen if geselecteerd",
                                "Selecteer eerst een if-stap in de lijst om in THEN/ELSE te bouwen.")
            return None
        return self.steps[self.active_if].setdefault(where, [])

    def add_step(self, step: dict) -> None:
        c = self.target_container()
        if c is None:
            return
        c.append(step)
        self.redraw()

    # ---------- muis ----------
    def on_press(self, e: tk.Event) -> None:
        self.drag_start = (e.x, e.y)

    def on_motion(self, e: tk.Event) -> None:
        if self.drag_start is None:
            return
        self.canvas.delete("rubber")
        self.canvas.create_rectangle(*self.drag_start, e.x, e.y,
                                     outline="#3bd1ff", dash=(4, 2), tags="rubber")

    def on_release(self, e: tk.Event) -> None:
        if self.drag_start is None:
            return
        sx, sy = self.drag_start
        self.drag_start = None
        self.canvas.delete("rubber")
        if abs(e.x - sx) < 6 and abs(e.y - sy) < 6:
            if self.pending_if or self.pending_or_step is not None or self.pending_region_step is not None:
                messagebox.showinfo("Sleep vereist", "Sleep een kader (niet klikken).")
                return
            self.add_step({"type": "tap", "x": e.x * SUB, "y": e.y * SUB})
        else:
            self.make_from_region(sx, sy, e.x, e.y)

    def make_from_region(self, x1: int, y1: int, x2: int, y2: int) -> None:
        dx1, dy1 = min(x1, x2) * SUB, min(y1, y2) * SUB
        dx2, dy2 = max(x1, x2) * SUB, max(y1, y2) * SUB
        box = [dx1, dy1, dx2, dy2]
        mode = self.drag_mode.get()

        # Zoekgebied zetten voor een geselecteerde tap_all_template-stap.
        if self.pending_region_step is not None:
            self.pending_region_step["region"] = box
            self.pending_region_step = None
            self.hint.config(text="Klik = tap  |  Sleep = template", fg="gray")
            self.redraw()
            return

        if mode == "tap_region" and not self.pending_if and self.pending_or_step is None:
            self.add_step({"type": "tap_region", "box": box, "mode": "random", "padding": 4})
            return

        if self.full is None:
            return
        crop = self.full[dy1:dy2, dx1:dx2]
        if crop.size == 0:
            return
        TEMPLATES.mkdir(exist_ok=True)
        name = f"step_{int(time.time() * 1000)}.png"
        cv2.imwrite(str(TEMPLATES / name), crop)
        tmpl = f"templates/{name}"

        if self.pending_or_step is not None:
            self.pending_or_step.setdefault("templates", []).append(tmpl)
            self.pending_or_step.setdefault("boxes", []).append(box)
            self.pending_or_step = None
            self.hint.config(text="Klik = tap  |  Sleep = template", fg="gray")
            self.redraw()
            return

        if self.pending_if:
            self.pending_if = False
            self.hint.config(text="Klik = tap  |  Sleep = template", fg="gray")
            step = {"type": "if_template", "template": tmpl, "threshold": 0.85,
                    "box": box, "then": [], "else": []}
            self.steps.append(step)          # if komt altijd in de hoofdlijst
            self.active_if = len(self.steps) - 1
            self.redraw()
            return

        step = {"type": self.drag_mode.get(), "template": tmpl, "threshold": 0.85, "box": box}
        if step["type"] == "wait_template":
            step["timeout"] = 10.0
            step["tap"] = True
        elif step["type"] == "tap_all_template":
            step["delay"] = 0.25
            step["repeat"] = True
            step["max_taps"] = 40
        self.add_step(step)

    # ---------- knoppen ----------
    def start_if(self) -> None:
        self.pending_or_step = None
        self.pending_if = True
        self.hint.config(text="Sleep nu een kader om het conditie-beeld", fg="#c07bff")

    def start_or_template(self) -> None:
        step = self.selected_step()
        if step is None or step.get("type") not in {"tap_template", "wait_template",
                                                    "if_template", "tap_all_template"}:
            messagebox.showinfo("Geen template-stap", "Selecteer eerst een tap/wait/if template-stap.")
            return
        self.pending_if = False
        self.pending_region_step = None
        self.pending_or_step = step
        self.hint.config(text="Sleep nu extra OR-template voor geselecteerde stap", fg="#ff8c3b")

    def start_region(self) -> None:
        """Beperk het zoekgebied van een tap_all_template-stap (bv. alleen je inventory)."""
        step = self.selected_step()
        if step is None or step.get("type") != "tap_all_template":
            messagebox.showinfo("Geen tap_all-stap",
                                "Selecteer eerst een tap_all_template-stap.")
            return
        self.pending_if = False
        self.pending_or_step = None
        self.pending_region_step = step
        self.hint.config(text="Sleep nu het ZOEKGEBIED (bv. je inventory)", fg="#3bff8c")

    def clear_region(self) -> None:
        """Haal het zoekgebied weg (weer op het hele scherm zoeken)."""
        step = self.selected_step()
        if step is None or step.get("type") != "tap_all_template":
            messagebox.showinfo("Geen tap_all-stap", "Selecteer eerst een tap_all_template-stap.")
            return
        step.pop("region", None)
        self.redraw()

    def add_wait(self) -> None:
        lo = simpledialog.askfloat("Wacht", "Min. seconden:", initialvalue=3.0, minvalue=0.0)
        if lo is None:
            return
        hi = simpledialog.askfloat("Wacht", "Max. seconden:", initialvalue=max(lo, 5.0), minvalue=lo)
        if hi is None:
            hi = lo
        self.add_step({"type": "wait", "min": lo, "max": hi})

    def add_swipe(self) -> None:
        values: dict[str, int] = {}
        for key, prompt in [
            ("x1", "Start X:"),
            ("y1", "Start Y:"),
            ("x2", "Eind X:"),
            ("y2", "Eind Y:"),
        ]:
            value = simpledialog.askinteger("Swipe", prompt, initialvalue=0)
            if value is None:
                return
            values[key] = int(value)
        ms = simpledialog.askinteger("Swipe", "Duur in ms:", initialvalue=300, minvalue=1)
        if ms is None:
            return
        values["ms"] = int(ms)
        self.add_step({"type": "swipe", **values})

    def edit_selected(self) -> None:
        step = self.selected_step()
        if step is None:
            messagebox.showinfo("Geen stap", "Selecteer eerst een echte stap.")
            return

        label = simpledialog.askstring(
            "Label",
            "Label voor deze stap (mag leeg):",
            initialvalue=str(step.get("label", "")),
        )
        if label is not None:
            if label.strip():
                step["label"] = label.strip()
            else:
                step.pop("label", None)

        kind = step.get("type")
        if kind == "tap":
            x = simpledialog.askinteger("Tap", "X coordinaat:", initialvalue=int(step.get("x", 0)))
            if x is None:
                self.redraw()
                return
            y = simpledialog.askinteger("Tap", "Y coordinaat:", initialvalue=int(step.get("y", 0)))
            if y is not None:
                step["x"] = int(x)
                step["y"] = int(y)
        elif kind == "wait":
            lo = simpledialog.askfloat("Wacht", "Min. seconden:", initialvalue=float(step.get("min", 1.0)), minvalue=0.0)
            if lo is None:
                self.redraw()
                return
            hi = simpledialog.askfloat("Wacht", "Max. seconden:", initialvalue=float(step.get("max", lo)), minvalue=0.0)
            if hi is not None:
                step["min"] = float(min(lo, hi))
                step["max"] = float(max(lo, hi))
        elif kind == "tap_region":
            box = list(step.get("box", [0, 0, 0, 0]))
            for i, title in enumerate(["Links X", "Boven Y", "Rechts X", "Onder Y"]):
                value = simpledialog.askinteger("Tap region", f"{title}:", initialvalue=int(box[i]))
                if value is None:
                    self.redraw()
                    return
                box[i] = int(value)
            x1, x2 = sorted([box[0], box[2]])
            y1, y2 = sorted([box[1], box[3]])
            step["box"] = [x1, y1, x2, y2]
            mode = simpledialog.askstring(
                "Tap region",
                "Mode: random of center",
                initialvalue=str(step.get("mode", "random")),
            )
            if mode:
                step["mode"] = "center" if mode.strip().lower() == "center" else "random"
            padding = simpledialog.askinteger(
                "Tap region",
                "Padding vanaf rand in pixels:",
                initialvalue=int(step.get("padding", 4)),
                minvalue=0,
            )
            if padding is not None:
                step["padding"] = int(padding)
        elif kind in {"tap_template", "wait_template", "if_template"}:
            threshold = simpledialog.askfloat(
                "Template",
                "Match threshold (0.0 - 1.0):",
                initialvalue=float(step.get("threshold", 0.85)),
                minvalue=0.0,
                maxvalue=1.0,
            )
            if threshold is not None:
                step["threshold"] = float(threshold)
            if kind == "wait_template":
                timeout = simpledialog.askfloat(
                    "Wait template",
                    "Timeout in seconden:",
                    initialvalue=float(step.get("timeout", 10.0)),
                    minvalue=0.0,
                )
                if timeout is not None:
                    step["timeout"] = float(timeout)
                step["tap"] = bool(messagebox.askyesno(
                    "Wait template",
                    "Tik op het template zodra het verschijnt?",
                ))
        elif kind == "swipe":
            for key, title in [("x1", "Start X"), ("y1", "Start Y"), ("x2", "Eind X"), ("y2", "Eind Y")]:
                value = simpledialog.askinteger("Swipe", f"{title}:", initialvalue=int(step.get(key, 0)))
                if value is None:
                    self.redraw()
                    return
                step[key] = int(value)
            ms = simpledialog.askinteger("Swipe", "Duur in ms:", initialvalue=int(step.get("ms", 300)), minvalue=1)
            if ms is not None:
                step["ms"] = int(ms)

        self.redraw()

    def selected_template_step(self) -> dict | None:
        step = self.selected_step()
        if step is None or step.get("type") not in {"tap_template", "wait_template", "if_template"}:
            messagebox.showinfo("Geen template-stap", "Selecteer eerst een tap/wait/if template-stap.")
            return None
        return step

    def set_selected_threshold(self) -> None:
        step = self.selected_template_step()
        if step is None:
            return
        threshold = simpledialog.askfloat(
            "Threshold",
            "Nieuwe threshold (0.0 - 1.0):",
            initialvalue=float(step.get("threshold", 0.85)),
            minvalue=0.0,
            maxvalue=1.0,
        )
        if threshold is None:
            return
        step["threshold"] = round(float(threshold), 3)
        self.redraw()

    def adjust_selected_threshold(self, delta: float) -> None:
        step = self.selected_template_step()
        if step is None:
            return
        current = float(step.get("threshold", 0.85))
        step["threshold"] = round(max(0.0, min(1.0, current + delta)), 3)
        self.redraw()

    def raise_selected_threshold(self) -> None:
        self.adjust_selected_threshold(0.02)

    def lower_selected_threshold(self) -> None:
        self.adjust_selected_threshold(-0.02)

    def duplicate_selected(self) -> None:
        row = self.selected_row()
        if row is None:
            messagebox.showinfo("Geen stap", "Selecteer eerst een echte stap.")
            return
        container, idx, _depth, _top = row
        container.insert(idx + 1, copy.deepcopy(container[idx]))
        self.redraw()

    def move_selected_up(self) -> None:
        row = self.selected_row()
        if row is None:
            messagebox.showinfo("Geen stap", "Selecteer eerst een echte stap.")
            return
        container, idx, _depth, _top = row
        if idx <= 0:
            return
        container[idx - 1], container[idx] = container[idx], container[idx - 1]
        self.redraw()

    def move_selected_down(self) -> None:
        row = self.selected_row()
        if row is None:
            messagebox.showinfo("Geen stap", "Selecteer eerst een echte stap.")
            return
        container, idx, _depth, _top = row
        if idx >= len(container) - 1:
            return
        container[idx + 1], container[idx] = container[idx], container[idx + 1]
        self.redraw()

    def test_selected_template(self) -> None:
        step = self.selected_step()
        if step is None or not step.get("template"):
            messagebox.showinfo("Geen template", "Selecteer een template-, wait- of if-stap.")
            return
        try:
            screen = screenshot.screenshot_to_cv2(screenshot.capture_png(self.serial))
        except (adb.AdbError, ValueError) as exc:
            messagebox.showerror("Test mislukt", str(exc))
            return

        best = None
        best_name = None
        errors: list[str] = []
        threshold = float(step.get("threshold", 0.85))
        for tmpl_name in step_template_names(step):
            tmpl_path = ROOT / tmpl_name
            if not tmpl_path.is_file():
                errors.append(f"mist: {tmpl_name}")
                continue
            tmpl = cv2.imread(str(tmpl_path), cv2.IMREAD_COLOR)
            if tmpl is None:
                errors.append(f"niet leesbaar: {tmpl_name}")
                continue
            try:
                match = vision.find_template(screen, tmpl, threshold=threshold)
            except ValueError as exc:
                errors.append(f"{tmpl_name}: {exc}")
                continue
            if match is not None and (best is None or match.confidence > best.confidence):
                best = match
                best_name = tmpl_name

        if best is None:
            detail = "\n".join(errors)
            messagebox.showinfo(
                "Niet gevonden",
                "Geen template gevonden boven de ingestelde threshold."
                + (f"\n\n{detail}" if detail else ""),
            )
            return
        messagebox.showinfo(
            "Gevonden",
            f"Beste template: {best_name}\n"
            f"Confidence: {best.confidence:.3f}\n"
            f"Box: {best.x},{best.y} {best.width}x{best.height}\n"
            f"Center: {best.center[0]},{best.center[1]}",
        )

    def delete_selected(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        container, idx, _depth, _top = self.rows[sel[0]]
        if container is None:      # een then:/else: kop
            return
        container.pop(idx)
        self.active_if = None
        self.redraw()

    def open_script(self) -> None:
        path = filedialog.askopenfilename(
            initialdir=str(ROOT),
            filetypes=[("JSON", "*.json"), ("Alle bestanden", "*.*")],
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Open mislukt", str(exc))
            return
        steps = data.get("steps")
        if not isinstance(steps, list):
            messagebox.showerror("Ongeldig script", "JSON bevat geen 'steps'-lijst.")
            return
        self.steps = steps
        self.loop_var.set(bool(data.get("loop", False)))
        self.active_if = None
        self.redraw()

    def save(self) -> None:
        if not self.steps:
            messagebox.showinfo("Leeg", "Nog geen stappen.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", initialdir=str(ROOT),
            initialfile="script.json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        Path(path).write_text(json.dumps({"loop": self.loop_var.get(), "steps": self.steps}, indent=2),
                              encoding="utf-8")
        messagebox.showinfo("Opgeslagen", f"Script opgeslagen:\n{path}")

    def run_once(self) -> None:
        self.run_now(max_loops=1)

    def run_now(self, max_loops: int | None = None) -> None:
        if not self.steps:
            messagebox.showinfo("Leeg", "Nog geen stappen om te draaien.")
            return
        OUTPUTS.mkdir(exist_ok=True)
        tmp = OUTPUTS / "_run.json"
        tmp.write_text(json.dumps({"loop": self.loop_var.get(), "steps": self.steps}, indent=2),
                       encoding="utf-8")
        # Geef het child-proces de adb-locatie mee, zodat het zeker een device vindt.
        env = os.environ.copy()
        env.setdefault("PHONEBOT_ADB_PATH", config.adb_executable())
        flags = subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0
        # 'cmd /k' houdt het console-venster OPEN, ook na afloop/een fout, zodat je
        # de output en eventuele foutmelding kunt lezen (sluit zelf met het kruisje).
        cmd = ["cmd", "/k", sys.executable, str(RUN_SCRIPT), str(tmp)]
        if max_loops is not None:
            cmd += ["--max-loops", str(int(max_loops))]
        subprocess.Popen(cmd, creationflags=flags, env=env)


def main() -> int:
    root = tk.Tk()
    Builder(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
