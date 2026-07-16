"""Visuele script-builder: prik tap-punten en regio's op een emulator-screenshot.

Toont een screenshot van de emulator in een venster. Daarmee bouw je een
stappen-script (zoals GnomeBot):

  - KLIK op het beeld        -> voegt een 'tap' toe op dat punt
  - SLEEP een rechthoek      -> knipt een template en voegt een 'tap_template' toe
  - knop 'Wacht'             -> voegt een 'wait' (random tussen min/max) toe
  - Omhoog/Omlaag/Verwijder  -> volgorde aanpassen
  - 'Ververs'                -> nieuwe screenshot ophalen
  - 'Loop' aanvinken         -> sequentie herhalen
  - 'Opslaan'                -> script als .json
  - 'Draai'                  -> voert het script nu uit (via run_script.py)

Coordinaten worden op device-resolutie opgeslagen, dus schaal-onafhankelijk van
het venster.

Gebruik (Python via volledig pad i.v.m. Windows-sandbox):
    python scripts/build_script.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from phonebot import adb, screenshot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
OUTPUTS = ROOT / "outputs"
RUN_SCRIPT = Path(__file__).resolve().parent / "run_script.py"
SUB = 2  # screenshot wordt op halve grootte getoond (device = canvas * SUB)


class Builder:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("PhoneBot script builder")
        self.steps: list[dict] = []
        self.full = None          # cv2-beeld op device-resolutie
        self.photo: tk.PhotoImage | None = None
        self.drag_start: tuple[int, int] | None = None

        try:
            self.serial = adb.require_device()
        except adb.AdbError as exc:
            messagebox.showerror("Geen device", str(exc))
            root.destroy()
            return

        # Layout: canvas links, bediening rechts.
        self.canvas = tk.Canvas(root, bg="black", cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        side = tk.Frame(root, padx=8, pady=8)
        side.grid(row=0, column=1, sticky="ns")

        tk.Label(side, text="Stappen").pack(anchor="w")
        self.listbox = tk.Listbox(side, width=34, height=22)
        self.listbox.pack(fill="y")

        self.loop_var = tk.BooleanVar(value=True)
        tk.Checkbutton(side, text="Loop (herhaal sequentie)", variable=self.loop_var).pack(anchor="w", pady=(6, 4))

        tk.Label(side, text="Sleep maakt:").pack(anchor="w")
        self.drag_mode = tk.StringVar(value="tap_template")
        tk.Radiobutton(side, text="tap_template (zoek + tik)",
                       variable=self.drag_mode, value="tap_template").pack(anchor="w")
        tk.Radiobutton(side, text="wait_template (wacht tot beeld + tik)",
                       variable=self.drag_mode, value="wait_template").pack(anchor="w")

        for text, cmd in [
            ("Wacht toevoegen", self.add_wait),
            ("Omhoog", lambda: self.move(-1)),
            ("Omlaag", lambda: self.move(1)),
            ("Verwijder", self.delete_selected),
            ("Ververs screenshot", self.refresh),
            ("Opslaan als .json", self.save),
            ("Draai script nu", self.run_now),
        ]:
            tk.Button(side, text=text, command=cmd, width=24).pack(pady=2)

        tk.Label(side, text="Klik = tap  |  Sleep = template", fg="gray").pack(anchor="w", pady=(8, 0))

        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        self.refresh()

    # ---- screenshot / tekenen ----
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

    def redraw(self) -> None:
        self.canvas.delete("all")
        if self.photo is not None:
            self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        for i, step in enumerate(self.steps, 1):
            if step["type"] == "tap":
                x, y = step["x"] // SUB, step["y"] // SUB
                self.canvas.create_oval(x - 9, y - 9, x + 9, y + 9, outline="#ff3b3b", width=2)
                self.canvas.create_text(x, y, text=str(i), fill="#ff3b3b")
            elif step.get("box"):
                x1, y1, x2, y2 = (v // SUB for v in step["box"])
                colour = "#ffd23b" if step["type"] == "wait_template" else "#3bd1ff"
                self.canvas.create_rectangle(x1, y1, x2, y2, outline=colour, width=2)
                self.canvas.create_text(x1 + 10, y1 + 8, text=str(i), fill=colour)
        self.refresh_list()

    def refresh_list(self) -> None:
        self.listbox.delete(0, tk.END)
        for i, step in enumerate(self.steps, 1):
            self.listbox.insert(tk.END, f"{i}. {self.describe(step)}")

    @staticmethod
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
        return t

    # ---- muis ----
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
            self.steps.append({"type": "tap", "x": e.x * SUB, "y": e.y * SUB})
        else:
            self.add_template(sx, sy, e.x, e.y)
        self.redraw()

    def add_template(self, x1: int, y1: int, x2: int, y2: int) -> None:
        dx1, dy1 = min(x1, x2) * SUB, min(y1, y2) * SUB
        dx2, dy2 = max(x1, x2) * SUB, max(y1, y2) * SUB
        if self.full is None:
            return
        crop = self.full[dy1:dy2, dx1:dx2]
        if crop.size == 0:
            return
        TEMPLATES.mkdir(exist_ok=True)
        name = f"step_{int(time.time())}.png"
        cv2.imwrite(str(TEMPLATES / name), crop)
        step = {
            "type": self.drag_mode.get(),
            "template": f"templates/{name}",
            "threshold": 0.85,
            "box": [dx1, dy1, dx2, dy2],
        }
        if step["type"] == "wait_template":
            step["timeout"] = 10.0
            step["tap"] = True
        self.steps.append(step)

    # ---- bediening ----
    def add_wait(self) -> None:
        lo = simpledialog.askfloat("Wacht", "Min. seconden:", initialvalue=3.0, minvalue=0.0)
        if lo is None:
            return
        hi = simpledialog.askfloat("Wacht", "Max. seconden:", initialvalue=max(lo, 5.0), minvalue=lo)
        if hi is None:
            hi = lo
        self.steps.append({"type": "wait", "min": lo, "max": hi})
        self.redraw()

    def selected_index(self) -> int | None:
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def delete_selected(self) -> None:
        i = self.selected_index()
        if i is not None:
            self.steps.pop(i)
            self.redraw()

    def move(self, delta: int) -> None:
        i = self.selected_index()
        if i is None:
            return
        j = i + delta
        if 0 <= j < len(self.steps):
            self.steps[i], self.steps[j] = self.steps[j], self.steps[i]
            self.redraw()
            self.listbox.selection_set(j)

    def save(self) -> Path | None:
        if not self.steps:
            messagebox.showinfo("Leeg", "Nog geen stappen.")
            return None
        path = filedialog.asksaveasfilename(
            defaultextension=".json", initialdir=str(ROOT),
            initialfile="script.json", filetypes=[("JSON", "*.json")])
        if not path:
            return None
        data = {"loop": self.loop_var.get(), "steps": self.steps}
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        messagebox.showinfo("Opgeslagen", f"Script opgeslagen:\n{path}")
        return Path(path)

    def run_now(self) -> None:
        OUTPUTS.mkdir(exist_ok=True)
        tmp = OUTPUTS / "_run.json"
        tmp.write_text(json.dumps({"loop": self.loop_var.get(), "steps": self.steps}, indent=2),
                       encoding="utf-8")
        flags = subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0
        subprocess.Popen([sys.executable, str(RUN_SCRIPT), str(tmp)], creationflags=flags)


def main() -> int:
    root = tk.Tk()
    Builder(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
