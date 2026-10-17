"""TFE Poster Maker v2 tests.  `pytest -q`  (AI-model tests auto-skip when models are absent)."""
import io
import json
import stat
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tfe_poster.enhance import adjust as adj  # noqa: E402
from tfe_poster.enhance import zoo  # noqa: E402
from tfe_poster.enhance.pipeline import EnhanceSettings, choose_factor, jpeg_blockiness  # noqa: E402
from tfe_poster.enhance.torch_sr import tiled_upscale  # noqa: E402
from tfe_poster.fonts import default_font_id, font_bytes, find_font  # noqa: E402
from tfe_poster.formats import (PAPER_MM, OutputTarget, original_target, place, print_target,  # noqa: E402
                                social_target)
from tfe_poster.inpaint import inpaint  # noqa: E402
from tfe_poster.layout import sample_edge_colour  # noqa: E402
from tfe_poster.ocr import backend_name  # noqa: E402
from tfe_poster.project import Project, _crop_resample  # noqa: E402
from tfe_poster.text.engine import autofit, layout, layout_em  # noqa: E402
from tfe_poster.text.model import EraseRegion, TextBlock  # noqa: E402

BOLD = default_font_id(True)
TEXT_RGB = (20, 30, 90)


# ---------------------------------------------------------------- formats
@pytest.mark.parametrize("paper", ["A0", "A1", "A2", "A4", "US Letter"])
def test_print_sizes_exact(paper):
    t = print_target(paper, 300, 10)
    pl = place(t, 1024, 1536)
    w_mm, h_mm = PAPER_MM[paper]
    assert abs(pl.canvas_w - round(w_mm / 25.4 * 300)) <= 1
    assert abs(pl.canvas_h - round(h_mm / 25.4 * 300)) <= 1
    assert abs(pl.page_w_pt - w_mm / 25.4 * 72) < 0.01


def test_fit_no_crop_no_stretch():
    pl = place(print_target("A1", 300, 15), 1024, 1536)
    x0, y0, x1, y1 = pl.image_rect(1024, 1536)
    m = round(15 / 25.4 * 300)
    assert x0 >= m - 1 and y0 >= m - 1 and x1 <= pl.canvas_w - m + 1 and y1 <= pl.canvas_h - m + 1
    assert abs((x1 - x0) / (y1 - y0) - 1024 / 1536) < 1e-6


def test_landscape_auto_orientation():
    pl = place(print_target("A3"), 1536, 1024)
    assert pl.canvas_w > pl.canvas_h and pl.orientation == "landscape"


def test_fill_covers_canvas_and_focus():
    t = social_target("YouTube thumbnail", fit="fill")
    pl = place(t, 1024, 1536)
    x0, y0, x1, y1 = pl.image_rect(1024, 1536)
    assert x0 <= 0 and y0 <= 0 and x1 >= pl.canvas_w - 1e-6 and y1 >= pl.canvas_h - 1e-6
    t.focus_y = 0.0
    assert place(t, 1024, 1536).off_y == 0


def test_original_aspect_target():
    pl = place(original_target(4096), 1024, 1536)
    assert (pl.canvas_w, pl.canvas_h) == (2731, 4096)


def test_choose_factor():
    assert choose_factor("auto", 6.2, 4) == 8
    assert choose_factor("auto", 1.0, 4) == 4
    assert choose_factor("auto", 30, 4, 16) == 16
    assert choose_factor("2", 30, 4) == 2


# ---------------------------------------------------------------- text engine
def test_kerning_changes_layout():
    a = TextBlock(0, "AVATAR", font_id=find_font("DejaVu Serif").id)
    b = TextBlock(0, "AVATAR", font_id=a.font_id, kerning=False)
    wa = layout_em(a)[1][2] - layout_em(a)[1][0]
    wb = layout_em(b)[1][2] - layout_em(b)[1][0]
    assert wa < wb - 0.05


