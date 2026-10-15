"""Generate synthetic 'ChatGPT-style' poster images for testing.

Usage: python scripts/make_samples.py [out_dir]
Writes 1024x1536 portrait and 1536x1024 landscape PNG/JPG images with
illustration-like backgrounds and text in several sizes and colours, plus
<name>.truth.json files listing the drawn strings.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIRS = ["/System/Library/Fonts/Supplementary", "/Library/Fonts", "/System/Library/Fonts",
             "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation"]
CANDIDATES = {
    "bold": ["Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "regular": ["Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
    "serif": ["Georgia.ttf", "DejaVuSerif.ttf", "LiberationSerif-Regular.ttf"],
}


def font(kind, size):
    for d in FONT_DIRS:
        for n in CANDIDATES[kind]:
            p = Path(d) / n
            if p.is_file():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def background(w, h, c0, c1, seed):
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 1, h)[:, None, None]
    img = (np.array(c0) * (1 - t) + np.array(c1) * t) * np.ones((h, w, 3))
    im = Image.fromarray(img.astype(np.uint8))
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(14):
        r = int(rng.integers(60, 260))
        x, y = int(rng.integers(0, w)), int(rng.integers(int(h * 0.25), h))
        col = tuple(int(v) for v in rng.integers(40, 255, 3)) + (110,)
        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    im = im.filter(ImageFilter.GaussianBlur(18))
    d = ImageDraw.Draw(im, "RGBA")
    # crisp "illustration" shapes
    for _ in range(6):
        x, y = int(rng.integers(0, w)), int(rng.integers(int(h * 0.35), int(h * 0.85)))
        s = int(rng.integers(40, 140))
        d.polygon([(x, y - s), (x + s, y + s), (x - s, y + s)],
                  fill=tuple(int(v) for v in rng.integers(0, 255, 3)) + (200,),
                  outline=(20, 20, 30, 255), width=4)
    return im


def draw_centered(d, w, y, text, f, fill, stroke=0, stroke_fill=None):
    l, t, r, b = d.textbbox((0, 0), text, font=f, stroke_width=stroke)
    d.text(((w - (r - l)) / 2 - l, y), text, font=f, fill=fill,
           stroke_width=stroke, stroke_fill=stroke_fill)


def poster_portrait(out: Path):
    w, h = 1024, 1536
    im = background(w, h, (250, 244, 228), (214, 232, 240), 1)
    d = ImageDraw.Draw(im)
    texts = []
    for y, s, kind, col, txt in [
        (80, 80, "bold", (25, 40, 90), "CARBON NANOTUBE"),
        (180, 80, "bold", (25, 40, 90), "LOGIC 2026"),
        (300, 40, "regular", (200, 60, 40), "Thin Film Workshop - Barcelona"),
        (1330, 34, "serif", (40, 40, 40), "ALD - PVD - CVD - RIE - ALE"),
        (1400, 28, "regular", (60, 60, 60), "8 inch wafer process integration"),
    ]:
        draw_centered(d, w, y, txt, font(kind, s), col)
        texts.append(txt)
    # banner with light text on dark
    d.rounded_rectangle([140, 1180, 884, 1270], 24, fill=(30, 30, 60))
    draw_centered(d, w, 1198, "Register: 12 November", font("bold", 46), (255, 215, 90))
    texts.append("Register: 12 November")
    im.save(out / "portrait_poster.png")
    (out / "portrait_poster.truth.json").write_text(json.dumps(texts, indent=1))


def poster_landscape(out: Path):
    w, h = 1536, 1024
    im = background(w, h, (18, 22, 48), (60, 20, 70), 7)
    d = ImageDraw.Draw(im)
    texts = []
    for y, s, kind, col, txt in [
        (60, 100, "bold", (245, 245, 250), "MEMORY DAY"),
        (190, 44, "regular", (140, 220, 255), "Atomic Layer Etching for CNT FETs"),
        (900, 36, "serif", (230, 200, 120), "Ideaded Thin Film Lab"),
    ]:
        draw_centered(d, w, y, txt, font(kind, s), col)
        texts.append(txt)
    im.convert("RGB").save(out / "landscape_dark.jpg", quality=88)
    (out / "landscape_dark.truth.json").write_text(json.dumps(texts, indent=1))


def poster_no_text(out: Path):
    im = background(1024, 1536, (120, 170, 120), (30, 80, 60), 3)
    im.convert("RGB").save(out / "illustration_no_text.jpg", quality=90)
    (out / "illustration_no_text.truth.json").write_text("[]")


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
    out.mkdir(parents=True, exist_ok=True)
    poster_portrait(out)
    poster_landscape(out)
    poster_no_text(out)
    print("samples written to", out)
