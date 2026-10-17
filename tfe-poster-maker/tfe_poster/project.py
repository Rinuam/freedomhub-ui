"""One poster project: source image -> AI master -> cleaned master -> outputs.

    load ─► detect_text ─► enhance (AI, up to 16x, disk-cached)
                       └─► edit text blocks / erase regions
    clean  : LaMa removes original text on the *source*, the cleaned regions are
             re-enhanced with the same model and blended into the master
    render : per output target (A-sizes, social, 4K…): resample master, apply
             tone/detail adjustments, soft shadows, vector text
    export : PDF (raster + vector text, searchable) and PNG/JPEG/TIFF/WebP
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
from PIL import Image, ImageOps

from . import APP_NAME, __version__
from .enhance import adjust as adj
from .enhance.pipeline import EnhanceSettings, Enhancer, choose_factor, resolve_auto
from .enhance.zoo import BY_ID
from .fonts import default_font_id, font_by_id
from .formats import (DEFAULT_TARGETS, MM_PER_INCH, OutputTarget, Placement, needed_scale, place)
from .inpaint import inpaint, method_name
from .layout import sample_edge_colour
from .ocr import backend_name, detect_text
from .text.engine import autofit, layout
from .text.model import EraseRegion, TextBlock
from .text.render import (composite_premul, draw_pdf, draw_search_layer, soft_shadow_layer)
from .textstyle import analyse_box

Image.MAX_IMAGE_PIXELS = 2_000_000_000
Progress = Callable[[str, float], None]
PROJECT_SUFFIX = ".tfe.json"


def _noop(m, f):
    pass


def cache_dir() -> Path:
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Caches" / "TFE Poster Maker"
    else:
        d = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "tfe-poster-maker"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _prune_cache(limit_gb: float = 12.0) -> None:
    files = sorted(cache_dir().glob("*.npy"), key=lambda p: p.stat().st_atime)
    total = sum(p.stat().st_size for p in files)
    while files and total > limit_gb * 1e9:
        p = files.pop(0)
        total -= p.stat().st_size
        p.unlink(missing_ok=True)


def parse_colour(s: str, edge) -> tuple[int, int, int]:
    if s == "edge":
        return tuple(edge)
    if s == "white":
        return (255, 255, 255)
    if s == "black":
        return (0, 0, 0)
    if s.startswith("#") and len(s) == 7:
        return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(edge)


@dataclass
class Rendered:
    target: OutputTarget
    placement: Placement
    background: np.ndarray        # canvas RGB without vector text (incl. soft shadows)
    flat: np.ndarray              # canvas RGB with vector text


@dataclass
class Project:
    source_path: Path
    enhance: EnhanceSettings = field(default_factory=EnhanceSettings)
    targets: list[OutputTarget] = field(default_factory=lambda: [OutputTarget.from_dict(t.to_dict())
                                                                  for t in DEFAULT_TARGETS])
    blocks: list[TextBlock] = field(default_factory=list)
    erase_regions: list[EraseRegion] = field(default_factory=list)
    inpaint_method: str = "auto"
    ocr_languages: list[str] = field(default_factory=lambda: ["en-US", "es-ES", "ca-ES", "fr-FR", "de-DE"])
    ocr_min_confidence: float = 0.3
    default_vectorise: str = "auto"     # auto | all | none
    src: Optional[np.ndarray] = None
    edge_colour: tuple = (255, 255, 255)
    ocr_backend: str = ""
    master: Optional[np.ndarray] = None
    master_factor: int = 0
    master_info: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ load
    def load(self) -> None:
        im = ImageOps.exif_transpose(Image.open(self.source_path))
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        self.src = np.ascontiguousarray(np.asarray(im.convert("RGB")))
        self.edge_colour = sample_edge_colour(self.src)
        self._src_hash = hashlib.sha1(self.src.tobytes()).hexdigest()[:16]
        self._clean_cache = None

    @property
    def size(self) -> tuple[int, int]:
        return self.src.shape[1], self.src.shape[0]

    # ------------------------------------------------------------- text OCR
    def detect_text(self, progress: Progress = _noop) -> None:
        import tempfile
        progress("Detecting text…", 0.0)
        t0 = time.time()
        w, h = self.size
        with tempfile.TemporaryDirectory(prefix="tfe_ocr_") as td:
            tmp = Path(td) / "ocr.png"
            Image.fromarray(self.src).save(tmp, compress_level=1)
            lines = detect_text(tmp, w, h, self.ocr_languages, self.ocr_min_confidence)
        self.ocr_backend = backend_name()
        self.blocks = []
        for i, ln in enumerate(lines):
            b = TextBlock(i, ln.text, ln.text, ln.confidence, box=(ln.x, ln.y, ln.w, ln.h))
            self._analyse(b)
            b.font_id = default_font_id(b.bold_guess)
            b.vectorise = b.erase = self._default_vectorise(b)
            autofit(b)
            self.blocks.append(b)
        self.timings["ocr_s"] = round(time.time() - t0, 1)
        progress(f"{len(self.blocks)} text lines found", 1.0)

    def _default_vectorise(self, b: TextBlock) -> bool:
        if self.default_vectorise == "all":
            return True
        if self.default_vectorise == "none":
            return False
        return b.confidence >= 0.6 and len(b.text.strip()) >= 2

    def _analyse(self, b: TextBlock) -> None:
        x, y, w, h = b.box
        a = analyse_box(self.src, x, y, w, h)
        b.fill = a.text_rgb
        b.bold_guess = a.bold
        m = cv2.morphologyEx(a.core.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        ys, xs = np.nonzero(m)
        if xs.size < 5:
            b.ink = (x, y, x + w, y + h)
            return
        x0, x1 = xs.min() + a.crop_x, xs.max() + 1 + a.crop_x
        y0, y1 = ys.min() + a.crop_y, ys.max() + 1 + a.crop_y
        px, py = 0.1 * h, 0.25 * h
        b.ink = (float(max(x0, x - px)), float(max(y0, y - py)),
                 float(min(x1, x + w + px)), float(min(y1, y + h + py)))

    def new_block(self, x: float, y: float, text: str = "New text") -> TextBlock:
        nid = max([b.id for b in self.blocks], default=-1) + 1
        ref = next((b for b in self.blocks if b.vectorise), None)
        b = TextBlock(nid, text, "", 1.0, vectorise=True, erase=False, auto_fit=False,
                      size=max(12.0, self.size[1] / 25), cx=x, cy=y, user_added=True,
                      font_id=ref.font_id if ref else default_font_id(True),
                      fill=ref.fill if ref else (20, 20, 20))
        self.blocks.append(b)
        return b

    def merge_blocks(self, ids: list[int]) -> Optional[TextBlock]:
        sel = sorted([b for b in self.blocks if b.id in ids], key=lambda b: (b.cy, b.cx))
        if len(sel) < 2:
            return None
        first = sel[0]
        first.text = "\n".join(b.text for b in sel)
        first.ocr_text = "\n".join(b.ocr_text for b in sel)
        first.erase_boxes = [tuple(b.box) for b in sel] + [e for b in sel for e in b.erase_boxes]
        first.size = float(np.median([b.size for b in sel]))
        gaps = [sel[i + 1].cy - sel[i].cy for i in range(len(sel) - 1)]
        first.line_height = float(np.clip(np.median(gaps) / max(1e-3, first.size), 0.8, 3.0))
        inks = [b.ink or (b.box[0], b.box[1], b.box[0] + b.box[2], b.box[1] + b.box[3]) for b in sel]
        first.ink = (min(i[0] for i in inks), min(i[1] for i in inks),
                     max(i[2] for i in inks), max(i[3] for i in inks))
        first.cx, first.cy = (first.ink[0] + first.ink[2]) / 2, (first.ink[1] + first.ink[3]) / 2
        first.auto_fit = False
        self.blocks = [b for b in self.blocks if b is first or b.id not in ids]
        return first

    # ------------------------------------------------------------- erasing
    def block_mask(self, b: TextBlock) -> tuple[np.ndarray, int, int]:
        """Inpainting mask for a block's original text: strokes, grown and closed into word blobs."""
        boxes = [b.box] + list(b.erase_boxes)
        H, W = self.src.shape[:2]
        x0 = int(max(0, min(bx[0] for bx in boxes) - 0.6 * max(bx[3] for bx in boxes)))
        y0 = int(max(0, min(bx[1] for bx in boxes) - 0.6 * max(bx[3] for bx in boxes)))
        x1 = int(min(W, max(bx[0] + bx[2] for bx in boxes) + 0.6 * max(bx[3] for bx in boxes)))
        y1 = int(min(H, max(bx[1] + bx[3] for bx in boxes) + 0.6 * max(bx[3] for bx in boxes)))
        out = np.zeros((y1 - y0, x1 - x0), np.uint8)
        for (x, y, w, h) in boxes:
            a = analyse_box(self.src, x, y, w, h)
            m = a.mask
            k = max(2, int(round(h * 0.08 * b.erase_mask_grow)))
            m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))
            c = max(3, int(h * 0.6))
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (c, c)))
            ox, oy = a.crop_x - x0, a.crop_y - y0
            sub = out[max(0, oy):oy + m.shape[0], max(0, ox):ox + m.shape[1]]
            sub |= m[max(0, -oy):max(0, -oy) + sub.shape[0], max(0, -ox):max(0, -ox) + sub.shape[1]]
        return out, x0, y0

    def erase_mask(self) -> np.ndarray:
        H, W = self.src.shape[:2]
        mask = np.zeros((H, W), np.uint8)
        for b in self.blocks:
            if b.erase and not b.user_added:
                m, x0, y0 = self.block_mask(b)
                mask[y0:y0 + m.shape[0], x0:x0 + m.shape[1]] |= m
        for r in self.erase_regions:
            x0, y0 = int(max(0, r.x)), int(max(0, r.y))
            x1, y1 = int(min(W, r.x + r.w)), int(min(H, r.y + r.h))
            mask[y0:y1, x0:x1] = 255
        return mask

    # ------------------------------------------------------------- enhance
    def target_factor(self) -> int:
        w, h = self.size
        need = needed_scale(self.targets, w, h)
        enh = Enhancer(self.enhance, self.src)
        return choose_factor(self.enhance.factor, need, enh.model_scale if enh.backend == "torch" else 4,
                             self.enhance.max_factor)

    def _master_key(self, settings: EnhanceSettings, factor: int) -> str:
        blob = json.dumps([self._src_hash, settings.cache_key(), factor], sort_keys=True)
        return hashlib.sha1(blob.encode()).hexdigest()[:20]

    def run_enhance(self, progress: Progress = _noop, should_stop=lambda: False,
                    factor: Optional[int] = None) -> None:
        t0 = time.time()
        enh = Enhancer(self.enhance, self.src)
        self._resolved = enh.s
        f = factor or self.target_factor()
        key = self._master_key(enh.s, f)
        cp = cache_dir() / f"{key}.npy"
        if cp.is_file():
            try:
                progress("Loading cached enhancement…", 0.5)
                self.master = np.load(cp, mmap_mode=None)
                self.master_factor = f
                self.master_info = json.loads(cp.with_suffix(".json").read_text())
                self.master_info["cached"] = True
                self._clean_cache = None
                progress("Enhancement loaded from cache", 1.0)
                return
            except Exception:
                pass
        res = enh.run(self.src, f, progress, should_stop)
        self.master, self.master_factor = res.image, f
        self.master_info = {"method": res.method, "passes": res.passes, "faces": res.faces,
                            "seconds": round(res.seconds, 1), "factor": f, "backend": enh.backend,
                            "auto": enh.auto_reason, "cached": False}
        self._clean_cache = None
        self.timings["enhance_s"] = round(time.time() - t0, 1)
        try:
            np.save(cp, self.master)
            cp.with_suffix(".json").write_text(json.dumps(self.master_info))
            _prune_cache()
        except Exception:
            pass

    # --------------------------------------------------------------- clean
    def clean(self, progress: Progress = _noop, should_stop=lambda: False):
        """(clean_src, clean_master or None). Cached until masks/model change."""
        mask = self.erase_mask()
        key = (hashlib.sha1(mask.tobytes()).hexdigest(), self.inpaint_method, self.master_factor,
               id(self.master))
        if self._clean_cache and self._clean_cache[0] == key:
            return self._clean_cache[1], self._clean_cache[2]
        if not mask.any():
            self._clean_cache = (key, self.src, self.master)
            return self.src, self.master
        progress(f"Removing original text ({method_name(self.inpaint_method)})…", 0.05)
        clean_src = inpaint(self.src, mask, self.inpaint_method)
        clean_master = None
        if self.master is not None:
            clean_master = self.master.copy()
            F = self.master_factor
            enh = Enhancer(getattr(self, "_resolved", self.enhance), self.src)
            from .inpaint import _clusters
            boxes = _clusters(mask, 12)
            H, W = self.src.shape[:2]
            for i, (x0, y0, x1, y1) in enumerate(boxes):
                if should_stop():
                    break
                progress(f"Re-enhancing cleaned area {i + 1}/{len(boxes)}…", 0.2 + 0.8 * i / max(1, len(boxes)))
                pad = 24
                cx0, cy0, cx1, cy1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
                region = enh.run_region(clean_src[cy0:cy1, cx0:cx1], F, should_stop)
                m = mask[cy0:cy1, cx0:cx1]
                m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
                mF = cv2.resize(m, (region.shape[1], region.shape[0]), interpolation=cv2.INTER_LINEAR)
                a = cv2.GaussianBlur(mF.astype(np.float32) / 255.0, (0, 0), max(1.0, F * 1.5))
                a = np.maximum(a, (mF > 127).astype(np.float32))[..., None]
                dst = clean_master[cy0 * F:cy0 * F + region.shape[0], cx0 * F:cx0 * F + region.shape[1]]
                region = _match_tone(region[:dst.shape[0], :dst.shape[1]], dst, mF[:dst.shape[0], :dst.shape[1]], F)
                a = a[:dst.shape[0], :dst.shape[1]]
                dst[:] = np.clip(dst * (1 - a) + region * a + 0.5, 0, 255).astype(np.uint8)
        self._clean_cache = (key, clean_src, clean_master)
        progress("Text removed", 1.0)
        return clean_src, clean_master

    # -------------------------------------------------------------- render
    def adjusted_edge_colour(self) -> tuple:
        small, _ = _down(self.src, 512)
        return sample_edge_colour(adj.apply(small, self.enhance.adjust, 512 / max(self.size)))

    def render_target(self, t: OutputTarget, progress: Progress = _noop, should_stop=lambda: False,
                      text: bool = True) -> Rendered:
        sw, sh = self.size
        pl = place(t, sw, sh)
        clean_src, clean_master = self.clean(lambda m, f: progress(m, 0.3 * f), should_stop)
        base = clean_master if clean_master is not None else clean_src
        F = self.master_factor if clean_master is not None else 1
        progress(f"Rendering {t.name}…", 0.35)
        cw, ch = pl.canvas_w, pl.canvas_h
        edge = self.adjusted_edge_colour()
        canvas = np.empty((ch, cw, 3), np.uint8)
        if t.fit == "extend":
            small, k = _down(clean_src, 640)
            s2 = max(cw / small.shape[1], ch / small.shape[0])
            bw, bh = int(np.ceil(small.shape[1] * s2)), int(np.ceil(small.shape[0] * s2))
            lowk = min(1.0, 900 / max(cw, ch))
            low = cv2.resize(small, (max(1, int(bw * lowk)), max(1, int(bh * lowk))), interpolation=cv2.INTER_LINEAR)
            low = cv2.GaussianBlur(low, (0, 0), max(2.0, 0.035 * max(low.shape[:2])))
            low = adj.apply(low, self.enhance.adjust, lowk * s2 / k)
            big = cv2.resize(low, (bw, bh), interpolation=cv2.INTER_CUBIC)
            ox, oy = (bw - cw) // 2, (bh - ch) // 2
            canvas[:] = (big[oy:oy + ch, ox:ox + cw].astype(np.float32) * 0.92).astype(np.uint8)
        else:
            canvas[:] = parse_colour(t.background, edge)
        # visible part of the image
        ix0, iy0, ix1, iy1 = pl.image_rect(sw, sh)
        vx0, vy0 = max(0.0, ix0), max(0.0, iy0)
        vx1, vy1 = min(float(cw), ix1), min(float(ch), iy1)
        X0, Y0, X1, Y1 = int(round(vx0)), int(round(vy0)), int(round(vx1)), int(round(vy1))
        if X1 > X0 and Y1 > Y0:
            # corresponding source rect -> base rect
            s0x, s0y = (X0 - pl.off_x) / pl.scale, (Y0 - pl.off_y) / pl.scale
            s1x, s1y = (X1 - pl.off_x) / pl.scale, (Y1 - pl.off_y) / pl.scale
            bx0, by0 = s0x * F, s0y * F
            bx1, by1 = s1x * F, s1y * F
            region = _crop_resample(base, bx0, by0, bx1, by1, X1 - X0, Y1 - Y0)
            if should_stop():
                raise InterruptedError()
            progress(f"Adjusting {t.name}…", 0.5)
            region = adj.apply(region, self.enhance.adjust, pl.scale)
            canvas[Y0:Y1, X0:X1] = region
        vec = [b for b in self.blocks if b.vectorise and b.text.strip()] if text else []
        f_px = lambda p: pl.src_to_canvas(p[0], p[1])  # noqa: E731
        progress(f"Shadows {t.name}…", 0.65)
        canvas = composite_premul(canvas, soft_shadow_layer(vec, cw, ch, f_px, pl.scale))
        flat = canvas
        if vec:
            progress(f"Vector text {t.name}…", 0.75)
            flat = composite_premul(canvas, self._text_layer(vec, pl))
        progress(f"{t.name} ready", 1.0)
        return Rendered(t, pl, canvas, flat)

    def _text_layer(self, blocks, pl: Placement, band: int = 2048) -> np.ndarray:
        """Vector text rasterised by MuPDF (exactly as in the PDF), in bands for huge canvases."""
        import pymupdf
        doc = pymupdf.open()
        page = doc.new_page(width=pl.page_w_pt, height=pl.page_h_pt)
        ptps = pl.scale * pl.pt_per_px
        for b in blocks:
            draw_pdf(page, b, pl.src_to_pt, ptps)
        mx, my = pl.canvas_w / pl.page_w_pt, pl.canvas_h / pl.page_h_pt
        out = np.zeros((pl.canvas_h, pl.canvas_w, 4), np.uint8)
        for y0 in range(0, pl.canvas_h, band):
            y1 = min(pl.canvas_h, y0 + band)
            clip = pymupdf.Rect(0, y0 / my, pl.page_w_pt, y1 / my)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(mx, my), clip=clip, alpha=True)
            a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 4)
            hh, ww = min(a.shape[0], y1 - y0), min(a.shape[1], pl.canvas_w)
            out[y0:y0 + hh, :ww] = a[:hh, :ww]
        return out

    # -------------------------------------------------------------- export
    def export(self, out_dir: Path, progress: Progress = _noop, should_stop=lambda: False,
               targets: Optional[list[OutputTarget]] = None) -> dict:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        stem = self.source_path.stem
        targets = [t for t in (targets or self.targets) if t.enabled]
        files, reports, warnings = [], [], []
        for i, t in enumerate(targets):
            base, span = i / len(targets), 1 / len(targets)
            pr = lambda m, f, base=base, span=span: progress(m, base + span * f)  # noqa: E731
            r = self.render_target(t, lambda m, f: pr(m, 0.7 * f), should_stop)
            tag = _slug(t.name)
            for fmt in t.formats:
                if should_stop():
                    raise InterruptedError()
                pr(f"Writing {t.name} {fmt.upper()}…", 0.75)
                path = out_dir / f"{stem}_{tag}.{ 'jpg' if fmt == 'jpeg' else fmt}"
                try:
                    if fmt == "pdf":
                        self._write_pdf(path, r)
                    else:
                        _write_image(path, r.flat, fmt, r.placement.dpi, t.jpeg_quality)
                except ValueError as e:          # e.g. WebP size limit: skip this format only
                    warnings.append(f"{t.name} {fmt.upper()}: {e}")
                    continue
                files.append(str(path))
            reports.append(self.target_report(r))
        rep = self.report(reports)
        rep["outputs"] = files
        rep["warnings"] = warnings
        rep["timings_s"]["export_s"] = round(time.time() - t0, 1)
        (out_dir / f"{stem}_report.json").write_text(json.dumps(rep, indent=2))
        (out_dir / f"{stem}_report.txt").write_text(format_report(rep))
        self.save(out_dir / f"{stem}{PROJECT_SUFFIX}")
        progress("Export finished", 1.0)
        return rep

    def _write_pdf(self, path: Path, r: Rendered) -> None:
        import pymupdf
        pl, t = r.placement, r.target
        doc = pymupdf.open()
        page = doc.new_page(width=pl.page_w_pt, height=pl.page_h_pt)
        buf = io.BytesIO()
        im = Image.fromarray(r.background)
        if t.pdf_background == "lossless":
            im.save(buf, "PNG", compress_level=6)
        else:
            im.save(buf, "JPEG", quality=t.jpeg_quality, subsampling=0, dpi=(pl.dpi, pl.dpi))
        page.insert_image(page.rect, stream=buf.getvalue())
        ptps = pl.scale * pl.pt_per_px
        for b in self.blocks:
            if b.vectorise and b.text.strip():
                laid = layout(b)
                draw_pdf(page, b, pl.src_to_pt, ptps, laid)
                draw_search_layer(page, b, pl.src_to_pt, ptps, laid)
        if pl.bleed_px:
            bp = pl.bleed_px * pl.pt_per_px
            try:
                page.set_trimbox(pymupdf.Rect(bp, bp, pl.page_w_pt - bp, pl.page_h_pt - bp))
            except Exception:
                pass
        doc.set_metadata({"title": self.source_path.stem, "creator": f"{APP_NAME} {__version__}",
                          "producer": f"{APP_NAME} {__version__} / PyMuPDF"})
        doc.subset_fonts()
        doc.save(path, garbage=3, deflate=True)
        doc.close()

    # -------------------------------------------------------------- report
    def target_report(self, r: Rendered) -> dict:
        pl, t = r.placement, r.target
        sw, sh = self.size
        native = pl.dpi / pl.scale            # source px per output inch
        F = self.master_factor or 1
        ai = min(pl.dpi, native * F)
        d = {"name": t.name, "kind": t.kind, "canvas_px": [pl.canvas_w, pl.canvas_h],
             "dpi": pl.dpi, "fit": t.fit, "formats": t.formats,
             "native_ppi": round(native, 1), "effective_ppi": round(ai, 1),
             "upsample_vs_source": round(pl.scale, 2)}
        if t.kind == "print":
            d["size_mm"] = [round(pl.canvas_w / pl.dpi * MM_PER_INCH, 1), round(pl.canvas_h / pl.dpi * MM_PER_INCH, 1)]
            d["native_view_m"] = round(3438 / max(native, 1e-3) * MM_PER_INCH / 1000, 2)
            d["effective_view_m"] = round(3438 / max(ai, 1e-3) * MM_PER_INCH / 1000, 2)
        return d

    def report(self, targets: list[dict]) -> dict:
        vec = [b for b in self.blocks if b.vectorise and b.text.strip()]
        return {
            "app": f"{APP_NAME} {__version__}", "source": str(self.source_path),
            "source_px": list(self.size),
            "enhancement": self.master_info or {"method": "none"},
            "ai_factor": self.master_factor,
            "text_removal": method_name(self.inpaint_method),
            "ocr_backend": self.ocr_backend,
            "text_blocks": len(self.blocks), "vector_blocks": len(vec),
            "vector_text": [{"text": b.display_text(), "font": (font_by_id(b.font_id).label if font_by_id(b.font_id)
                                                                 else b.font_id),
                             "size_src_px": round(b.size, 1), "missing_glyphs": layout(b).missing}
                            for b in vec],
            "targets": targets, "timings_s": dict(self.timings),
        }

    # ------------------------------------------------------------- persist
    def to_dict(self) -> dict:
        return {"version": __version__, "source": str(self.source_path),
                "enhance": self.enhance.to_dict(), "targets": [t.to_dict() for t in self.targets],
                "blocks": [b.to_dict() for b in self.blocks],
                "erase_regions": [r.to_dict() for r in self.erase_regions],
                "inpaint_method": self.inpaint_method}

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    def load_edits(self, path: Path, settings: bool = True) -> bool:
        try:
            d = json.loads(Path(path).read_text())
        except Exception:
            return False
        self.blocks = [TextBlock.from_dict(b) for b in d.get("blocks", [])]
        self.erase_regions = [EraseRegion(**r) for r in d.get("erase_regions", [])]
        if settings:
            if d.get("enhance"):
                self.enhance = EnhanceSettings.from_dict(d["enhance"])
            if d.get("targets"):
                self.targets = [OutputTarget.from_dict(t) for t in d["targets"]]
            self.inpaint_method = d.get("inpaint_method", self.inpaint_method)
        self._clean_cache = None
        return True

    # ------------------------------------------------------------- preview
    def preview_base(self, max_side: int = 2400, cleaned: bool = False) -> tuple[np.ndarray, float]:
        """(image, preview px per source px)."""
        if cleaned:
            cs, cm = self.clean()
            img, F = (cm, self.master_factor) if cm is not None else (cs, 1)
        else:
            img, F = (self.master, self.master_factor) if self.master is not None else (self.src, 1)
        out, k = _down(img, max_side)
        return out, k * F


