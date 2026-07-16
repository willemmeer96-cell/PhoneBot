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


def find_color_blobs(
    screen: np.ndarray,
    lower_hsv: tuple[int, int, int],
    upper_hsv: tuple[int, int, int],
    min_area: int = 400,
    max_results: int = 20,
) -> list[Match]:
    """Find solid regions of a colour range (bijv. een felle tile-marker).

    Veel robuuster dan template matching voor stabiele, uniek-gekleurde markers:
    het wuift niet en is ongevoelig voor kleine beeldverschuivingen.

    Args:
        screen: BGR-beeld (screenshot).
        lower_hsv, upper_hsv: HSV-ondergrens/bovengrens (OpenCV: H 0-179, S/V 0-255).
        min_area: negeer blobs kleiner dan dit (pixels).
        max_results: maximaal aantal blobs.

    Returns:
        Match-objecten (bounding box van elke blob), grootste eerst. `confidence`
        bevat hier de vulgraad van de box (0-1), niet een template-score.
    """
    if screen is None or screen.size == 0:
        raise ValueError("Screen image is empty.")

    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lower_hsv, np.uint8), np.array(upper_hsv, np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blobs: list[Match] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        fill = float(area) / float(max(w * h, 1))
        blobs.append(Match(x=int(x), y=int(y), width=int(w), height=int(h), confidence=fill))

    blobs.sort(key=lambda m: m.width * m.height, reverse=True)
    return blobs[:max_results]


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
