"""Estimate text colour, background colour, weight and a pixel mask for a text box."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class BoxAnalysis:
    text_rgb: tuple[int, int, int]
    bg_rgb: tuple[int, int, int]
    stroke_ratio: float       # stroke width / box height (bold > ~0.11)
    mask: np.ndarray          # uint8 0/255, crop-sized, source resolution (for inpainting)
    core: np.ndarray          # bool, stroke pixels above the Otsu threshold (for ink extents)
    crop_x: int
    crop_y: int

    @property
    def bold(self) -> bool:
        return self.stroke_ratio > 0.11


def _crop(img: np.ndarray, x, y, w, h, pad):
    H, W = img.shape[:2]
    x0, y0 = max(0, int(np.floor(x - pad))), max(0, int(np.floor(y - pad)))
    x1, y1 = min(W, int(np.ceil(x + w + pad))), min(H, int(np.ceil(y + h + pad)))
    return img[y0:y1, x0:x1], x0, y0


def _background_plane(lab: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """Per-pixel background estimate: robust planar fit (a + bx + cy) to the ring.

    AI images often put text on gradients; a single median colour would make the
    whole box look 'different from background' and bloat the inpaint mask.
    """
    h, w = ring.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xn, yn = xx / max(1, w), yy / max(1, h)
    A = np.stack([np.ones(ring.sum(), np.float32), xn[ring], yn[ring]], axis=1)
    vals = lab[ring]
    keep = np.ones(len(vals), bool)
    coef = None
    for _ in range(3):            # iteratively drop outliers (stray strokes in the ring)
        coef, *_ = np.linalg.lstsq(A[keep], vals[keep], rcond=None)
        res = np.linalg.norm(A @ coef - vals, axis=1)
        thr = max(4.0, 2.5 * float(np.median(res[keep])))
        new_keep = res < thr
        if new_keep.sum() < 10 or (new_keep == keep).all():
            break
        keep = new_keep
    full = np.stack([np.ones_like(xn), xn, yn], axis=-1) @ coef
    return full.astype(np.float32)


def analyse_box(src: np.ndarray, x: float, y: float, w: float, h: float) -> BoxAnalysis:
    pad = max(3.0, 0.3 * h)
    crop, cx, cy = _crop(src, x, y, w, h, pad)
    ch, cw = crop.shape[:2]
    lab = cv2.cvtColor(crop, cv2.COLOR_RGB2LAB).astype(np.float32)

    inside = np.zeros((ch, cw), bool)
    bx0, by0 = int(max(0, x - cx)), int(max(0, y - cy))
    bx1, by1 = int(min(cw, x + w - cx + 0.5)), int(min(ch, y + h - cy + 0.5))
    inside[by0:by1, bx0:bx1] = True

    ring = ~inside
    if ring.sum() < 20:                       # box touches the image edge on all sides
        ring = np.zeros_like(inside)
        ring[[0, -1], :] = True
        ring[:, [0, -1]] = True
    bg_map = _background_plane(lab, ring)
    dist = np.linalg.norm(lab - bg_map, axis=2)

    d_in = dist[inside]
    d8 = np.clip(d_in, 0, 255).astype(np.uint8).reshape(-1, 1)
    otsu, _ = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    otsu = max(float(otsu), 12.0)             # ignore JPEG noise on flat backgrounds

    spill0 = cv2.dilate(inside.astype(np.uint8), np.ones((3, 3), np.uint8),
                        iterations=max(1, int(0.15 * h))).astype(bool)
    core = inside & (dist > otsu)
    ink = spill0 & (dist > otsu)       # strokes may poke slightly outside the OCR box
    if core.sum() < 5:
        core = inside & (dist >= np.percentile(d_in, 80))
    # Text colour from the stroke cores (the farthest half), not the antialiased rims.
    core_d = dist[core]
    strong = core & (dist >= np.median(core_d))
    text_rgb = np.median(crop[strong], axis=0)
    bg_rgb = np.median(crop[ring], axis=0)

    # Mask for inpainting: include antialiasing (half threshold) and grow a little,
    # but only around strokes inside the box (plus a small spill margin).
    mask = (spill0 & (dist > otsu * 0.5)).astype(np.uint8) * 255
    k = max(1, int(round(h * 0.04)))
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))

    dt = cv2.distanceTransform(core.astype(np.uint8), cv2.DIST_L2, 3)
    peaks = dt[(dt > 0) & (dt >= cv2.dilate(dt, np.ones((3, 3), np.uint8)))]
    stroke = 2.0 * float(np.median(peaks)) if peaks.size else 0.0
    return BoxAnalysis(tuple(int(v) for v in text_rgb), tuple(int(v) for v in bg_rgb),
                       stroke / max(1.0, h), mask, ink, cx, cy)
