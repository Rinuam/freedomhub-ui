"""Text shaping (HarfBuzz) + glyph outlines (fontTools) -> vector paths.

One geometry feeds every renderer (PDF, PNG via MuPDF, Qt editor), so the
editor is WYSIWYG with the printed output.

Coordinates of a laid-out block are in source-image pixels, y down.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from ..fonts import default_font_id, font_bytes
from .model import TextBlock

ITALIC_SKEW = math.tan(math.radians(12))

# A path is a list of sub-paths; each sub-path is a list of segments:
#   ("M", (x, y)) | ("L", (x, y)) | ("C", (x1, y1), (x2, y2), (x, y)) | ("Z",)
Path = list[list[tuple]]


class _CubicPen:
    """fontTools pen collecting cubic segments (quadratics are elevated)."""

    def __init__(self, glyphset):
        from fontTools.pens.basePen import BasePen

        outer = self

        class P(BasePen):
            def _moveTo(self, p):
                outer.cur = [("M", p)]
                outer.subs.append(outer.cur)
                outer.last = p

            def _lineTo(self, p):
                outer.cur.append(("L", p))
                outer.last = p

            def _curveToOne(self, p1, p2, p3):
                outer.cur.append(("C", p1, p2, p3))
                outer.last = p3

            def _qCurveToOne(self, p1, p2):
                p0 = outer.last
                c1 = (p0[0] + 2 / 3 * (p1[0] - p0[0]), p0[1] + 2 / 3 * (p1[1] - p0[1]))
                c2 = (p2[0] + 2 / 3 * (p1[0] - p2[0]), p2[1] + 2 / 3 * (p1[1] - p2[1]))
                outer.cur.append(("C", c1, c2, p2))
                outer.last = p2

            def _closePath(self):
                outer.cur.append(("Z",))

            def _endPath(self):
                pass

        self.subs: list = []
        self.cur: list = []
        self.last = (0, 0)
        self.pen = P(glyphset)


class Face:
    def __init__(self, font_id: str):
        from fontTools.ttLib import TTFont
        import uharfbuzz as hb
        self.font_id = font_id
        data = font_bytes(font_id)
        self.tt = TTFont(io.BytesIO(data), lazy=True)
        self.upm = self.tt["head"].unitsPerEm
        self.glyph_order = self.tt.getGlyphOrder()
        self.glyphset = self.tt.getGlyphSet()
        hhea = self.tt["hhea"]
        os2 = self.tt["OS/2"] if "OS/2" in self.tt else None
        self.ascender = (os2.sTypoAscender if os2 and os2.sTypoAscender else hhea.ascent) / self.upm
        self.descender = (os2.sTypoDescender if os2 and os2.sTypoDescender else hhea.descent) / self.upm
        self.cap_height = (getattr(os2, "sCapHeight", 0) or 0.7 * self.upm) / self.upm if os2 else 0.7
        self.hb_face = hb.Face(hb.Blob(data))
        self.hb_font = hb.Font(self.hb_face)
        self._paths: dict[int, tuple[Path, Optional[tuple]]] = {}

    def glyph(self, gid: int):
        """(path in em units, y up; bounds or None)."""
        if gid in self._paths:
            return self._paths[gid]
        name = self.glyph_order[gid] if gid < len(self.glyph_order) else ".notdef"
        cp = _CubicPen(self.glyphset)
        try:
            self.glyphset[name].draw(cp.pen)
        except Exception:
            pass
        k = 1.0 / self.upm
        path = [[(seg[0], *[(p[0] * k, p[1] * k) for p in seg[1:]]) for seg in sub] for sub in cp.subs]
        xs = [p[0] for sub in path for seg in sub for p in seg[1:]]
        ys = [p[1] for sub in path for seg in sub for p in seg[1:]]
        bounds = (min(xs), min(ys), max(xs), max(ys)) if xs else None
        self._paths[gid] = (path, bounds)
        return self._paths[gid]

    def shape(self, text: str, tracking: float = 0.0, kern: bool = True, liga: bool = True):
        """[(gid, x, y)] in em units (y up) and total advance."""
        import uharfbuzz as hb
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb_font, buf, {"kern": kern, "liga": liga, "clig": liga, "calt": True})
        k = 1.0 / self.upm
        x = 0.0
        out = []
        n = len(buf.glyph_infos)
        for i, (info, pos) in enumerate(zip(buf.glyph_infos, buf.glyph_positions)):
            out.append((info.codepoint, x + pos.x_offset * k, pos.y_offset * k))
            x += pos.x_advance * k
            if i < n - 1:
                x += tracking / 1000.0
        return out, x


@lru_cache(maxsize=48)
def get_face(font_id: str) -> Face:
    return Face(font_id)


@dataclass
class Laid:
    path: Path                       # source px, y down, final transform applied
    ink_em: tuple                    # unrotated ink bounds in em units (y down), before placement
    bounds: tuple                    # axis-aligned bounds of the final path (source px)
    missing: str = ""
    lines: list = field(default_factory=list)   # (text, origin_x_px, baseline_y_px) for search layer
    size: float = 0.0


def _layout_em(b: TextBlock):
    """Glyph outlines for the whole block in em units, y down, origin at first baseline."""
    face = get_face(b.font_id or default_font_id(b.bold_guess))
    lines = b.display_text().split("\n")
    shaped = [face.shape(l, b.tracking, b.kerning, b.ligatures) for l in lines]
    widths = [w for _, w in shaped]
    maxw = max(widths) if widths else 0.0
    path: Path = []
    missing = set()
    line_info = []
    for li, ((glyphs, w), text) in enumerate(zip(shaped, lines)):
        dx = {"left": 0.0, "right": maxw - w}.get(b.align, (maxw - w) / 2)
        by = li * b.line_height
        line_info.append((text, dx, by))
        for gid, gx, gy in glyphs:
            if gid == 0:
                missing.update(ch for ch in text if not ch.isspace())
            gp, _ = face.glyph(gid)
            for sub in gp:
                nsub = []
                for seg in sub:
                    pts = []
                    for (px, py) in seg[1:]:
                        y = -(py + gy)                         # y down
                        x = px + gx + dx
                        if b.synth_italic:
                            x -= y * ITALIC_SKEW               # shear around the baseline
                        pts.append((x, y + by))
                    nsub.append((seg[0], *pts))
                path.append(nsub)
    if missing:
        # report only chars the font truly lacks
        cmap = face.tt.getBestCmap() or {}
        missing = {c for c in missing if ord(c) not in cmap}
    return path, "".join(sorted(missing)), line_info, face


def _bounds(path: Path):
    xs = [p[0] for sub in path for seg in sub for p in seg[1:]]
    ys = [p[1] for sub in path for seg in sub for p in seg[1:]]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _exact_bounds(path: Path):
    """Tight bounds (curves evaluated) - control boxes overshoot on round glyphs."""
    xs, ys = [], []
    last = (0.0, 0.0)
    for sub in path:
        for seg in sub:
            if seg[0] in ("M", "L"):
                last = seg[1]
                xs.append(last[0]); ys.append(last[1])
            elif seg[0] == "C":
                p0, p1, p2, p3 = last, seg[1], seg[2], seg[3]
                for i in range(1, 9):
                    t = i / 8
                    mt = 1 - t
                    xs.append(mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0])
                    ys.append(mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1])
                last = p3
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


@lru_cache(maxsize=512)
def _em_cached(key):
    b = TextBlock.from_dict({"id": 0, "text": "", **dict(key)})
    path, missing, lines, face = _layout_em(b)
    return path, _exact_bounds(path), missing, lines


def layout_em(b: TextBlock):
    key = tuple((k, v) for k, v in b.to_dict().items()
                if k in ("text", "case", "font_id", "bold_guess", "tracking", "line_height", "align",
                         "synth_italic", "kerning", "ligatures"))
    return _em_cached(key)


def layout(b: TextBlock) -> Laid:
    """Place the block: ink-box centre at (cx, cy), em = b.size px, rotated about the centre."""
    path_em, ink, missing, lines = layout_em(b)
    s = b.size
    mx, my = (ink[0] + ink[2]) / 2, (ink[1] + ink[3]) / 2
    th = math.radians(b.rotation)
    c, si = math.cos(th), math.sin(th)

    def T(p):
        x, y = (p[0] - mx) * s, (p[1] - my) * s
        return (b.cx + x * c - y * si, b.cy + x * si + y * c)

    path = [[(seg[0], *[T(p) for p in seg[1:]]) for seg in sub] for sub in path_em]
    line_pos = [(t, *T((dx, by))) for t, dx, by in lines]
    return Laid(path, ink, _bounds(path), missing, line_pos, s)


def autofit(b: TextBlock) -> None:
    """Size and centre the block so its ink matches the detected ink box."""
    if not b.ink:
        return
    _, ink, _, _ = layout_em(b)
    iw, ih = max(1e-4, ink[2] - ink[0]), max(1e-4, ink[3] - ink[1])
    x0, y0, x1, y1 = b.ink
    sw = (x1 - x0) / iw
    sh = (y1 - y0) / ih
    b.size = float(min(sw, sh * 1.15))
    b.cx, b.cy = (x0 + x1) / 2, (y0 + y1) / 2


def flatten(path: Path, steps: int = 8) -> list[list[tuple[float, float]]]:
    """Polylines for rasterising / hit-testing."""
    polys = []
    for sub in path:
        pts = []
        last = (0.0, 0.0)
        for seg in sub:
            if seg[0] in ("M", "L"):
                last = seg[1]
                pts.append(last)
            elif seg[0] == "C":
                p0, p1, p2, p3 = last, seg[1], seg[2], seg[3]
                for i in range(1, steps + 1):
                    t = i / steps
                    mt = 1 - t
                    pts.append((mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0],
                                mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1]))
                last = p3
        if len(pts) > 2:
            polys.append(pts)
    return polys
