"""Render laid-out text blocks into PDF pages (vector) and Qt paths (editor)."""
from __future__ import annotations

import math
from typing import Callable

import numpy as np

from .engine import Laid, layout
from .model import TextBlock

Mapper = Callable[[tuple[float, float]], tuple[float, float]]   # source px -> page pt


def _rgb(c) -> tuple[float, float, float]:
    return tuple(v / 255.0 for v in c)


def _emit(shape, path, f: Mapper, dx: float = 0.0, dy: float = 0.0) -> None:
    for sub in path:
        cur = start = None
        for seg in sub:
            if seg[0] == "M":
                cur = start = f((seg[1][0] + dx, seg[1][1] + dy))
            elif seg[0] == "L":
                p = f((seg[1][0] + dx, seg[1][1] + dy))
                shape.draw_line(cur, p)
                cur = p
            elif seg[0] == "C":
                c1 = f((seg[1][0] + dx, seg[1][1] + dy))
                c2 = f((seg[2][0] + dx, seg[2][1] + dy))
                p = f((seg[3][0] + dx, seg[3][1] + dy))
                shape.draw_bezier(cur, c1, c2, p)
                cur = p
            elif seg[0] == "Z" and cur is not None and start is not None and cur != start:
                shape.draw_line(cur, start)
                cur = start


def draw_pdf(page, b: TextBlock, f: Mapper, pt_per_src: float, laid: Laid | None = None,
             include_soft_shadow: bool = False) -> None:
    """Vector text: [hard shadow] -> [outside stroke] -> fill (+ synthetic bold)."""
    laid = laid or layout(b)
    if not laid.path:
        return
    em_pt = b.size * pt_per_src
    if b.shadow_on and (b.shadow_blur <= 0 or include_soft_shadow):
        sdx, sdy = b.size * b.shadow_dx / 100, b.size * b.shadow_dy / 100
        sh = page.new_shape()
        _emit(sh, laid.path, f, sdx, sdy)
        w = em_pt * b.stroke_width / 100 * 2 if b.stroke_on else 0
        sh.finish(width=w, color=_rgb(b.shadow) if w else None, fill=_rgb(b.shadow), lineJoin=1, lineCap=1,
                  closePath=False, fill_opacity=b.shadow_opacity, stroke_opacity=b.shadow_opacity)
        sh.commit()
    if b.stroke_on and b.stroke_width > 0:
        st = page.new_shape()
        _emit(st, laid.path, f)
        st.finish(width=em_pt * b.stroke_width / 100 * 2, color=_rgb(b.stroke), fill=_rgb(b.stroke),
                  lineJoin=1, lineCap=1, closePath=False,
                  fill_opacity=b.stroke_opacity, stroke_opacity=b.stroke_opacity)
        st.commit()
    fl = page.new_shape()
    _emit(fl, laid.path, f)
    bw = em_pt * 0.03 * b.synth_bold
    fl.finish(width=bw, color=_rgb(b.fill) if bw > 0 else None, fill=_rgb(b.fill), lineJoin=1, lineCap=1,
              closePath=False, fill_opacity=b.fill_opacity, stroke_opacity=b.fill_opacity)
    fl.commit()


def draw_search_layer(page, b: TextBlock, f: Mapper, pt_per_src: float, laid: Laid | None = None) -> None:
    """Invisible real text (embedded font subset) so the PDF stays searchable/selectable."""
    import pymupdf
    from ..fonts import default_font_id, fitz_font
    laid = laid or layout(b)
    try:
        font = fitz_font(b.font_id or default_font_id(b.bold_guess))
    except Exception:
        return
    size = b.size * pt_per_src
    for text, x, y in laid.lines:
        if not text.strip():
            continue
        tw = pymupdf.TextWriter(page.rect)
        p = f((x, y))
        try:
            tw.append(p, text, font=font, fontsize=size)
        except Exception:
            continue
        morph = None
        if abs(b.rotation) > 0.01:
            morph = (pymupdf.Point(p), pymupdf.Matrix(b.rotation))
        tw.write_text(page, render_mode=3, morph=morph)