def _match_tone(region: np.ndarray, master: np.ndarray, mask: np.ndarray, F: int) -> np.ndarray:
    """Remove the low-frequency colour offset between a re-enhanced crop and the master.

    The offset is measured only on untouched pixels (outside the dilated text mask) and
    spread into the masked area by normalised convolution, so the patch is seamless.
    """
    ring = (mask < 8).astype(np.float32)
    if ring.sum() < 50:
        return region
    diff = (master.astype(np.float32) - region.astype(np.float32)) * ring[..., None]
    sig = max(4.0, 6.0 * F)
    k = 1.0 / max(1.0, sig / 6.0)                     # work at reduced size: blur is smooth anyway
    small = lambda a: cv2.resize(a, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else a  # noqa: E731
    D = cv2.GaussianBlur(small(diff), (0, 0), sig * k)
    W = cv2.GaussianBlur(small(ring), (0, 0), sig * k)
    for _ in range(3):                                # fill holes larger than the kernel
        if (W > 1e-3).all():
            break
        D = cv2.GaussianBlur(D, (0, 0), sig * k * 2)
        W = cv2.GaussianBlur(W, (0, 0), sig * k * 2)
    corr = D / np.maximum(W, 1e-4)[..., None]
    if k < 1:
        corr = cv2.resize(corr, (region.shape[1], region.shape[0]), interpolation=cv2.INTER_LINEAR)
    return np.clip(region.astype(np.float32) + corr, 0, 255)


def _down(img: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    k = min(1.0, max_side / max(h, w))
    if k >= 1.0:
        return img, 1.0
    return cv2.resize(img, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA), k


def _crop_resample(img, x0, y0, x1, y1, out_w, out_h) -> np.ndarray:
    """Resample a float rect of ``img`` to (out_w, out_h) with sub-pixel accuracy."""
    H, W = img.shape[:2]
    sx, sy = (x1 - x0) / out_w, (y1 - y0) / out_h
    shrink = sx > 1.0
    if shrink:
        # integer crop with margin, area resize, then exact sub-pixel warp
        ix0, iy0 = max(0, int(np.floor(x0)) - 2), max(0, int(np.floor(y0)) - 2)
        ix1, iy1 = min(W, int(np.ceil(x1)) + 2), min(H, int(np.ceil(y1)) + 2)
        crop = img[iy0:iy1, ix0:ix1]
        cw = max(1, int(round((ix1 - ix0) / sx)))
        chh = max(1, int(round((iy1 - iy0) / sy)))
        small = cv2.resize(crop, (cw, chh), interpolation=cv2.INTER_AREA)
        kx, ky = cw / (ix1 - ix0), chh / (iy1 - iy0)
        M = np.float32([[1, 0, -(x0 - ix0) * kx], [0, 1, -(y0 - iy0) * ky]])
        return cv2.warpAffine(small, M, (out_w, out_h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # enlarging: Lanczos warp of a padded crop (keeps memory bounded)
    ix0, iy0 = max(0, int(np.floor(x0)) - 4), max(0, int(np.floor(y0)) - 4)
    ix1, iy1 = min(W, int(np.ceil(x1)) + 4), min(H, int(np.ceil(y1)) + 4)
    crop = img[iy0:iy1, ix0:ix1]
    # pixel-centre convention: dst_j + 0.5 = (src_i + 0.5 - x0) / sx
    M = np.float32([[1 / sx, 0, (ix0 - x0 + 0.5) / sx - 0.5], [0, 1 / sy, (iy0 - y0 + 0.5) / sy - 0.5]])
    out = np.empty((out_h, out_w, 3), np.uint8)
    band = 2048
    for by in range(0, out_h, band):
        bh = min(band, out_h - by)
        Mb = M.copy()
        Mb[1, 2] -= by
        out[by:by + bh] = cv2.warpAffine(crop, Mb, (out_w, bh), flags=cv2.INTER_LANCZOS4,
                                         borderMode=cv2.BORDER_REPLICATE)
    return out


def _slug(s: str) -> str:
    keep = "".join(c if c.isalnum() else "_" for c in s)
    while "__" in keep:
        keep = keep.replace("__", "_")
    return keep.strip("_")


def _srgb_icc() -> Optional[bytes]:
    try:
        from PIL import ImageCms
        return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    except Exception:
        return None


def _write_image(path: Path, img: np.ndarray, fmt: str, dpi: float, quality: int = 95) -> None:
    im = Image.fromarray(img)
    icc = _srgb_icc()
    kw = {"icc_profile": icc} if icc else {}
    dpi = (round(dpi), round(dpi))
    if fmt == "png":
        im.save(path, "PNG", dpi=dpi, compress_level=6, **kw)
    elif fmt in ("jpg", "jpeg"):
        im.save(path, "JPEG", quality=quality, subsampling=0, optimize=True, dpi=dpi, **kw)
    elif fmt == "tiff":
        im.save(path, "TIFF", compression="tiff_lzw", dpi=dpi, **kw)
    elif fmt == "webp":
        if max(img.shape[:2]) > 16383:
            raise ValueError("WebP is limited to 16383 px per side - use PNG/JPEG/TIFF for this size")
        im.save(path, "WEBP", quality=quality, method=6, **kw)
    else:
        raise ValueError(f"unknown format {fmt}")


def format_report(r: dict) -> str:
    e = r.get("enhancement", {})
    lines = [f"{r['app']} - quality report",
             f"Source:          {r['source']}  ({r['source_px'][0]} x {r['source_px'][1]} px)",
             f"AI enhancement:  x{r.get('ai_factor') or 1}  {e.get('method', 'none')}"
             + ("  [from cache]" if e.get("cached") else ""),
             ]
    if e.get("auto"):
        lines.append(f"                 auto: {e['auto']}")
    for p in e.get("passes", []):
        lines.append(f"                 - {p}")
    if e.get("seconds"):
        lines.append(f"                 {e['seconds']} s on {e.get('backend', '?')}")
    lines += [f"Text removal:    {r['text_removal']}",
              f"OCR:             {r['ocr_backend']}  ({r['text_blocks']} lines, {r['vector_blocks']} vectorised)",
              "", "Outputs:"]
    for t in r["targets"]:
        size = f"{t['size_mm'][0]} x {t['size_mm'][1]} mm, " if "size_mm" in t else ""
        lines.append(f"  {t['name']}: {size}{t['canvas_px'][0]} x {t['canvas_px'][1]} px @ {t['dpi']:g} dpi "
                     f"({t['fit']}) -> {', '.join(t['formats']).upper()}")
        lines.append(f"      native {t['native_ppi']} ppi -> effective {t['effective_ppi']} ppi"
                     + (f"  (pixels invisible beyond {t['effective_view_m']} m; native {t['native_view_m']} m)"
                        if "effective_view_m" in t else ""))
    if r["vector_text"]:
        lines += ["", "Vector text:"]
        for v in r["vector_text"]:
            warn = f"  !! missing glyphs: {v['missing_glyphs']}" if v["missing_glyphs"] else ""
            lines.append(f"  - \"{v['text']}\"  {v['font']}{warn}")
    if r.get("warnings"):
        lines += ["", "Warnings:"] + [f"  ! {w}" for w in r["warnings"]]
    if r.get("outputs"):
        lines += ["", "Files:"] + [f"  {o}" for o in r["outputs"]]
    lines.append("")
    lines.append("Timings (s): " + ", ".join(f"{k}={v}" for k, v in r.get("timings_s", {}).items()))
    return "\n".join(lines) + "\n"
