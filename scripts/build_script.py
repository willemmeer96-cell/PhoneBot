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
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from phonebot import adb, config, screenshot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
OUTPUTS = ROOT / "outputs"
RUN_SCRIPT = Path(__file__).resolve().parent / "run_script.py"
SUB = 2  # screenshot op halve grootte tonen (device = canvas * SUB)


def describe(step: dict) -> str:
    t = step["type"]
    if t == "tap":
        return f"tap ({step['x']},{step['y']})"
    if t == "wait":
        return f"wait {step['min']}..{step['max']}s"
    if t == "tap_template":
        return f"tap_template {Path(step['template']).name}"
    if t == "wait_template":
        return f"wait_template {Path(step['template']).name} (max {step.get('timeout', 10)}s)"
    if t == "if_template":
        return f"if {Path(step['template']).name}?"
    return t


class Builder:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("PhoneBot script builder")
        self.steps: list[dict] = []
        self.full = None
        self.photo: tk.PhotoImage | None = None
        self.drag_start: tuple[int, int] | None = None
        self.pending_if = False
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
        self.listbox = tk.Listbox(side, width=36, height=18)
        self.listbox.pack(fill="y")
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

        for text, cmd in [
            ("If-conditie (sleep beeld)", self.start_if),
            ("Wacht toevoegen", self.add_wait),
            ("Verwijder", self.delete_selected),
            ("Ververs screenshot", self.refresh),
            ("Opslaan als .json", self.save),
            ("Draai script nu", self.run_now),
        ]:
            tk.Button(side, text=text, command=cmd, width=26).pack(pady=2)

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
                colour = {"wait_template": "#ffd23b", "if_template": "#c07bff"}.get(step["type"], "#3bd1ff")
                self.canvas.create_rectangle(x1, y1, x2, y2, outline=colour, width=2)
                self.canvas.create_text(x1 + 10, y1 + 8, text=tag, fill=colour)
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
            if self.pending_if:
                messagebox.showinfo("If-conditie", "Sleep een kader om het conditie-beeld (niet klikken).")
                return
            self.add_step({"type": "tap", "x": e.x * SUB, "y": e.y * SUB})
        else:
            self.make_from_region(sx, sy, e.x, e.y)

    def make_from_region(self, x1: int, y1: int, x2: int, y2: int) -> None:
        dx1, dy1 = min(x1, x2) * SUB, min(y1, y2) * SUB
        dx2, dy2 = max(x1, x2) * SUB, max(y1, y2) * SUB
        if self.full is None:
            return
        crop = self.full[dy1:dy2, dx1:dx2]
        if crop.size == 0:
            return
        TEMPLATES.mkdir(exist_ok=True)
        name = f"step_{int(time.time() * 1000)}.png"
        cv2.imwrite(str(TEMPLATES / name), crop)
        tmpl = f"templates/{name}"
        box = [dx1, dy1, dx2, dy2]

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
        self.add_step(step)

    # ---------- knoppen ----------
    def start_if(self) -> None:
        self.pending_if = True
        self.hint.config(text="Sleep nu een kader om het conditie-beeld", fg="#c07bff")

    def add_wait(self) -> None:
        lo = simpledialog.askfloat("Wacht", "Min. seconden:", initialvalue=3.0, minvalue=0.0)
        if lo is None:
            return
        hi = simpledialog.askfloat("Wacht", "Max. seconden:", initialvalue=max(lo, 5.0), minvalue=lo)
        if hi is None:
            hi = lo
        self.add_step({"type": "wait", "min": lo, "max": hi})

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

    def run_now(self) -> None:
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
        subprocess.Popen(["cmd", "/k", sys.executable, str(RUN_SCRIPT), str(tmp)],
                         creationflags=flags, env=env)


def main() -> int:
    root = tk.Tk()
    Builder(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