def soft_shadow_layer(blocks: list[TextBlock], canvas_w: int, canvas_h: int, f_px: Mapper,
                      px_per_src: float) -> np.ndarray | None:
    """RGBA (premultiplied) soft shadows at canvas resolution, rendered with MuPDF + blur."""
    import cv2
    import pymupdf
    soft = [b for b in blocks if b.vectorise and b.shadow_on and b.shadow_blur > 0 and b.text.strip()]
    if not soft:
        return None
    out = np.zeros((canvas_h, canvas_w, 4), np.float32)
    for b in soft:
        laid = layout(b)
        sdx, sdy = b.size * b.shadow_dx / 100, b.size * b.shadow_dy / 100
        blur_px = max(0.5, b.size * b.shadow_blur / 100 * px_per_src)
        pad = int(3 * blur_px) + 2
        x0, y0, x1, y1 = laid.bounds
        X0, Y0 = f_px((x0 + sdx, y0 + sdy))
        X1, Y1 = f_px((x1 + sdx, y1 + sdy))
        bx0, by0 = max(0, int(min(X0, X1)) - pad), max(0, int(min(Y0, Y1)) - pad)
        bx1, by1 = min(canvas_w, int(max(X0, X1)) + pad + 1), min(canvas_h, int(max(Y0, Y1)) + pad + 1)
        if bx1 <= bx0 or by1 <= by0:
            continue
        doc = pymupdf.open()
        page = doc.new_page(width=bx1 - bx0, height=by1 - by0)    # 1 pt == 1 canvas px
        sh = page.new_shape()
        _emit(sh, laid.path, lambda p: (f_px(p)[0] - bx0, f_px(p)[1] - by0), sdx, sdy)
        w = b.size * px_per_src * b.stroke_width / 100 * 2 if b.stroke_on else 0
        sh.finish(width=w, color=(0, 0, 0) if w else None, fill=(0, 0, 0), lineJoin=1, closePath=False)
        sh.commit()
        pix = page.get_pixmap(alpha=True)
        a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 4)[..., 3].astype(np.float32) / 255
        a = cv2.GaussianBlur(a, (0, 0), blur_px) * b.shadow_opacity
        hh, ww = min(a.shape[0], by1 - by0), min(a.shape[1], bx1 - bx0)
        a = a[:hh, :ww]
        reg = out[by0:by0 + hh, bx0:bx0 + ww]
        col = np.array(b.shadow, np.float32) / 255
        # premultiplied "over"
        reg[..., :3] = col * a[..., None] + reg[..., :3] * (1 - a[..., None])
        reg[..., 3] = a + reg[..., 3] * (1 - a)
    return out


def composite_premul(raster: np.ndarray, layer: np.ndarray | None) -> np.ndarray:
    """raster uint8 RGB  over-composited with a premultiplied float/uint8 RGBA layer."""
    if layer is None:
        return raster
    out = raster.copy()
    rows = np.flatnonzero(layer[..., 3].any(axis=1))
    if rows.size == 0:
        return out
    scale = 255.0 if layer.dtype != np.uint8 else 1.0
    for y0 in range(rows[0], rows[-1] + 1, 256):
        y1 = min(y0 + 256, rows[-1] + 1)
        L = layer[y0:y1].astype(np.float32) * (scale if layer.dtype != np.uint8 else 1.0)
        a = L[..., 3:4] / 255.0
        bg = out[y0:y1].astype(np.float32)
        out[y0:y1] = np.clip(bg * (1 - a) + L[..., :3] + 0.5, 0, 255).astype(np.uint8)
    return out


def qt_path(laid: Laid, dx: float = 0.0, dy: float = 0.0):
    from PySide6.QtGui import QPainterPath
    qp = QPainterPath()
    qp.setFillRule(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WindingFill)
    for sub in laid.path:
        for seg in sub:
            if seg[0] == "M":
                qp.moveTo(seg[1][0] + dx, seg[1][1] + dy)
            elif seg[0] == "L":
                qp.lineTo(seg[1][0] + dx, seg[1][1] + dy)
            elif seg[0] == "C":
                qp.cubicTo(seg[1][0] + dx, seg[1][1] + dy, seg[2][0] + dx, seg[2][1] + dy,
                           seg[3][0] + dx, seg[3][1] + dy)
            elif seg[0] == "Z":
                qp.closeSubpath()
    return qp
