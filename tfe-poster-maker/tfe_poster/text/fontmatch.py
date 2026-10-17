"""Suggest installed fonts that look like the original lettering.

Renders the recognised text in each candidate face (same outline engine as the
output), scales it onto the detected ink box and scores shape overlap (IoU of
slightly blurred masks) against the source strokes.
"""
from __future__ import annotations

from typing import Callable, Optional

import cv2
import numpy as np

from ..fonts import list_fonts
from ..textstyle import analyse_box
from .engine import flatten, layout_em
from .model import TextBlock

H = 48   # comparison height in px


def _target_mask(src: np.ndarray, b: TextBlock) -> Optional[np.ndarray]:
    x, y, w, h = b.box
    a = analyse_box(src, x, y, w, h)
    core = a.core.astype(np.uint8)
    ys, xs = np.nonzero(core)
    if xs.size < 20:
        return None
    crop = core[ys.min():ys.max() + 1, xs.min():xs.max() + 1] * 255
    k = H / crop.shape[0]
    return cv2.resize(crop, (max(4, int(crop.shape[1] * k)), H), interpolation=cv2.INTER_AREA)


def _render(font_id: str, text: str, w: int):
    tmp = TextBlock(0, text, font_id=font_id)
    try:
        path, ink, missing, _ = layout_em(tmp)
    except Exception:
        return None
    if missing or not path:
        return None
    x0, y0, x1, y1 = ink
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    sx, sy = w / (x1 - x0), H / (y1 - y0)       # stretch to the target box: compare letter shapes
    img = np.zeros((H, w), np.uint8)
    polys = [np.array([[(px - x0) * sx * 8, (py - y0) * sy * 8] for px, py in poly], np.int32)
             for poly in flatten(path, 6)]
    cv2.fillPoly(img, polys, 255, lineType=cv2.LINE_AA, shift=3)
    return img, (x1 - x0) / (y1 - y0)


def suggest(src: np.ndarray, b: TextBlock, top: int = 12,
            progress: Optional[Callable[[float], None]] = None,
            should_stop: Callable[[], bool] = lambda: False) -> list[tuple[str, float]]:
    """[(font_id, score 0..1)] best first."""
    text = (b.ocr_text or b.text).split("\n")[0].strip()
    if not text:
        return []
    target = _target_mask(src, b)
    if target is None:
        return []
    tb = cv2.GaussianBlur(target.astype(np.float32) / 255, (0, 0), 1.2)
    target_ar = target.shape[1] / H
    fonts = list_fonts()
    scores = []
    for i, f in enumerate(fonts):
        if should_stop():
            break
        res = _render(f.id, text, target.shape[1])
        if res is not None:
            r, ar = res
            rb = cv2.GaussianBlur(r.astype(np.float32) / 255, (0, 0), 1.2)
            iou = np.minimum(tb, rb).sum() / max(np.maximum(tb, rb).sum(), 1e-6)
            # the comparison stretches to the box; penalise fonts whose natural width differs
            aspect = np.exp(-2.0 * abs(np.log(max(ar, 1e-3) / target_ar)))
            scores.append((f.id, float(iou * aspect)))
        if progress and i % 20 == 0:
            progress(i / len(fonts))
    scores.sort(key=lambda t: -t[1])
    return scores[:top]
