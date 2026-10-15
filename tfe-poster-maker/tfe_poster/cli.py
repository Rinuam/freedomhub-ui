"""Command line interface.  `python -m tfe_poster [gui|process|batch|doctor]`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Settings, UPSCALE_MODELS


def _add_settings_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--orientation", choices=["auto", "portrait", "landscape"], default="auto")
    p.add_argument("--margin", type=float, default=15.0, help="margin in mm (default 15)")
    p.add_argument("--dpi", type=int, default=300)
    p.add_argument("--no-upscale", action="store_true", help="skip Real-ESRGAN (Lanczos only)")
    p.add_argument("--model", choices=list(UPSCALE_MODELS), default=None)
    p.add_argument("--tile", type=int, default=0, help="Real-ESRGAN tile size (0 = auto)")
    p.add_argument("--realesrgan", default="", help="path to realesrgan-ncnn-vulkan")
    p.add_argument("--vectorise", choices=["auto", "all", "none"], default="auto",
                   help="which OCR boxes become vector text (no review in CLI)")
    p.add_argument("--font", default="", help="font full name for vector text, e.g. 'Helvetica Neue Bold'")
    p.add_argument("--lossless", action="store_true", help="embed the PDF background losslessly")


def _settings(a) -> Settings:
    s = Settings(orientation=a.orientation, margin_mm=a.margin, dpi=a.dpi,
                 upscale=not a.no_upscale, upscale_tile=a.tile, realesrgan_path=a.realesrgan,
                 batch_vectorise=a.vectorise,
                 pdf_background="lossless" if a.lossless else "jpeg")
    if a.model:
        s.upscale_model = a.model
    if a.font:
        from .fonts import find_font
        f = find_font(a.font)
        if not f:
            sys.exit(f"Font not found: {a.font}")
        s.default_font = f.id
    return s


def _print_progress(msg: str, frac: float) -> None:
    print(f"\r[{frac * 100:5.1f}%] {msg:<60}", end="", flush=True)


def doctor() -> int:
    from . import __version__
    from .fonts import list_fonts, default_font_id, font_by_id
    from .ocr import backend_name
    from .upscale import find_realesrgan, available_models
    b = find_realesrgan()
    print(f"TFE Poster Maker {__version__}")
    print(f"  python       : {sys.version.split()[0]} ({sys.platform})")
    print(f"  OCR backend  : {backend_name()}")
    print(f"  Real-ESRGAN  : {b or 'NOT FOUND (Lanczos fallback)'}")
    if b:
        print(f"  models       : {', '.join(available_models(b))}")
    fonts = list_fonts()
    print(f"  fonts        : {len(fonts)} usable faces; default "
          f"{font_by_id(default_font_id()).label} / {font_by_id(default_font_id(True)).label}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tfe-poster", description="TFE Poster Maker")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="open the desktop app (default)")
    p = sub.add_parser("process", help="process one image without review")
    p.add_argument("image")
    p.add_argument("-o", "--out", default=None)
    _add_settings_args(p)
    b = sub.add_parser("batch", help="process every PNG/JPG in a folder")
    b.add_argument("folder")
    b.add_argument("-o", "--out", default=None)
    _add_settings_args(b)
    sub.add_parser("doctor", help="check OCR / Real-ESRGAN / fonts")
    a = ap.parse_args(argv)

    if a.cmd in (None, "gui"):
        from .gui.app import run
        return run()
    if a.cmd == "doctor":
        return doctor()
    s = _settings(a)
    if a.cmd == "process":
        from .batch import process_one
        img = Path(a.image)
        out = Path(a.out) if a.out else img.parent / "tfe_output"
        rep = process_one(img, out, s, _print_progress)
        print()
        from .project import format_report
        print(format_report(rep))
        return 0
    if a.cmd == "batch":
        from .batch import run_batch
        folder = Path(a.folder)
        out = Path(a.out) if a.out else folder / "tfe_output"
        rows = run_batch(folder, out, s,
                         lambda i, n, m, f: _print_progress(f"({i + 1}/{n}) {m}", f))
        print()
        for r in rows:
            print(f"  {r['status']:5} {r['file']}  native {r['native_ppi']} ppi -> "
                  f"effective {r['effective_ppi']} ppi, {r['vectorised']}/{r['text_boxes']} vector"
                  + (f"\n        {r['error'].splitlines()[0]}" if r["error"] else ""))
        print(f"Summary: {out / 'batch_summary.csv'}")
        return 0 if all(r["status"] == "ok" for r in rows) else 1
    return 0
