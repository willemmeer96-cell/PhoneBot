"""Run-logboek voor de bot-scripts: getimede actie-log + roterende screenshots.

Bedoeld om achteraf te zien wat een script deed en waar het vastliep (of bv. op een
disconnect/ban-scherm bleef hangen). Alles komt in een eigen mapje per run onder
`outputs/debug/`. Er worden maar `keep_frames` screenshots bewaard (oudste worden
gewist), dus de map loopt nooit vol. Oude runs worden ook opgeruimd (`keep_runs`).

Gebruik in een script:

    from phonebot import recorder
    rec = recorder.Recorder("powerchop", enabled=args.log)
    rec.log("start")
    rec.frame(screen, "chop boom")     # bewaart frame + logt de notitie
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

_PKG_ROOT = Path(__file__).resolve().parent.parent
DEBUG_DIR = _PKG_ROOT / "outputs" / "debug"


class Recorder:
    """Schrijft een log.txt en een roterende reeks frame_*.png per run.

    Args:
        name: label voor deze run (komt in de mapnaam).
        keep_frames: hoeveel recente screenshots bewaard blijven.
        keep_runs: hoeveel oude run-mappen bewaard blijven (0 = alles houden).
        enabled: staat het uit, dan doen alle methodes niets (geen schijf-I/O).
    """

    def __init__(self, name: str = "run", keep_frames: int = 20,
                 keep_runs: int = 10, enabled: bool = True) -> None:
        self.enabled = enabled
        self.keep_frames = max(1, keep_frames)
        self._counter = 0
        self.dir: Path | None = None
        self.log_path: Path | None = None
        if not enabled:
            return

        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        self._prune_runs(keep_runs)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.dir = DEBUG_DIR / f"{safe}_{stamp}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.dir / "log.txt"
        self.log(f"=== {name} gestart ===")

    def _prune_runs(self, keep: int) -> None:
        if keep <= 0:
            return
        runs = sorted((p for p in DEBUG_DIR.iterdir() if p.is_dir()),
                      key=lambda p: p.stat().st_mtime)
        for old in runs[:-keep]:
            shutil.rmtree(old, ignore_errors=True)

    def log(self, message: str) -> None:
        """Voeg een getimede regel toe aan log.txt (en print 'm)."""
        if not self.enabled or self.log_path is None:
            return
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def frame(self, image: np.ndarray, note: str = "") -> None:
        """Bewaar een screenshot in de roterende buffer; oudste worden gewist."""
        if not self.enabled or self.dir is None or image is None:
            return
        self._counter += 1
        name = f"frame_{self._counter:05d}.png"
        try:
            cv2.imwrite(str(self.dir / name), image)
            frames = sorted(self.dir.glob("frame_*.png"))
            for old in frames[:-self.keep_frames]:
                old.unlink(missing_ok=True)
        except OSError:
            pass
        if note:
            self.log(f"{note}  -> {name}")
