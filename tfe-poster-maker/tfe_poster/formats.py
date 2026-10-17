"""Output targets: print (A0-A6, US, custom mm @ dpi) and pixels (social media, 4K…).

Each target maps source-image pixels onto an output canvas with one of:
  fit    - whole image visible; margins in the edge colour (or a chosen colour)
  fill   - canvas filled, image cropped (focus point selectable)
  extend - whole image visible; margins filled with a blurred, enlarged copy
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0

PAPER_MM = {
    "A0": (841, 1189), "A1": (594, 841), "A2": (420, 594), "A3": (297, 420),
    "A4": (210, 297), "A5": (148, 210), "A6": (105, 148),
    "B1": (707, 1000), "B2": (500, 707),
    "US Letter": (215.9, 279.4), "US Tabloid": (279.4, 431.8),
    "Poster 18×24 in": (457.2, 609.6), "Poster 24×36 in": (609.6, 914.4),
}

SOCIAL_PX = {
    "Instagram post 1:1": (1080, 1080),
    "Instagram portrait 4:5": (1080, 1350),
    "Instagram / TikTok story 9:16": (1080, 1920),
    "Facebook post": (1200, 630),
    "Facebook cover": (1640, 624),
    "LinkedIn post": (1200, 627),
    "LinkedIn banner": (1584, 396),
    "X / Twitter post 16:9": (1600, 900),
    "X / Twitter header": (1500, 500),
    "YouTube thumbnail": (1280, 720),
    "Pinterest pin 2:3": (1000, 1500),
    "Full HD 1920×1080": (1920, 1080),
    "4K UHD 3840×2160": (3840, 2160),
    "8K UHD 7680×4320": (7680, 4320),
}

IMAGE_FORMATS = ("png", "jpg", "tiff", "webp")


@dataclass
class OutputTarget:
    name: str = "A1"
    kind: str = "print"              # print | pixels | original
    enabled: bool = True
    # print
    paper: str = "A1"
    w_mm: float = 594.0
    h_mm: float = 841.0
    orientation: str = "auto"        # auto | portrait | landscape
    dpi: int = 300
    margin_mm: float = 15.0
    bleed_mm: float = 0.0
    # pixels
    w_px: int = 1080
    h_px: int = 1080
    margin_px: int = 0
    long_side_px: int = 4096         # for kind == "original" (keep aspect)
    # common
    fit: str = "fit"                 # fit | fill | extend
    focus_x: float = 0.5             # for fill crop
    focus_y: float = 0.5
    background: str = "edge"         # edge | white | black | #rrggbb
    formats: list[str] = field(default_factory=lambda: ["pdf", "png"])
    jpeg_quality: int = 95
    pdf_background: str = "jpeg"     # jpeg | lossless
    color_profile: str = "sRGB"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def label(self) -> str:
        if self.kind == "print":
            return f"{self.name} · {self.dpi} dpi · {', '.join(self.formats).upper()}"
        if self.kind == "original":
            return f"{self.name} · long side {self.long_side_px}px · {', '.join(self.formats).upper()}"
        return f"{self.name} · {self.w_px}×{self.h_px} · {', '.join(self.formats).upper()}"


def print_target(paper: str, dpi: int = 300, margin_mm: float = 15.0, formats=("pdf", "png"),
                 orientation: str = "auto") -> OutputTarget:
    w, h = PAPER_MM[paper]
    return OutputTarget(name=paper, kind="print", paper=paper, w_mm=w, h_mm=h, dpi=dpi,
                        margin_mm=margin_mm, formats=list(formats), orientation=orientation)


def social_target(name: str, fit: str = "extend", formats=("png", "jpg")) -> OutputTarget:
    w, h = SOCIAL_PX[name]
    return OutputTarget(name=name, kind="pixels", w_px=w, h_px=h, fit=fit, formats=list(formats),
                        margin_px=0)


def original_target(long_side: int = 4096, formats=("png",)) -> OutputTarget:
    return OutputTarget(name=f"Original aspect {long_side}px", kind="original", long_side_px=long_side,
                        fit="fit", formats=list(formats), margin_px=0)


DEFAULT_TARGETS = [print_target("A1"), social_target("Instagram portrait 4:5")]


@dataclass
class Placement:
    """Geometry of one output canvas."""
    canvas_w: int
    canvas_h: int
    page_w_pt: float
    page_h_pt: float
    scale: float            # canvas px per source px
    off_x: float            # canvas x of source x = 0
    off_y: float
    dpi: float
    orientation: str
    fit: str
    margin_px: int
    bleed_px: int = 0

    def src_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return self.off_x + x * self.scale, self.off_y + y * self.scale

    @property
    def pt_per_px(self) -> float:
        return self.page_w_pt / self.canvas_w

    def src_to_pt(self, p) -> tuple[float, float]:
        x, y = self.src_to_canvas(p[0], p[1])
        return x * self.pt_per_px, y * self.page_h_pt / self.canvas_h

    def image_rect(self, src_w: int, src_h: int) -> tuple[float, float, float, float]:
        """Canvas rect covered by the image (may extend past the canvas for fill)."""
        return self.off_x, self.off_y, self.off_x + src_w * self.scale, self.off_y + src_h * self.scale


def place(target: OutputTarget, src_w: int, src_h: int) -> Placement:
    t = target
    if t.kind == "print":
        w_mm, h_mm = t.w_mm, t.h_mm
        land_img = src_w > src_h
        orient = t.orientation
        if orient == "auto":
            orient = "landscape" if land_img else "portrait"
        if (orient == "landscape") != (w_mm > h_mm):
            w_mm, h_mm = h_mm, w_mm
        bleed = t.bleed_mm
        cw = int(round((w_mm + 2 * bleed) / MM_PER_INCH * t.dpi))
        ch = int(round((h_mm + 2 * bleed) / MM_PER_INCH * t.dpi))
        margin = int(round((t.margin_mm + bleed) / MM_PER_INCH * t.dpi)) if t.fit != "fill" else 0
        pw, ph = (w_mm + 2 * bleed) / MM_PER_INCH * PT_PER_INCH, (h_mm + 2 * bleed) / MM_PER_INCH * PT_PER_INCH
        dpi = t.dpi
        bleed_px = int(round(bleed / MM_PER_INCH * t.dpi))
    elif t.kind == "original":
        k = t.long_side_px / max(src_w, src_h)
        cw, ch = int(round(src_w * k)), int(round(src_h * k))
        margin, dpi, bleed_px = 0, 72.0, 0
        pw, ph = cw * 72 / 300, ch * 72 / 300            # PDF at 300 dpi nominal
        orient = "landscape" if cw > ch else "portrait"
        dpi = 300.0
    else:
        cw, ch = t.w_px, t.h_px
        margin = t.margin_px if t.fit != "fill" else 0
        pw, ph = cw * 72 / 300, ch * 72 / 300
        dpi = 300.0
        bleed_px = 0
        orient = "landscape" if cw > ch else "portrait"
    inner_w, inner_h = max(1, cw - 2 * margin), max(1, ch - 2 * margin)
    if t.fit == "fill":
        s = max(cw / src_w, ch / src_h)
        iw, ih = src_w * s, src_h * s
        ox = (cw - iw) * min(1.0, max(0.0, t.focus_x))
        oy = (ch - ih) * min(1.0, max(0.0, t.focus_y))
    else:
        s = min(inner_w / src_w, inner_h / src_h)
        iw, ih = src_w * s, src_h * s
        ox, oy = (cw - iw) / 2, (ch - ih) / 2
    return Placement(cw, ch, pw, ph, s, ox, oy, dpi, orient, t.fit, margin, bleed_px)


def needed_scale(targets: list[OutputTarget], src_w: int, src_h: int) -> float:
    en = [t for t in targets if t.enabled] or targets
    return max((place(t, src_w, src_h).scale for t in en), default=1.0)
