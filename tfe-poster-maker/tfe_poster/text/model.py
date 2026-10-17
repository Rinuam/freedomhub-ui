"""Editable text block (all geometry in *source image pixels*)."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional

RGB = tuple[int, int, int]


@dataclass
class TextBlock:
    id: int
    text: str
    ocr_text: str = ""
    confidence: float = 1.0
    vectorise: bool = True          # draw as vector text
    erase: bool = True              # inpaint the original raster text
    # detection (source px)
    box: tuple[float, float, float, float] = (0, 0, 0, 0)      # x, y, w, h
    ink: Optional[tuple[float, float, float, float]] = None     # x0, y0, x1, y1
    erase_boxes: list = field(default_factory=list)             # extra boxes after merging lines
    erase_mask_grow: float = 1.0
    bold_guess: bool = False
    # typography
    font_id: str = ""
    size: float = 32.0              # em size in source px
    auto_fit: bool = True
    tracking: float = 0.0           # 1/1000 em added between glyphs
    line_height: float = 1.2        # multiple of size
    align: str = "center"           # left | center | right
    case: str = "none"              # none | upper | lower | title
    synth_bold: float = 0.0         # 0..1  (adds same-colour outline, ~3% em at 1)
    synth_italic: bool = False
    kerning: bool = True
    ligatures: bool = True
    # paint
    fill: RGB = (0, 0, 0)
    fill_opacity: float = 1.0
    stroke_on: bool = False
    stroke: RGB = (255, 255, 255)
    stroke_width: float = 4.0       # % of em
    stroke_opacity: float = 1.0
    shadow_on: bool = False
    shadow: RGB = (0, 0, 0)
    shadow_opacity: float = 0.6
    shadow_dx: float = 4.0          # % of em
    shadow_dy: float = 4.0
    shadow_blur: float = 6.0        # % of em (0 = hard vector shadow)
    # placement: centre of the ink box (before rotation), source px
    cx: float = 0.0
    cy: float = 0.0
    rotation: float = 0.0           # degrees, clockwise
    user_added: bool = False

    def display_text(self) -> str:
        t = self.text
        if self.case == "upper":
            return t.upper()
        if self.case == "lower":
            return t.lower()
        if self.case == "title":
            return t.title()
        return t

    def style_key(self) -> tuple:
        d = asdict(self)
        for k in ("id", "ocr_text", "confidence", "vectorise", "erase", "box", "ink", "erase_boxes",
                  "erase_mask_grow", "bold_guess", "auto_fit", "user_added"):
            d.pop(k)
        return tuple(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in d.items()))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TextBlock":
        d = dict(d)
        for k in ("box", "fill", "stroke", "shadow", "ink"):
            if d.get(k) is not None:
                d[k] = tuple(d[k])
        d["erase_boxes"] = [tuple(x) for x in d.get("erase_boxes") or []]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def copy_style_from(self, o: "TextBlock") -> None:
        for k in ("font_id", "tracking", "line_height", "align", "case", "synth_bold", "synth_italic",
                  "fill", "fill_opacity", "stroke_on", "stroke", "stroke_width", "stroke_opacity",
                  "shadow_on", "shadow", "shadow_opacity", "shadow_dx", "shadow_dy", "shadow_blur",
                  "kerning", "ligatures"):
            setattr(self, k, getattr(o, k))


@dataclass
class EraseRegion:
    """User-drawn rectangle to inpaint (source px)."""
    x: float
    y: float
    w: float
    h: float

    def to_dict(self):
        return asdict(self)
