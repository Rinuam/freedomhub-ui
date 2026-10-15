"""numpy <-> Qt helpers and an image pyramid for fast zooming on A1 canvases."""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap


def to_qimage(arr: np.ndarray) -> QImage:
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    if arr.ndim == 3 and arr.shape[2] == 4:
        img = QImage(arr.data, w, h, 4 * w, QImage.Format_RGBA8888)
    else:
        img = QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888)
    return img.copy()   # detach from the numpy buffer


def to_pixmap(arr: np.ndarray) -> QPixmap:
    return QPixmap.fromImage(to_qimage(arr))


def downscale(arr: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    h, w = arr.shape[:2]
    f = min(1.0, max_side / max(h, w))
    if f >= 1.0:
        return arr, 1.0
    return cv2.resize(arr, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA), f


class Pyramid:
    """Levels at 1, 1/2, 1/4 … down to ~1000 px; crop+resize from the nearest level."""

    def __init__(self, arr: np.ndarray):
        self.levels = [arr]
        while max(self.levels[-1].shape[:2]) > 1200:
            self.levels.append(cv2.pyrDown(self.levels[-1]))
        self.h, self.w = arr.shape[:2]

    def render(self, x0: float, y0: float, x1: float, y1: float, out_w: int, out_h: int) -> np.ndarray:
        """Return region [x0,x1)x[y0,y1) (full-res coords) resized to out_w x out_h."""
        zoom = out_w / max(1e-6, (x1 - x0))
        lvl = 0
        while lvl + 1 < len(self.levels) and zoom <= 0.5 ** (lvl + 1):
            lvl += 1
        src = self.levels[lvl]
        k = src.shape[1] / self.w
        ix0, iy0 = int(np.floor(x0 * k)), int(np.floor(y0 * k))
        ix1, iy1 = int(np.ceil(x1 * k)), int(np.ceil(y1 * k))
        ix0c, iy0c = max(0, ix0), max(0, iy0)
        ix1c, iy1c = min(src.shape[1], ix1), min(src.shape[0], iy1)
        out = np.zeros((out_h, out_w, 3), np.uint8)
        out[:] = (60, 60, 64)
        if ix1c <= ix0c or iy1c <= iy0c:
            return out
        crop = src[iy0c:iy1c, ix0c:ix1c]
        sx = out_w / (ix1 - ix0)
        sy = out_h / (iy1 - iy0)
        dx0, dy0 = int(round((ix0c - ix0) * sx)), int(round((iy0c - iy0) * sy))
        dw = max(1, int(round(crop.shape[1] * sx)))
        dh = max(1, int(round(crop.shape[0] * sy)))
        interp = cv2.INTER_AREA if sx < 1 else (cv2.INTER_NEAREST if sx >= 3 else cv2.INTER_LINEAR)
        r = cv2.resize(crop, (dw, dh), interpolation=interp)
        dw, dh = min(dw, out_w - dx0), min(dh, out_h - dy0)
        if dw > 0 and dh > 0:
            out[dy0:dy0 + dh, dx0:dx0 + dw] = r[:dh, :dw]
        return out
