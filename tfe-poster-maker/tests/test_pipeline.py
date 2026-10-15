"""Pipeline tests. Run with `pytest -q` (uses a low dpi to stay fast)."""
import json
import os
import stat
import sys
import textwrap
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tfe_poster.config import Settings  # noqa: E402
from tfe_poster.fonts import default_font_id, font_bytes  # noqa: E402
from tfe_poster.layout import compute_layout, sample_edge_colour  # noqa: E402
from tfe_poster.ocr import backend_name  # noqa: E402
from tfe_poster.project import Project, TextBox  # noqa: E402
from tfe_poster import upscale as up  # noqa: E402


# ------------------------------------------------------------------ layout
@pytest.mark.parametrize("w,h,orient", [(1024, 1536, "portrait"), (1536, 1024, "landscape"),
                                        (1024, 1024, "portrait"), (300, 4000, "portrait")])
def test_layout_no_crop_no_stretch(w, h, orient):
    lay = compute_layout(w, h, "auto", 15, 300)
    assert lay.orientation == orient
    assert (lay.canvas_w, lay.canvas_h) == ((7016, 9933) if orient == "portrait" else (9933, 7016))
    m = round(15 / 25.4 * 300)
    assert lay.place_x >= m - 1 and lay.place_y >= m - 1
    assert lay.place_x + lay.place_w <= lay.canvas_w - m + 1
    assert lay.place_y + lay.place_h <= lay.canvas_h - m + 1
    # aspect preserved to within one pixel
    assert abs(lay.place_w / lay.place_h - w / h) < 1.5 / min(lay.place_w, lay.place_h)
    # one dimension touches the margin
    assert lay.place_w >= lay.canvas_w - 2 * m - 1 or lay.place_h >= lay.canvas_h - 2 * m - 1


def test_layout_forced_orientation():
    lay = compute_layout(1024, 1536, "landscape", 10, 300)
    assert lay.orientation == "landscape" and lay.canvas_w > lay.canvas_h


def test_edge_colour_is_robust_median():
    img = np.zeros((200, 100, 3), np.uint8)
    img[:] = (10, 120, 200)
    img[:5, :5] = (255, 0, 0)          # a stray corner mark
    assert sample_edge_colour(img) == (10, 120, 200)


def test_flatten_premultiplied():
    r = np.full((4, 4, 3), 200, np.uint8)
    t = np.zeros((4, 4, 4), np.uint8)
    t[1, 1] = (255, 0, 0, 255)
    t[2, 2] = (64, 0, 0, 128)
    f = Project.flatten(r, t)
    assert tuple(f[1, 1]) == (255, 0, 0)
    assert tuple(f[2, 2]) == (164, 100, 100)
    assert tuple(f[0, 0]) == (200, 200, 200)