def test_tracking_and_multiline():
    b = TextBlock(0, "HELLO", font_id=BOLD)
    w0 = layout_em(b)[1][2]
    b.tracking = 200
    assert layout_em(b)[1][2] > w0 + 0.7
    m = TextBlock(0, "A\nB\nC", font_id=BOLD, line_height=1.5)
    ink = layout_em(m)[1]
    assert 3.0 < ink[3] - ink[1] < 4.0


def test_autofit_matches_ink():
    b = TextBlock(0, "NANOTUBE", font_id=BOLD, ink=(100, 50, 500, 110))
    autofit(b)
    x0, y0, x1, y1 = layout(b).bounds
    assert abs((x0 + x1) / 2 - 300) < 1.0 and abs((y0 + y1) / 2 - 80) < 1.0
    assert abs((x1 - x0) - 400) < 6


def test_missing_glyphs_reported():
    b = TextBlock(0, "abc 漢字", font_id=find_font("DejaVu Sans").id)
    assert "漢" in layout(b).missing


def test_rotation_keeps_centre():
    b = TextBlock(0, "ROTATE", font_id=BOLD, size=40, cx=300, cy=200, rotation=30)
    x0, y0, x1, y1 = layout(b).bounds
    assert abs((x0 + x1) / 2 - 300) < 2 and abs((y0 + y1) / 2 - 200) < 2


# ---------------------------------------------------------------- image ops
def test_tiled_upscale_is_seamless_for_local_ops():
    img = (np.random.default_rng(1).random((300, 437, 3)) * 255).astype(np.uint8)
    f = lambda t: np.repeat(np.repeat(t.astype(np.float32) / 255, 3, 0), 3, 1)  # noqa: E731
    out = tiled_upscale(img, f, 3, tile=64, overlap=16)
    assert np.array_equal(out, np.repeat(np.repeat(img, 3, 0), 3, 1))


def test_adjust_identity_and_banding():
    img = (np.random.default_rng(2).random((1300, 200, 3)) * 255).astype(np.uint8)
    assert adj.apply(img, adj.Adjustments()) is img
    a = adj.Adjustments(clarity=0.5, sharpen=1.0, contrast=0.2, vibrance=0.3)
    banded = adj.apply(img, a)
    whole = adj._apply_band(img, a, 1.0, 7)
    assert np.abs(banded.astype(int) - whole.astype(int)).max() <= 1


def test_crop_resample_matches_full_resize():
    img = np.dstack([np.tile(np.linspace(0, 255, 400), (300, 1))] * 3).astype(np.uint8)
    full = cv2.resize(img, (1200, 900), interpolation=cv2.INTER_LANCZOS4)
    part = _crop_resample(img, 100, 50, 200, 150, 300, 300)
    assert np.abs(part.astype(int) - full[150:450, 300:600].astype(int)).mean() < 1.5


def test_edge_colour():
    img = np.zeros((200, 100, 3), np.uint8)
    img[:] = (10, 120, 200)
    img[:5, :5] = (255, 0, 0)
    assert sample_edge_colour(img) == (10, 120, 200)


def test_jpeg_blockiness_detects_jpeg():
    rng = np.random.default_rng(3)
    img = cv2.GaussianBlur((rng.random((256, 256, 3)) * 255).astype(np.uint8), (0, 0), 3)
    buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 40])[1]
    assert jpeg_blockiness(cv2.imdecode(buf, 1)) > jpeg_blockiness(img) + 0.05


