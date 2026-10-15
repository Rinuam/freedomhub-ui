"""The processing pipeline for one image.

    load -> prepare (fit to A1, upscale, resample, margin) -> detect_text
         -> [review: edit boxes] -> export (inpaint, PDF + PNG + report)
"""
from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageOps

from . import __version__, APP_NAME
from .config import Settings, PT_PER_INCH, MM_PER_INCH
from .fonts import default_font_id, fitz_font, font_by_id
from .inpaint import inpaint_region
from .layout import Layout, compute_layout, compose_canvas, sample_edge_colour
from .ocr import backend_name, detect_text
from .textstyle import analyse_box
from .upscale import resample, upscale

Image.MAX_IMAGE_PIXELS = 400_000_000   # A1 @ 300 dpi is ~70 MP; allow headroom

Progress = Callable[[str, float], None]   # (stage message, 0..1)

SIDE_CAR_SUFFIX = ".tfe.json"


def _noop(msg: str, frac: float) -> None:
    pass


@dataclass
class TextBox:
    id: int
    text: str
    ocr_text: str
    x: float               # source px, top-left origin
    y: float
    w: float
    h: float
    confidence: float
    vectorise: bool = False
    font_id: str = ""
    size_pt: Optional[float] = None   # None = auto-fit to the detected ink
    colour: tuple[int, int, int] = (0, 0, 0)
    align: str = "center"             # center | left | right (anchor on detected ink)
    bold_guess: bool = False
    mask_grow: float = 1.0
    ink: tuple[float, float, float, float] | None = None   # x0, y0, x1, y1 source px

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TextBox":
        d = dict(d)
        d["colour"] = tuple(d.get("colour", (0, 0, 0)))
        if d.get("ink") is not None:
            d["ink"] = tuple(d["ink"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@lru_cache(maxsize=4096)
def ink_metrics(font_id: str, text: str) -> tuple[float, float, float, float]:
    """Ink bounds (l, t, r, b) of ``text`` at font size 1, relative to the baseline origin.

    Measured by rendering with MuPDF - the same engine that draws the PDF - so the fit
    matches the output exactly (side bearings, overshoots, missing-glyph fallbacks).
    """
    import pymupdf
    font = fitz_font(font_id)
    size, zoom = 300.0, 2.0
    adv = max(1.0, font.text_length(text, size))
    margin = size
    doc = pymupdf.open()
    page = doc.new_page(width=adv + 2 * margin, height=3 * size)
    ox, oy = margin, 2 * size
    tw = pymupdf.TextWriter(page.rect)
    tw.append((ox, oy), text, font=font, fontsize=size)
    tw.write_text(page)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    ys, xs = np.nonzero(a < 128)
    if xs.size == 0:     # whitespace only
        return 0.0, -0.7, adv / size, 0.0
    k = 1.0 / (zoom * size)
    return ((xs.min() - ox * zoom) * k, (ys.min() - oy * zoom) * k,
            (xs.max() + 1 - ox * zoom) * k, (ys.max() + 1 - oy * zoom) * k)


@dataclass
class Placement:
    """Resolved vector text for the PDF, in points (top-left origin)."""
    text: str
    font_id: str
    size_pt: float
    x_pt: float
    baseline_pt: float
    colour: tuple[int, int, int]
    missing_glyphs: str = ""


@dataclass
class Project:
    source_path: Path
    settings: Settings = field(default_factory=Settings)
    src: Optional[np.ndarray] = None
    layout: Optional[Layout] = None
    edge_colour: tuple[int, int, int] = (255, 255, 255)
    upscale_method: str = ""
    upscale_factor: int = 1
    canvas: Optional[np.ndarray] = None       # 300 dpi, upscaled, text still in raster
    boxes: list[TextBox] = field(default_factory=list)
    ocr_backend: str = ""
    timings: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ load
    def load(self) -> None:
        im = Image.open(self.source_path)
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P") and ("transparency" in im.info or im.mode != "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        self.src = np.ascontiguousarray(np.asarray(im.convert("RGB")))
        h, w = self.src.shape[:2]
        s = self.settings
        self.layout = compute_layout(w, h, s.orientation, s.margin_mm, s.dpi)
        self.edge_colour = sample_edge_colour(self.src)

    # --------------------------------------------------------------- prepare
    def prepare(self, progress: Progress = _noop) -> None:
        """Upscale, resample to 300 dpi and place on the A1 canvas."""
        if self.src is None:
            self.load()
        lay = self.layout
        t0 = time.time()
        progress("Upscaling with Real-ESRGAN…", 0.0)
        res = upscale(self.src, lay.place_w / lay.src_w, self.settings.upscale,
                      self.settings.upscale_model, self.settings.realesrgan_path,
                      self.settings.upscale_tile,
                      lambda f: progress("Upscaling with Real-ESRGAN…", 0.85 * f))
        self.upscale_method, self.upscale_factor = res.method, res.factor
        self.timings["upscale_s"] = round(time.time() - t0, 1)
        progress(f"Resampling to {lay.dpi} dpi…", 0.88)
        placed = resample(res.image, lay.place_w, lay.place_h)
        del res
        self.canvas = compose_canvas(placed, lay, self.edge_colour)
        self.timings["prepare_s"] = round(time.time() - t0, 1)
        progress("Canvas ready", 1.0)

    # ------------------------------------------------------------------- OCR
    def detect_text(self, progress: Progress = _noop) -> None:
        if self.src is None:
            self.load()
        progress("Detecting text…", 0.0)
        t0 = time.time()
        h, w = self.src.shape[:2]
        # OCR the decoded, EXIF-oriented, alpha-flattened pixels (not the raw file), so
        # box coordinates are in exactly the frame the rest of the pipeline uses.
        import tempfile
        with tempfile.TemporaryDirectory(prefix="tfe_ocr_") as td:
            tmp = Path(td) / "ocr.png"
            Image.fromarray(self.src).save(tmp, compress_level=1)
            lines = detect_text(tmp, w, h, self.settings.ocr_languages,
                                self.settings.ocr_min_confidence)
        self.ocr_backend = backend_name()
        self.boxes = []
        for i, ln in enumerate(lines):
            b = TextBox(i, ln.text, ln.text, ln.x, ln.y, ln.w, ln.h, ln.confidence)
            self._analyse(b)
            b.font_id = self.settings.default_font or default_font_id(bold=b.bold_guess)
            b.vectorise = self._default_vectorise(b)
            self.boxes.append(b)
        self.timings["ocr_s"] = round(time.time() - t0, 1)
        progress(f"{len(self.boxes)} text boxes found", 1.0)

    def _default_vectorise(self, b: TextBox) -> bool:
        mode = self.settings.batch_vectorise
        if mode == "all":
            return True
        if mode == "none":
            return False
        return b.confidence >= 0.6 and len(b.text.strip()) >= 2

    def _analyse(self, b: TextBox) -> None:
        a = analyse_box(self.src, b.x, b.y, b.w, b.h)
        b.colour = a.text_rgb
        b.bold_guess = a.bold
        b.ink = self._ink_box(a, b)

    def _ink_box(self, a, b: TextBox):
        import cv2
        m = cv2.morphologyEx(a.core.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        ys, xs = np.nonzero(m)
        if xs.size < 5:
            return (b.x, b.y, b.x + b.w, b.y + b.h)
        x0, x1 = xs.min() + a.crop_x, xs.max() + 1 + a.crop_x
        y0, y1 = ys.min() + a.crop_y, ys.max() + 1 + a.crop_y
        # Clamp to a modest neighbourhood of the OCR box (masks can catch nearby art).
        px, py = 0.1 * b.h, 0.25 * b.h
        x0, x1 = max(x0, b.x - px), min(x1, b.x + b.w + px)
        y0, y1 = max(y0, b.y - py), min(y1, b.y + b.h + py)
        return (float(x0), float(y0), float(x1), float(y1))

    def text_mask(self, b: TextBox):
        a = analyse_box(self.src, b.x, b.y, b.w, b.h)
        return a.mask, a.crop_x, a.crop_y

    # ------------------------------------------------------------ placement
    def place(self, b: TextBox) -> Placement:
        lay = self.layout
        k = PT_PER_INCH / lay.dpi                          # canvas px -> pt
        ix0, iy0, ix1, iy1 = b.ink or (b.x, b.y, b.x + b.w, b.y + b.h)
        X0, Y0 = lay.src_to_canvas(ix0, iy0)
        X1, Y1 = lay.src_to_canvas(ix1, iy1)
        x0, y0, x1, y1 = X0 * k, Y0 * k, X1 * k, Y1 * k     # ink box in pt

        text = b.text
        fid = b.font_id or default_font_id(b.bold_guess)
        ref = 1000
        l, t, r, bt = (v * ref for v in ink_metrics(fid, text))
        ink_w, ink_h = max(1e-3, r - l), max(1e-3, bt - t)
        if b.size_pt:
            size = float(b.size_pt)
        else:
            size_w = (x1 - x0) / ink_w * ref
            size_h = (y1 - y0) / ink_h * ref
            size = min(size_w, size_h * 1.15)
        f = size / ref
        if b.align == "left":
            xo = x0 - l * f
        elif b.align == "right":
            xo = x1 - r * f
        else:
            xo = (x0 + x1) / 2 - (l + r) / 2 * f
        base = (y0 + y1) / 2 - (t + bt) / 2 * f
        font = fitz_font(fid)
        missing = "".join(sorted({c for c in text if not c.isspace() and not font.has_glyph(ord(c))}))
        return Placement(text, fid, round(size, 2), xo, base, b.colour, missing)

    # ---------------------------------------------------------------- render
    def final_raster(self, progress: Progress = _noop) -> np.ndarray:
        """Canvas with vectorised text inpainted out."""
        out = self.canvas.copy()
        vec = [b for b in self.boxes if b.vectorise and b.text.strip()]
        for i, b in enumerate(vec):
            progress(f"Inpainting text {i + 1}/{len(vec)}…", i / max(1, len(vec)))
            mask, mx, my = self.text_mask(b)
            inpaint_region(out, mask, mx, my, self.layout, self.settings.inpaint_method, b.mask_grow)
        return out

    def placements(self) -> list[Placement]:
        return [self.place(b) for b in self.boxes if b.vectorise and b.text.strip()]

    def _write_text(self, page, placements: list[Placement]) -> None:
        import pymupdf
        for p in placements:
            tw = pymupdf.TextWriter(page.rect, color=tuple(c / 255 for c in p.colour))
            tw.append((p.x_pt, p.baseline_pt), p.text, font=fitz_font(p.font_id), fontsize=p.size_pt)
            tw.write_text(page)

    def build_pdf(self, raster: np.ndarray, placements: list[Placement]):
        import pymupdf
        lay = self.layout
        doc = pymupdf.open()
        page = doc.new_page(width=lay.page_w_pt, height=lay.page_h_pt)
        buf = io.BytesIO()
        im = Image.fromarray(raster)
        if self.settings.pdf_background == "lossless":
            im.save(buf, "PNG", compress_level=6)
        else:
            im.save(buf, "JPEG", quality=self.settings.jpeg_quality, subsampling=0,
                    optimize=True, dpi=(lay.dpi, lay.dpi))
        page.insert_image(page.rect, stream=buf.getvalue())
        self._write_text(page, placements)
        doc.set_metadata({"title": self.source_path.stem, "creator": f"{APP_NAME} {__version__}",
                          "producer": f"{APP_NAME} {__version__} / PyMuPDF"})
        doc.subset_fonts()
        return doc

    def render_text_layer(self, placements: list[Placement]) -> Optional[np.ndarray]:
        """RGBA canvas-sized rendering of only the vector text (exactly as in the PDF)."""
        if not placements:
            return None
        import pymupdf
        lay = self.layout
        doc = pymupdf.open()
        page = doc.new_page(width=lay.page_w_pt, height=lay.page_h_pt)
        self._write_text(page, placements)
        m = pymupdf.Matrix(lay.canvas_w / lay.page_w_pt, lay.canvas_h / lay.page_h_pt)
        pix = page.get_pixmap(matrix=m, alpha=True)
        arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 4)
        if (pix.width, pix.height) != (lay.canvas_w, lay.canvas_h):
            import cv2
            arr = cv2.resize(arr, (lay.canvas_w, lay.canvas_h), interpolation=cv2.INTER_LINEAR)
        return arr

    @staticmethod
    def flatten(raster: np.ndarray, text_rgba: Optional[np.ndarray]) -> np.ndarray:
        if text_rgba is None:
            return raster
        # MuPDF pixmaps with alpha are premultiplied: out = bg * (1 - a) + rgb.
        # Work in row strips and skip strips without text (A1 is ~70 MP).
        out = raster.copy()
        alpha = text_rgba[..., 3]
        rows = np.flatnonzero(alpha.any(axis=1))
        if rows.size == 0:
            return out
        step = 256
        for y0 in range(rows[0], rows[-1] + 1, step):
            y1 = min(y0 + step, rows[-1] + 1)
            a = alpha[y0:y1]
            cols = np.flatnonzero(a.any(axis=0))
            if cols.size == 0:
                continue
            x0, x1 = cols[0], cols[-1] + 1
            a16 = a[:, x0:x1, None].astype(np.uint16)
            bg = out[y0:y1, x0:x1].astype(np.uint16)
            fg = text_rgba[y0:y1, x0:x1, :3].astype(np.uint16)
            v = (bg * (255 - a16) + 127) // 255 + fg
            out[y0:y1, x0:x1] = np.minimum(v, 255).astype(np.uint8)
        return out

    def naive_before(self) -> np.ndarray:
        """What plain bicubic scaling would print, for the comparison view."""
        import cv2
        lay = self.layout
        placed = cv2.resize(self.src, (lay.place_w, lay.place_h), interpolation=cv2.INTER_CUBIC)
        return compose_canvas(placed, lay, self.edge_colour)

    # ---------------------------------------------------------------- render
    def _render_key(self) -> str:
        boxes = [(b.text, b.x, b.y, b.w, b.h, b.font_id, b.size_pt, b.colour, b.align,
                  b.mask_grow, b.ink) for b in self.boxes if b.vectorise and b.text.strip()]
        return json.dumps([boxes, self.settings.inpaint_method, id(self.canvas)], default=str)

    def render(self, progress: Progress = _noop):
        """(raster_without_text, placements, flattened) — cached until boxes change."""
        key = self._render_key()
        cached = getattr(self, "_render_cache", None)
        if cached and cached[0] == key:
            return cached[1]
        raster = self.final_raster(lambda m, f: progress(m, 0.8 * f))
        placements = self.placements()
        progress("Rendering vector text…", 0.85)
        flat = self.flatten(raster, self.render_text_layer(placements))
        self._render_cache = (key, (raster, placements, flat))
        progress("Preview ready", 1.0)
        return raster, placements, flat

    # ---------------------------------------------------------------- export
    def export(self, out_dir: Path, progress: Progress = _noop) -> dict:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = self.source_path.stem
        t0 = time.time()
        raster, placements, flat = self.render(lambda m, f: progress(m, 0.5 * f))
        progress("Writing PDF…", 0.55)
        pdf_path = out_dir / f"{stem}_A1.pdf"
        doc = self.build_pdf(raster, placements)
        doc.save(pdf_path, garbage=3, deflate=True)
        doc.close()
        png_path = out_dir / f"{stem}_A1_{self.layout.dpi}dpi.png"
        progress("Writing PNG…", 0.75)
        Image.fromarray(flat).save(png_path, dpi=(self.layout.dpi, self.layout.dpi),
                                   compress_level=6)
        self.timings["export_s"] = round(time.time() - t0, 1)
        report = self.dpi_report(placements)
        report["outputs"] = {"pdf": str(pdf_path), "png": str(png_path)}
        (out_dir / f"{stem}_report.json").write_text(json.dumps(report, indent=2))
        (out_dir / f"{stem}_report.txt").write_text(format_report(report))
        self.save_sidecar(out_dir / f"{stem}{SIDE_CAR_SUFFIX}")
        progress("Done", 1.0)
        return report

    # ---------------------------------------------------------------- report
    def dpi_report(self, placements: Optional[list[Placement]] = None) -> dict:
        lay = self.layout
        pw_in = lay.place_w / lay.dpi
        ph_in = lay.place_h / lay.dpi
        native = lay.src_w / pw_in
        up_px = (lay.src_w * self.upscale_factor, lay.src_h * self.upscale_factor)
        up_ppi = up_px[0] / pw_in
        effective = min(up_ppi, lay.dpi)
        if placements is None:
            placements = self.placements() if self.canvas is not None else []

        def verdict(ppi):
            if ppi >= 250:
                return "excellent - fine at reading distance"
            if ppi >= 150:
                return "good - fine at arm's length (~0.5 m)"
            if ppi >= 100:
                return "acceptable for a poster viewed from ~1 m"
            return "low - pixels visible closer than ~1.5 m"

        def dist_m(ppi):   # 1 arc-minute acuity: d = 3438 / ppi inches
            return round(3438 / ppi * MM_PER_INCH / 1000, 2)

        return {
            "app": f"{APP_NAME} {__version__}",
            "source": str(self.source_path),
            "source_px": [lay.src_w, lay.src_h],
            "page": {"format": "A1", "orientation": lay.orientation,
                     "mm": [lay.page_w_mm, lay.page_h_mm], "margin_mm": lay.margin_mm,
                     "margin_rgb": list(self.edge_colour)},
            "image_area_mm": [round(pw_in * MM_PER_INCH, 1), round(ph_in * MM_PER_INCH, 1)],
            "output_px": [lay.canvas_w, lay.canvas_h],
            "output_dpi": lay.dpi,
            "native_ppi": round(native, 1),
            "native_verdict": verdict(native),
            "native_min_view_distance_m": dist_m(native),
            "upscale": {"method": self.upscale_method, "factor": self.upscale_factor,
                        "px": list(up_px), "ppi": round(up_ppi, 1)},
            "effective_ppi": round(effective, 1),
            "effective_verdict": verdict(effective),
            "effective_min_view_distance_m": dist_m(effective),
            "resample_factor_after_upscale": round(lay.place_w / up_px[0], 3),
            "ocr_backend": self.ocr_backend,
            "text_boxes": len(self.boxes),
            "vector_text_boxes": len(placements),
            "vector_text": [{"text": p.text, "font": (font_by_id(p.font_id).label
                                                      if font_by_id(p.font_id) else p.font_id),
                             "size_pt": p.size_pt,
                             "missing_glyphs": p.missing_glyphs} for p in placements],
            "timings_s": self.timings,
        }

    # --------------------------------------------------------------- sidecar
    def save_sidecar(self, path: Path) -> None:
        data = {"version": __version__, "source": str(self.source_path),
                "settings": self.settings.to_dict(),
                "boxes": [b.to_dict() for b in self.boxes]}
        Path(path).write_text(json.dumps(data, indent=2))

    def load_sidecar(self, path: Path) -> bool:
        try:
            data = json.loads(Path(path).read_text())
        except Exception:
            return False
        self.boxes = [TextBox.from_dict(d) for d in data.get("boxes", [])]
        return True


def format_report(r: dict) -> str:
    up = r["upscale"]
    lines = [
        f"{r['app']} - resolution report",
        f"Source:            {r['source']}",
        f"Source pixels:     {r['source_px'][0]} x {r['source_px'][1]}",
        f"Page:              A1 {r['page']['orientation']} {r['page']['mm'][0]:g} x {r['page']['mm'][1]:g} mm, "
        f"margin {r['page']['margin_mm']:g} mm, colour RGB{tuple(r['page']['margin_rgb'])}",
        f"Image area:        {r['image_area_mm'][0]} x {r['image_area_mm'][1]} mm (no crop, no stretch)",
        f"Output:            {r['output_px'][0]} x {r['output_px'][1]} px @ {r['output_dpi']} dpi",
        "",
        f"Native ppi:        {r['native_ppi']}  -> {r['native_verdict']}",
        f"                   pixels resolvable closer than {r['native_min_view_distance_m']} m",
        f"Upscale:           {up['method']} -> {up['px'][0]} x {up['px'][1]} px ({up['ppi']} ppi)",
        f"Effective ppi:     {r['effective_ppi']}  -> {r['effective_verdict']}",
        f"                   (detail above native is AI-reconstructed, not captured)",
        f"Final resample:    x{r['resample_factor_after_upscale']} after upscale",
        "",
        f"OCR backend:       {r['ocr_backend']}",
        f"Text boxes:        {r['text_boxes']} detected, {r['vector_text_boxes']} vectorised "
        f"(resolution-independent in the PDF)",
    ]
    for v in r["vector_text"]:
        warn = f"  !! missing glyphs: {v['missing_glyphs']}" if v["missing_glyphs"] else ""
        lines.append(f"   - \"{v['text']}\"  {v['font']} {v['size_pt']} pt{warn}")
    if r.get("timings_s"):
        lines.append("")
        lines.append("Timings (s):       " + ", ".join(f"{k}={v}" for k, v in r["timings_s"].items()))
    return "\n".join(lines) + "\n"