# ------------------------------------------------------------- end to end
def _poster(path: Path, text="NANOTUBE LOGIC"):
    im = Image.new("RGB", (512, 768), (240, 236, 220))
    d = ImageDraw.Draw(im)
    for y in range(768):
        d.line([(0, y), (511, y)], fill=(240 - y // 12, 236 - y // 20, 220))
    d.ellipse([100, 300, 400, 600], fill=(80, 140, 200))
    f = ImageFont.truetype(__import__("io").BytesIO(font_bytes(default_font_id(True))), 40)
    d.text((40, 60), text, font=f, fill=(20, 30, 90))
    im.save(path)
    return d.textbbox((40, 60), text, font=f)


def _project(tmp_path, **kw):
    src = tmp_path / "poster.png"
    x0, y0, x1, y1 = _poster(src)
    s = Settings(dpi=72, upscale=False, **kw)
    p = Project(src, s)
    p.load()
    # OCR-like box (OCR independent) around the drawn text.
    p.boxes = [TextBox(0, "NANOTUBE LOGIC", "NANOTUBE LOGIC", x0 - 2, y0 - 3, x1 - x0 + 4,
                       y1 - y0 + 8, 1.0, vectorise=True)]
    p._analyse(p.boxes[0])
    p.boxes[0].font_id = default_font_id(True)
    p.prepare()
    return p


def test_analysis_finds_text_colour(tmp_path):
    p = _project(tmp_path)
    b = p.boxes[0]
    assert np.abs(np.array(b.colour) - (20, 30, 90)).max() < 25
    assert b.bold_guess


def test_export_pdf_and_png(tmp_path):
    p = _project(tmp_path)
    rep = p.export(tmp_path / "out")
    pdf = pymupdf.open(rep["outputs"]["pdf"])
    page = pdf[0]
    assert abs(page.rect.width - 594 / 25.4 * 72) < 0.5 and abs(page.rect.height - 841 / 25.4 * 72) < 0.5
    assert "NANOTUBE LOGIC" in page.get_text()
    fonts = page.get_fonts(full=True)
    assert fonts and all(f[1] in ("ttf", "otf", "cff") for f in fonts)      # embedded
    assert len(page.get_images()) == 1
    png = Image.open(rep["outputs"]["png"])
    assert png.size == (p.layout.canvas_w, p.layout.canvas_h)
    assert round(png.info["dpi"][0]) == 72
    assert json.loads((tmp_path / "out" / "poster_report.json").read_text())["vector_text_boxes"] == 1
    assert (tmp_path / "out" / "poster.tfe.json").is_file()


def test_inpaint_removes_raster_text(tmp_path):
    p = _project(tmp_path)
    raster = p.final_raster()
    lay = p.layout
    b = p.boxes[0]
    x0, y0 = map(int, lay.src_to_canvas(b.x, b.y))
    x1, y1 = map(int, lay.src_to_canvas(b.x + b.w, b.y + b.h))
    before = p.canvas[y0:y1, x0:x1].astype(int)
    after = raster[y0:y1, x0:x1].astype(int)
    dark = lambda a: (np.abs(a - (20, 30, 90)).sum(2) < 90).mean()  # noqa: E731
    assert dark(before) > 0.1
    assert dark(after) < 0.01


def test_vector_text_lands_on_raster_text(tmp_path):
    p = _project(tmp_path)
    _, placements, flat = p.render()
    lay = p.layout
    b = p.boxes[0]
    pad = 10
    x0, y0 = map(int, lay.src_to_canvas(b.x - pad, b.y - pad))
    x1, y1 = map(int, lay.src_to_canvas(b.x + b.w + pad, b.y + b.h + pad))

    def bbox(a):
        m = np.abs(a[y0:y1, x0:x1].astype(int) - (20, 30, 90)).sum(2) < 120
        ys, xs = np.nonzero(m)
        return np.array([xs.min(), ys.min(), xs.max(), ys.max()])
    d = np.abs(bbox(flat) - bbox(p.canvas))
    assert d.max() <= 2 * lay.scale, d     # within 2 source pixels


def test_sidecar_roundtrip(tmp_path):
    p = _project(tmp_path)
    p.boxes[0].text = "EDITED"
    p.boxes[0].size_pt = 33.0
    sc = tmp_path / "x.tfe.json"
    p.save_sidecar(sc)
    q = Project(p.source_path, p.settings)
    q.load()
    assert q.load_sidecar(sc)
    assert q.boxes[0].text == "EDITED" and q.boxes[0].size_pt == 33.0
    assert q.boxes[0].colour == p.boxes[0].colour


def test_report_numbers(tmp_path):
    p = _project(tmp_path)
    r = p.dpi_report()
    # 512 px across the printed width
    assert abs(r["native_ppi"] - 512 / (p.layout.place_w / 72)) < 0.2
    assert r["effective_ppi"] == r["native_ppi"]   # no upscale in this test


# ------------------------------------------------------------- upscaler
FAKE = textwrap.dedent("""\
    #!{py}
    import sys
    from PIL import Image
    a = sys.argv
    i, o, s = a[a.index('-i') + 1], a[a.index('-o') + 1], int(a[a.index('-s') + 1])
    im = Image.open(i)
    for p in ('25.00%', '50.00%', '100.00%'):
        print(p, flush=True)
    im.resize((im.width * s, im.height * s)).save(o)
""")


def test_realesrgan_wrapper_with_fake_binary(tmp_path):
    b = tmp_path / "realesrgan-ncnn-vulkan"
    b.write_text(FAKE.format(py=sys.executable))
    b.chmod(b.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "realesr-animevideov3-x4.param").write_text("")
    img = np.zeros((10, 20, 3), np.uint8)
    seen = []
    res = up.upscale(img, 3.0, True, "realesr-animevideov3", str(b), progress=seen.append)
    assert res.factor == 4 and res.image.shape == (40, 80, 3)
    assert seen and seen[-1] == 1.0
    # not needed when the source already has enough pixels
    assert up.upscale(img, 0.9, True, "realesr-animevideov3", str(b)).factor == 1


@pytest.mark.skipif(not up.find_realesrgan(), reason="realesrgan-ncnn-vulkan not installed")
def test_real_realesrgan_small():
    img = (np.random.default_rng(0).random((32, 48, 3)) * 255).astype(np.uint8)
    out = up.realesrgan_upscale(img, up.find_realesrgan(), "realesr-animevideov3", 4)
    assert out.shape == (128, 192, 3)


@pytest.mark.skipif(backend_name() == "none", reason="no OCR backend")
def test_ocr_detects_text(tmp_path):
    src = tmp_path / "poster.png"
    _poster(src)
    p = Project(src, Settings(dpi=72, upscale=False))
    p.load()
    p.detect_text()
    texts = " ".join(b.text for b in p.boxes).upper()
    assert "NANOTUBE" in texts


@pytest.mark.skipif(backend_name() == "none", reason="no OCR backend")
def test_ocr_respects_exif_rotation(tmp_path):
    src = tmp_path / "poster.png"
    x0, y0, x1, y1 = _poster(src)
    im = Image.open(src)
    # Store rotated pixels + an EXIF tag that rotates them back (orientation 6 = 90° CW).
    rot = im.transpose(Image.ROTATE_90)
    exif = Image.Exif()
    exif[0x0112] = 6
    jpg = tmp_path / "rotated.jpg"
    rot.save(jpg, quality=95, exif=exif)
    p = Project(jpg, Settings(dpi=72, upscale=False))
    p.load()
    assert p.src.shape[:2] == (768, 512)
    p.detect_text()
    hit = [b for b in p.boxes if "NANOTUBE" in b.text.upper()]
    assert hit and abs(hit[0].x - x0) < 15 and abs(hit[0].y - y0) < 15
