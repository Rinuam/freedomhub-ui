"""Remove raster text from the 300 dpi canvas with OpenCV inpainting.

Masks come from the source-resolution analysis and are mapped onto the canvas.
Each box is inpainted in a local crop (capped resolution) so A1-sized canvases
stay fast; only masked pixels are replaced, with a feathered edge.
"""
from __future__ import annotations

import cv2
import numpy as np

MAX_WORK_SIDE = 1600


def inpaint_region(canvas: np.ndarray, src_mask: np.ndarray, src_x: int, src_y: int,
                   layout, method: str = "telea", grow: float = 1.0) -> None:
    """In-place: inpaint one mask (given at source resolution at src_x/src_y)."""
    s = layout.scale
    mh, mw = src_mask.shape
    # canvas rectangle of the mask crop
    X0, Y0 = layout.src_to_canvas(src_x, src_y)
    X1, Y1 = layout.src_to_canvas(src_x + mw, src_y + mh)
    X0, Y0, X1, Y1 = int(np.floor(X0)), int(np.floor(Y0)), int(np.ceil(X1)), int(np.ceil(Y1))
    W, H = X1 - X0, Y1 - Y0
    if W < 2 or H < 2:
        return
    mask = cv2.resize(src_mask, (W, H), interpolation=cv2.INTER_LINEAR)
    mask = (mask > 127).astype(np.uint8) * 255
    g = int(round(max(1.0, s * 0.75) * grow))
    if g > 0:
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1)))

    # Context around the mask so the inpainter sees real background.
    ctx = int(max(8, 0.15 * max(W, H) if max(W, H) < 400 else 0.05 * max(W, H)))
    cx0, cy0 = max(0, X0 - ctx), max(0, Y0 - ctx)
    cx1, cy1 = min(canvas.shape[1], X1 + ctx), min(canvas.shape[0], Y1 + ctx)
    region = canvas[cy0:cy1, cx0:cx1]
    full_mask = np.zeros(region.shape[:2], np.uint8)
    mx0, my0 = X0 - cx0, Y0 - cy0
    sub = full_mask[max(0, my0):my0 + H, max(0, mx0):mx0 + W]
    sub[:] = mask[max(0, -my0):max(0, -my0) + sub.shape[0], max(0, -mx0):max(0, -mx0) + sub.shape[1]]
    if not full_mask.any():
        return

    rh, rw = region.shape[:2]
    f = min(1.0, MAX_WORK_SIDE / max(rh, rw))
    flag = cv2.INPAINT_NS if method == "ns" else cv2.INPAINT_TELEA
    if f < 1.0:
        sw, sh = max(2, int(rw * f)), max(2, int(rh * f))
        small = cv2.resize(region, (sw, sh), interpolation=cv2.INTER_AREA)
        smask = (cv2.resize(full_mask, (sw, sh), interpolation=cv2.INTER_AREA) > 0).astype(np.uint8) * 255
        filled = cv2.inpaint(small, smask, 5, flag)
        filled = cv2.resize(filled, (rw, rh), interpolation=cv2.INTER_CUBIC)
    else:
        filled = cv2.inpaint(region, full_mask, max(3, int(round(3 * s))), flag)

    feather = max(1, int(round(s)))
    alpha = cv2.GaussianBlur(full_mask.astype(np.float32) / 255.0, (0, 0), feather)
    alpha = np.maximum(alpha, full_mask.astype(np.float32) / 255.0)[..., None]
    out = region.astype(np.float32) * (1 - alpha) + filled.astype(np.float32) * alpha
    region[:] = np.clip(out + 0.5, 0, 255).astype(np.uint8)
