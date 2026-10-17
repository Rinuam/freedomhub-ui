"""Offline font discovery and loading.

Fonts are identified by ``"<path>#<index>"`` so faces inside .ttc collections
(very common on macOS, e.g. Helvetica.ttc) are addressable. Faces from a
collection are extracted to a standalone sfnt buffer before embedding, so the
PDF only carries the face that is actually used (and PyMuPDF subsets it).
"""
from __future__ import annotations

import io
import json
import os
import sys
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path
import logging

logging.getLogger("fontTools").setLevel(logging.ERROR)

FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}
CACHE = Path.home() / ".tfe-poster-maker" / "fonts.json"

# Preferred defaults, first match wins (full names as reported by the font).
PREFERRED_REGULAR = ["Helvetica Neue", "Helvetica", "Arial", "Avenir Next Regular",
                     "DejaVu Sans", "Liberation Sans"]
PREFERRED_BOLD = ["Helvetica Neue Bold", "Helvetica Bold", "Arial Bold",
                  "Avenir Next Bold", "DejaVu Sans Bold", "Liberation Sans Bold"]


@dataclass
class FontInfo:
    id: str
    family: str
    style: str
    full_name: str

    @property
    def path(self) -> str:
        return self.id.rsplit("#", 1)[0]

    @property
    def index(self) -> int:
        return int(self.id.rsplit("#", 1)[1])

    @property
    def label(self) -> str:
        return self.full_name or f"{self.family} {self.style}".strip()


def font_dirs() -> list[Path]:
    home = Path.home()
    here = Path(__file__).resolve().parent
    dirs = [here / "fonts"]
    if getattr(sys, "_MEIPASS", None):
        dirs.append(Path(sys._MEIPASS) / "tfe_poster" / "fonts")
    if sys.platform == "darwin":
        dirs += [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplementary"),
                 Path("/Library/Fonts"), home / "Library/Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
                 home / ".fonts", home / ".local/share/fonts"]
    return [d for d in dirs if d.is_dir()]


def _name(tt, ids) -> str:
    name = tt["name"]
    for i in ids:
        rec = name.getName(i, 3, 1) or name.getName(i, 1, 0)
        if rec:
            try:
                return str(rec.toUnicode()).strip()
            except Exception:
                pass
    return ""


def _scan_file(path: Path) -> list[FontInfo]:
    from fontTools.ttLib import TTCollection, TTFont
    out = []
    try:
        if path.suffix.lower() in (".ttc", ".otc"):
            faces = list(TTCollection(str(path), lazy=True).fonts)
        else:
            faces = [TTFont(str(path), lazy=True)]
    except Exception:
        return out
    for i, tt in enumerate(faces):
        try:
            if "glyf" not in tt and "CFF " not in tt and "CFF2" not in tt:
                continue  # bitmap-only (e.g. emoji) faces cannot be embedded as vectors
            cmap = tt.getBestCmap() or {}
            if ord("A") not in cmap:
                continue
            family = _name(tt, (16, 1))
            style = _name(tt, (17, 2))
            full = _name(tt, (4,)) or f"{family} {style}"
            if not family or family.startswith("."):
                continue
            out.append(FontInfo(f"{path}#{i}", family, style, full))
        except Exception:
            continue
    return out


def _signature(dirs: list[Path]) -> str:
    parts = []
    for d in dirs:
        try:
            parts.append(f"{d}:{d.stat().st_mtime_ns}")
        except OSError:
            pass
    return "|".join(parts)


@lru_cache(maxsize=1)
def list_fonts() -> list[FontInfo]:
    dirs = font_dirs()
    sig = _signature(dirs)
    try:
        data = json.loads(CACHE.read_text())
        if data.get("sig") == sig:
            return [FontInfo(**f) for f in data["fonts"]]
    except Exception:
        pass
    fonts: dict[str, FontInfo] = {}
    for d in dirs:
        for root, _, files in os.walk(d):
            for fn in files:
                p = Path(root) / fn
                if p.suffix.lower() in FONT_EXTS:
                    for f in _scan_file(p):
                        fonts.setdefault(f.label.lower(), f)  # dedupe by full name
    result = sorted(fonts.values(), key=lambda f: f.label.lower())
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"sig": sig, "fonts": [asdict(f) for f in result]}))
    except Exception:
        pass
    return result


def font_by_id(font_id: str) -> FontInfo | None:
    for f in list_fonts():
        if f.id == font_id:
            return f
    if font_id and "#" in font_id and Path(font_id.rsplit("#", 1)[0]).is_file():
        for f in _scan_file(Path(font_id.rsplit("#", 1)[0])):
            if f.id == font_id:
                return f
    return None


def find_font(name: str) -> FontInfo | None:
    n = name.lower()
    fonts = list_fonts()
    for f in fonts:
        if f.label.lower() == n:
            return f
    for f in fonts:
        if f.label.lower().startswith(n):
            return f
    return None


def default_font_id(bold: bool = False) -> str:
    for name in (PREFERRED_BOLD if bold else PREFERRED_REGULAR):
        f = find_font(name)
        if f:
            return f.id
    fonts = list_fonts()
    if not fonts:
        raise RuntimeError("No usable fonts found on this system")
    return fonts[0].id


@lru_cache(maxsize=64)
def font_bytes(font_id: str) -> bytes:
    """Standalone sfnt bytes for one face (extracted from collections)."""
    path, idx = font_id.rsplit("#", 1)
    idx = int(idx)
    if Path(path).suffix.lower() not in (".ttc", ".otc"):
        return Path(path).read_bytes()
    from fontTools.ttLib import TTCollection
    face = TTCollection(path).fonts[idx]
    buf = io.BytesIO()
    face.save(buf)
    return buf.getvalue()


@lru_cache(maxsize=64)
def fitz_font(font_id: str):
    import pymupdf
    return pymupdf.Font(fontbuffer=font_bytes(font_id))