# ---------------------------------------------------------------- end to end
def _poster(path: Path):
    im = Image.new("RGB", (512, 768), (240, 236, 220))
    d = ImageDraw.Draw(im)
    for y in range(768):
        d.line([(0, y), (511, y)], fill=(240 - y // 12, 236 - y // 20, 220))
    d.ellipse([100, 300, 400, 600], fill=(80, 140, 200))
    f = ImageFont.truetype(io.BytesIO(font_bytes(BOLD)), 40)
    d.text((40, 60), "NANOTUBE LOGIC", font=f, fill=TEXT_RGB)
    im.save(path)
    return d.textbbox((40, 60), "NANOTUBE LOGIC", font=f)


def _project(tmp_path, targets=None):
    src = tmp_path / "poster.png"
    x0, y0, x1, y1 = _poster(src)
    p = Project(src)
    p.enhance = EnhanceSettings(model="lanczos")
    p.inpaint_method = "telea"
    p.targets = targets or [print_target("A4", 72, 10, ("pdf", "png"))]
    p.load()
    b = TextBlock(0, "NANOTUBE LOGIC", "NANOTUBE LOGIC", 1.0, box=(x0 - 2, y0 - 3, x1 - x0 + 4, y1 - y0 + 8),
                  font_id=BOLD)
    p._analyse(b)
    autofit(b)
    p.blocks = [b]
    return p


def test_analysis_and_autofit_size(tmp_path):
    p = _project(tmp_path)
    b = p.blocks[0]
    assert np.abs(np.array(b.fill) - TEXT_RGB).max() < 25
    assert b.bold_guess
    assert abs(b.size - 40) < 1.5          # drawn at 40 px


def test_erase_removes_raster_text(tmp_path):
    p = _project(tmp_path)
    cs, _ = p.clean()
    x, y, w, h = p.blocks[0].box
    dark = lambda a: (np.abs(a.astype(int) - TEXT_RGB).sum(2) < 90).mean()  # noqa: E731
    assert dark(p.src[int(y):int(y + h), int(x):int(x + w)]) > 0.1
    assert dark(cs[int(y):int(y + h), int(x):int(x + w)]) < 0.01


def test_export_all_formats(tmp_path):
    t1 = print_target("A4", 72, 10, ("pdf", "png", "jpg", "tiff"))
    t2 = social_target("Instagram post 1:1", fit="extend", formats=("png", "webp"))
    p = _project(tmp_path, [t1, t2])
    p.blocks[0].stroke_on = True
    p.blocks[0].shadow_on = True
    rep = p.export(tmp_path / "out")
    outs = rep["outputs"]
    assert len(outs) == 6 and all(Path(o).is_file() for o in outs)
    pdf = pymupdf.open(next(o for o in outs if o.endswith(".pdf")))
    page = pdf[0]
    assert abs(page.rect.width - 210 / 25.4 * 72) < 0.5
    assert "NANOTUBE LOGIC" in page.get_text()            # searchable layer
    assert len(page.get_drawings()) >= 2                  # vector outlines (stroke + fill)
    assert page.get_fonts() and len(page.get_images()) == 1
    ig = Image.open(next(o for o in outs if "Instagram" in o and o.endswith(".png")))
    assert ig.size == (1080, 1080) and ig.info.get("icc_profile")
    assert (tmp_path / "out" / "poster.tfe.json").is_file()


def test_vector_text_lands_on_original(tmp_path):
    p = _project(tmp_path)
    r = p.render_target(p.targets[0])
    pl = r.placement
    b = p.blocks[0]
    x, y, w, h = b.box
    X0, Y0 = map(int, pl.src_to_canvas(x - 8, y - 8))
    X1, Y1 = map(int, pl.src_to_canvas(x + w + 8, y + h + 8))
    plain = p.render_target(p.targets[0], text=False)
    # draw the original text area from the source (no erase) for reference
    p.blocks[0].erase = False
    p._clean_cache = None
    ref = p.render_target(p.targets[0], text=False).flat

    def bbox(a):
        m = np.abs(a[Y0:Y1, X0:X1].astype(int) - TEXT_RGB).sum(2) < 120
        ys, xs = np.nonzero(m)
        return np.array([xs.min(), ys.min(), xs.max(), ys.max()])
    assert np.abs(bbox(r.flat) - bbox(ref)).max() <= 2 * pl.scale + 1
    assert plain.flat is not None


def test_webp_limit_is_a_warning(tmp_path):
    p = _project(tmp_path, [OutputTarget(name="huge", kind="pixels", w_px=17000, h_px=100, fit="fit",
                                         formats=["webp", "png"])])
    rep = p.export(tmp_path / "o")
    assert rep["warnings"] and any(o.endswith(".png") for o in rep["outputs"])


def test_project_roundtrip(tmp_path):
    p = _project(tmp_path)
    p.blocks[0].text = "EDITED"
    p.blocks[0].stroke_on = True
    p.erase_regions.append(EraseRegion(1, 2, 30, 40))
    sc = tmp_path / "x.tfe.json"
    p.save(sc)
    q = Project(p.source_path)
    q.load()
    assert q.load_edits(sc)
    assert q.blocks[0].text == "EDITED" and q.blocks[0].stroke_on
    assert q.erase_regions[0].w == 30 and q.enhance.model == "lanczos"


def test_merge_blocks(tmp_path):
    p = _project(tmp_path)
    b2 = TextBlock(1, "SECOND", box=(40, 120, 200, 40), font_id=BOLD, ink=(40, 125, 240, 155), size=30)
    autofit(b2)
    p.blocks.append(b2)
    m = p.merge_blocks([0, 1])
    assert m.text == "NANOTUBE LOGIC\nSECOND" and len(p.blocks) == 1 and m.erase_boxes


def test_font_match_finds_bold(tmp_path):
    from tfe_poster.text.fontmatch import suggest
    p = _project(tmp_path)
    res = suggest(p.src, p.blocks[0], 3)
    assert res and res[0][0] == BOLD


# ---------------------------------------------------------------- models
def test_download_verifies_checksum(tmp_path, monkeypatch):
    blob = tmp_path / "m.pth"
    blob.write_bytes(b"x" * 1000)
    good = zoo.ModelInfo("t", "t", "sr", "X", 4, "m.pth", blob.as_uri(), zoo.sha256(blob), 1000, "MIT", True, 3, "")
    bad = zoo.ModelInfo("b", "b", "sr", "X", 4, "m2.pth", blob.as_uri(), "0" * 64, 1000, "MIT", True, 3, "")
    monkeypatch.setitem(zoo.BY_ID, "t", good)
    monkeypatch.setitem(zoo.BY_ID, "b", bad)
    assert zoo.download("t", dest_dir=tmp_path / "store").is_file()
    with pytest.raises(IOError):
        zoo.download("b", dest_dir=tmp_path / "store")
    assert not (tmp_path / "store" / "m2.pth").exists()


def test_catalog_entries_well_formed():
    for m in zoo.CATALOG:
        assert len(m.sha256) == 64 and m.url.startswith("https://") and m.size > 0
    for name, (model, detail, blend, desc) in zoo.PRESETS.items():
        assert model == "auto" or model in zoo.BY_ID
        assert not detail or detail in zoo.BY_ID


needs_model = pytest.mark.skipif(not zoo.is_installed("plksr-nomos2"), reason="plksr model not installed")


@needs_model
def test_real_model_enhance_small(tmp_path):
    from tfe_poster.enhance.pipeline import Enhancer
    img = (np.random.default_rng(0).random((48, 64, 3)) * 255).astype(np.uint8)
    e = Enhancer(EnhanceSettings(model="plksr-nomos2", device="cpu", tile=32))
    r = e.run(img, 8)
    assert r.image.shape == (384, 512, 3) and len(r.passes) == 2


@pytest.mark.skipif(not zoo.is_installed("lama"), reason="LaMa not installed")
def test_lama_inpaint(tmp_path):
    src = tmp_path / "p.png"
    _poster(src)
    img = np.asarray(Image.open(src).convert("RGB"))
    mask = np.zeros(img.shape[:2], np.uint8)
    mask[55:115, 30:500] = 255
    out = inpaint(img, mask, "lama")
    assert (np.abs(out[55:115, 30:500].astype(int) - TEXT_RGB).sum(2) < 90).mean() < 0.01


@pytest.mark.skipif(backend_name() == "none", reason="no OCR backend")
def test_ocr_detects_text(tmp_path):
    src = tmp_path / "poster.png"
    _poster(src)
    p = Project(src)
    p.load()
    p.detect_text()
    assert "NANOTUBE" in " ".join(b.text for b in p.blocks).upper()
