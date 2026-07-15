"""Simple template matching with OpenCV.

Vision-based only: no knowledge of any specific app or game.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from . import config


@dataclass(frozen=True)
class Match:
    """A single template match result.

    Attributes:
        x, y: Top-left corner of the matched region (pixels).
        width, height: Size of the template (pixels).
        confidence: Match score in [0.0, 1.0].
    """

    x: int
    y: int
    width: int
    height: int
    confidence: float

    @property
    def center(self) -> tuple[int, int]:
        """Center pixel of the match, handy for tapping."""
        return (self.x + self.width // 2, self.y + self.height // 2)


def find_template(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float = config.DEFAULT_MATCH_THRESHOLD,
) -> Match | None:
    """Locate `template` inside `screen` using normalized cross-correlation.

    Args:
        screen: The larger BGR image (e.g. a screenshot).
        template: The smaller BGR image to search for.
        threshold: Minimum confidence to accept a match.

    Returns:
        The best Match at or above `threshold`, or None if nothing qualifies.

    Raises:
        ValueError: If either image is empty or the template is larger than the screen.
    """
    if screen is None or screen.size == 0:
        raise ValueError("Screen image is empty.")
    if template is None or template.size == 0:
        raise ValueError("Template image is empty.")

    s_h, s_w = screen.shape[:2]
    t_h, t_w = template.shape[:2]
    if t_h > s_h or t_w > s_w:
        raise ValueError(
            f"Template ({t_w}x{t_h}) is larger than the screen ({s_w}x{s_h})."
        )

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)

    if max_val < threshold:
        return None

    return Match(
        x=int(max_loc[0]),
        y=int(max_loc[1]),
        width=int(t_w),
        height=int(t_h),
        confidence=float(max_val),
    )
