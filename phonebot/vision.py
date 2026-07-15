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


def find_all_templates(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float = config.DEFAULT_MATCH_THRESHOLD,
    max_results: int = 50,
) -> list[Match]:
    """Find every occurrence of `template` in `screen`, deduplicated.

    Useful for counting repeated items (e.g. how many logs are in the inventory).
    Overlapping hits are suppressed so each real occurrence is returned once.

    Returns matches sorted by confidence (highest first).
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
    ys, xs = np.where(result >= threshold)
    if len(xs) == 0:
        return []

    scores = result[ys, xs]
    order = np.argsort(scores)[::-1]  # highest confidence first

    matches: list[Match] = []
    taken: list[tuple[int, int]] = []
    for idx in order:
        x, y = int(xs[idx]), int(ys[idx])
        # Suppress hits whose top-left is within half a template of a kept hit.
        if any(abs(x - tx) < t_w * 0.5 and abs(y - ty) < t_h * 0.5 for tx, ty in taken):
            continue
        taken.append((x, y))
        matches.append(
            Match(x=x, y=y, width=int(t_w), height=int(t_h), confidence=float(scores[idx]))
        )
        if len(matches) >= max_results:
            break
    return matches
