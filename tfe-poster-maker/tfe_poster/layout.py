"""Fit an image onto an A1 sheet without crop or stretch, plus dpi bookkeeping."""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from .config import A1_LONG_MM, A1_SHORT_MM, MM_PER_INCH, PT_PER_INCH


def mm_to_px(mm: float, dpi: int) -> int:
    return int(round(mm / MM_PER_INCH * dpi))


@dataclass
class Layout:
    """Where the source image sits on the A1 canvas.

    All *_px values are in output-canvas pixels at ``dpi``.
    """
    src_w: int
    src_h: int
    orientation: str          # portrait | landscape
    page_w_mm: float
    page_h_mm: float
    dpi: int
    margin_mm: float
    canvas_w: int
    canvas_h: int
    place_x: int
    place_y: int
    place_w: int
    place_h: int

    @property
    def scale(self) -> float:
        """Source px -> canvas px (uniform)."""
        return self.place_w / self.src_w

    @property
    def page_w_pt(self) -> float:
        return self.page_w_mm / MM_PER_INCH * PT_PER_INCH

    @property
    def page_h_pt(self) -> float:
        return self.page_h_mm / MM_PER_INCH * PT_PER_INCH

    def src_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        s_x = self.place_w / self.src_w
        s_y = self.place_h / self.src_h
        return self.place_x + x * s_x, self.place_y + y * s_y

    def canvas_to_pt(self, x: float, y: float) -> tuple[float, float]:
        """Canvas px (top-left origin) -> PDF points (top-left origin, as PyMuPDF uses)."""
        return x * self.page_w_pt / self.canvas_w, y * self.page_h_pt / self.canvas_h

    @property
    def printed_w_in(self) -> float:
        return self.place_w / self.dpi

    @property
    def native_ppi(self) -> float:
        """Source pixels per printed inch, before any upscaling."""
        return self.src_w / self.printed_w_in

    def to_dict(self) -> dict:
        return asdict(self)


def choose_orientation(w: int, h: int, requested: str = "auto") -> str:
    if requested in ("portrait", "landscape"):
        return requested
    return "landscape" if w > h else "portrait"


def compute_layout(src_w: int, src_h: int, orientation: str = "auto",
                   margin_mm: float = 15.0, dpi: int = 300) -> Layout:
    orient = choose_orientation(src_w, src_h, orientation)
    if orient == "portrait":
        pw, ph = A1_SHORT_MM, A1_LONG_MM
    else:
        pw, ph = A1_LONG_MM, A1_SHORT_MM
    cw, ch = mm_to_px(pw, dpi), mm_to_px(ph, dpi)
    m = mm_to_px(max(0.0, margin_mm), dpi)
    inner_w, inner_h = max(1, cw - 2 * m), max(1, ch - 2 * m)
    s = min(inner_w / src_w, inner_h / src_h)
    w, h = max(1, int(round(src_w * s))), max(1, int(round(src_h * s)))
    w, h = min(w, inner_w), min(h, inner_h)
    x, y = (cw - w) // 2, (ch - h) // 2
    return Layout(src_w, src_h, orient, pw, ph, dpi, margin_mm, cw, ch, x, y, w, h)


def sample_edge_colour(img: np.ndarray, frac: float = 0.02) -> tuple[int, int, int]:
    """Median colour of a thin border strip of an RGB uint8 image.

    The median is robust to a few stray pixels (e.g. a signature in a corner).
    """
    h, w = img.shape[:2]
    b = max(1, int(round(min(h, w) * frac)))
    strips = [img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3),
              img[:, :b].reshape(-1, 3), img[:, -b:].reshape(-1, 3)]
    px = np.concatenate(strips, axis=0)
    med = np.median(px, axis=0)
    return int(med[0]), int(med[1]), int(med[2])


def compose_canvas(placed: np.ndarray, layout: Layout,
                   colour: tuple[int, int, int]) -> np.ndarray:
    """Paste an already-resampled image (place_h x place_w) on a solid canvas."""
    assert placed.shape[0] == layout.place_h and placed.shape[1] == layout.place_w, \
        (placed.shape, layout.place_w, layout.place_h)
    canvas = np.empty((layout.canvas_h, layout.canvas_w, 3), np.uint8)
    canvas[:] = colour
    canvas[layout.place_y:layout.place_y + layout.place_h,
           layout.place_x:layout.place_x + layout.place_w] = placed
    return canvas
