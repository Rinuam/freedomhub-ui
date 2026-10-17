"""Command line: `tfe-poster [gui|process|batch|models|doctor]`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _targets(a):
    from .formats import PAPER_MM, SOCIAL_PX, original_target, print_target, social_target
    out = []
    for p in a.print or []:
        if p not in PAPER_MM:
            sys.exit(f"Unknown paper {p!r}. Choose from: {', '.join(PAPER_MM)}")
        out.append(print_target(p, a.dpi, a.margin, a.print_formats.split(","), a.orientation))
    for s in a.social or []:
        if s not in SOCIAL_PX:
            sys.exit(f"Unknown social preset {s!r}. Choose from: {', '.join(SOCIAL_PX)}")
        out.append(social_target(s, a.social_fit, a.social_formats.split(",")))
    for n in a.original or []:
        out.append(original_target(int(n), a.social_formats.split(",")))
    if not out:
        out.append(print_target("A1", a.dpi, a.margin, a.print_formats.split(","), a.orientation))
    for t in out:
        t.pdf_background = "lossless" if a.lossless else "jpeg"
    return out


def _enhance(a):
    from .enhance.pipeline import EnhanceSettings
    from .enhance.zoo import PRESETS
    s = EnhanceSettings()
    if a.preset:
        match = [p for p in PRESETS if p.lower().startswith(a.preset.lower())]
        if not match:
            sys.exit(f"Unknown preset. Choose from: {', '.join(PRESETS)}")
        s.apply_preset(match[0])
    if a.model:
        s.model = a.model
    s.factor = a.factor
    s.tta = a.tta
    s.face = a.faces
    s.pre_restore = a.restore
    s.tile = a.tile
    s.device = a.device
    if a.sharpen:
        s.adjust.sharpen = a.sharpen
    if a.clarity:
        s.adjust.clarity = a.clarity
    return s


def _add_common(p):
    g = p.add_argument_group("enhancement")
    g.add_argument("--preset", help="enhancement preset (prefix match, e.g. 'Best · real')")
    g.add_argument("--model", help="model id (see `models`), file path, 'ncnn:<name>' or 'lanczos'")
    g.add_argument("--factor", default="auto", choices=["auto", "2", "4", "8", "16"])
    g.add_argument("--tta", action="store_true", help="8x self-ensemble (slower, slightly better)")
    g.add_argument("--faces", default="off", help="off | gfpgan-1.4 | codeformer")
    g.add_argument("--restore", default="off", help="pre-restore: off | fbcnn | scunet")
    g.add_argument("--tile", type=int, default=384)
    g.add_argument("--device", default="auto", help="auto | mps | cpu")
    g.add_argument("--sharpen", type=float, default=0.0)
    g.add_argument("--clarity", type=float, default=0.0)
    o = p.add_argument_group("outputs")
    o.add_argument("--print", action="append", help="paper size, repeatable (A0..A6, 'US Letter', …)")
    o.add_argument("--social", action="append", help="social preset, repeatable ('Instagram post 1:1', …)")
    o.add_argument("--original", action="append", help="keep aspect, long side N px (repeatable)")
    o.add_argument("--dpi", type=int, default=300)
    o.add_argument("--margin", type=float, default=15.0)
    o.add_argument("--orientation", default="auto", choices=["auto", "portrait", "landscape"])
    o.add_argument("--print-formats", default="pdf,png")
    o.add_argument("--social-formats", default="png,jpg")
    o.add_argument("--social-fit", default="extend", choices=["fit", "fill", "extend"])
    o.add_argument("--lossless", action="store_true", help="lossless PDF background")
    t = p.add_argument_group("text")
    t.add_argument("--vectorise", choices=["auto", "all", "none"], default="auto")
    t.add_argument("--font", default="", help="font full name for all vector text")
    p.add_argument("-o", "--out", default=None)


def _progress(msg, frac):
    print(f"\r[{frac * 100:5.1f}%] {msg[:70]:<70}", end="", flush=True)


def cmd_models(a) -> int:
    from .enhance import zoo
    if a.download:
        ids = zoo.DEFAULT_BUNDLE if a.download == ["default"] else \
            [m.id for m in zoo.CATALOG] if a.download == ["all"] else a.download
        for mid in ids:
            print(f"Downloading {mid} ({zoo.BY_ID[mid].size_mb:.0f} MB)…")
            zoo.download(mid, lambda f: print(f"\r  {f * 100:5.1f}%", end="", flush=True),
                         Path(a.dest) if a.dest else None)
            print()
        return 0
    for m in zoo.CATALOG:
        st = "installed" if zoo.is_installed(m.id) else "-"
        lic = m.license + ("" if m.commercial_ok else "  (non-commercial!)")
        print(f"{m.id:18} {m.kind:8} x{m.scale} {m.size_mb:6.0f} MB  {st:9}  {m.name}  [{lic}]")
    for p in zoo.custom_models():
        print(f"{'custom':18} {'sr':8} -- {p.stat().st_size / 1e6:6.0f} MB  installed  {p.name}")
    print(f"\nModel folder: {zoo.user_dir()}")
    return 0


def doctor() -> int:
    from . import __version__
    from .enhance import zoo
    from .enhance.torch_sr import torch_available
    from .fonts import default_font_id, font_by_id, list_fonts
    from .inpaint import method_name
    from .ocr import backend_name
    from .upscale import find_realesrgan
    print(f"TFE Poster Maker {__version__}  (python {sys.version.split()[0]}, {sys.platform})")
    if torch_available():
        import torch
        from .enhance.torch_sr import device_name
        print(f"  PyTorch      : {torch.__version__} on {device_name()}")
    else:
        from .enhance import torch_sr
        print(f"  PyTorch      : NOT AVAILABLE (ncnn/Lanczos fallback): {torch_sr.TORCH_ERROR}")
    inst = [m.id for m in zoo.CATALOG if zoo.is_installed(m.id)]
    print(f"  models       : {len(inst)}/{len(zoo.CATALOG)} installed: {', '.join(inst) or 'none'}")
    print(f"  Real-ESRGAN  : {find_realesrgan() or 'not found'} (fallback)")
    print(f"  OCR          : {backend_name()}")
    print(f"  text removal : {method_name()}")
    fonts = list_fonts()
    print(f"  fonts        : {len(fonts)} faces; default {font_by_id(default_font_id()).label}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tfe-poster", description="TFE Poster Maker")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gui")
    p = sub.add_parser("process", help="enhance + export one image (no review)")
    p.add_argument("image")
    _add_common(p)
    b = sub.add_parser("batch", help="process every image in a folder")
    b.add_argument("folder")
    _add_common(b)
    m = sub.add_parser("models", help="list / download models")
    m.add_argument("--download", nargs="+", help="ids, 'default' or 'all'")
    m.add_argument("--dest", default="")
    sub.add_parser("doctor")
    a = ap.parse_args(argv)
    if a.cmd in (None, "gui"):
        from .gui.app import run
        return run()
    if a.cmd == "doctor":
        return doctor()
    if a.cmd == "models":
        return cmd_models(a)
    from .project import format_report
    enh, targets = _enhance(a), _targets(a)
    font_id = ""
    if a.font:
        from .fonts import find_font
        f = find_font(a.font)
        if not f:
            sys.exit(f"Font not found: {a.font}")
        font_id = f.id
    if a.cmd == "process":
        from .batch import process_one
        img = Path(a.image)
        out = Path(a.out) if a.out else img.parent / "tfe_output"
        rep = process_one(img, out, enh, targets, a.vectorise, font_id, _progress)
        print("\n" + format_report(rep))
        return 0
    from .batch import run_batch
    folder = Path(a.folder)
    out = Path(a.out) if a.out else folder / "tfe_output"
    rows = run_batch(folder, out, enh, targets, a.vectorise, font_id,
                     lambda i, n, msg, f: _progress(f"({i + 1}/{n}) {msg}", f))
    print()
    for r in rows:
        print(f"  {r['status']:5} {r['file']}  {r['ai']}  {r['vectorised']}/{r['text_blocks']} vector"
              + (f"\n        {r['error'].splitlines()[0]}" if r["error"] else ""))
    print(f"Summary: {out / 'batch_summary.csv'}")
    return 0 if all(r["status"] == "ok" for r in rows) else 1
