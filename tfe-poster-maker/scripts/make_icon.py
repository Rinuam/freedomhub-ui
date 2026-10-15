"""Draw the app icon (A1 sheet with a 4x arrow). Writes PNG + macOS .iconset."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def icon(size=1024):
    s = size / 1024
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(bg)
    d.rounded_rectangle([90 * s, 90 * s, 934 * s, 934 * s], 190 * s, fill=(24, 38, 82, 255))
    im = Image.alpha_composite(im, bg)
    sh = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([318 * s, 214 * s, 718 * s, 780 * s], fill=(0, 0, 0, 120))
    im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(18 * s)))
    d = ImageDraw.Draw(im)
    # sheet in A1 proportion (1 : 1.414)
    d.rectangle([300 * s, 196 * s, 700 * s, 762 * s], fill=(250, 246, 236, 255))
    d.rectangle([326 * s, 222 * s, 674 * s, 736 * s], fill=(120, 190, 220, 255))
    d.polygon([(340 * s, 720 * s), (470 * s, 470 * s), (600 * s, 720 * s)], fill=(230, 90, 110, 255))
    d.ellipse([540 * s, 260 * s, 640 * s, 360 * s], fill=(255, 210, 90, 255))
    for i, w in enumerate((260, 200)):
        y = (300 + 46 * i) * s
        d.rectangle([350 * s, y, (350 + w) * s, y + 22 * s], fill=(24, 38, 82, 255))
    # vector-node marks
    for x, y in ((350, 300), (610, 300), (350, 322), (610, 322)):
        d.rectangle([(x - 7) * s, (y - 7) * s, (x + 7) * s, (y + 7) * s], outline=(255, 120, 40, 255),
                    width=max(1, int(3 * s)))
    return im


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/icon")
    out.mkdir(parents=True, exist_ok=True)
    big = icon(1024)
    big.save(out / "icon.png")
    iconset = out / "TFE.iconset"
    iconset.mkdir(exist_ok=True)
    for sz in (16, 32, 128, 256, 512):
        big.resize((sz, sz), Image.LANCZOS).save(iconset / f"icon_{sz}x{sz}.png")
        big.resize((sz * 2, sz * 2), Image.LANCZOS).save(iconset / f"icon_{sz}x{sz}@2x.png")
    print("icon written to", out)
