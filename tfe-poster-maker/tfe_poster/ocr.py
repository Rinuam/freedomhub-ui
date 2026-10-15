"""Text detection.

Primary backend: Apple Vision (VNRecognizeTextRequest) through pyobjc. It runs
fully on-device. A Tesseract CLI backend exists so the pipeline can be tested
off-macOS; it is never needed on the Mac.

All boxes are returned in *source image pixels*, top-left origin.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OcrLine:
    text: str
    x: float
    y: float
    w: float
    h: float
    confidence: float


def vision_available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import Vision  # noqa: F401
        return True
    except Exception:
        return False


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def backend_name() -> str:
    if vision_available():
        return "Apple Vision"
    if tesseract_available():
        return "Tesseract (fallback)"
    return "none"


def _vision_ocr(path: Path, width: int, height: int, languages: list[str]) -> list[OcrLine]:
    import Vision
    from Foundation import NSURL

    url = NSURL.fileURLWithPath_(str(path))
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    # Small display text on posters is common; let Vision look for it.
    req.setMinimumTextHeight_(0.0)
    if languages:
        try:
            supported = set(req.supportedRecognitionLanguagesAndReturnError_(None)[0] or [])
            langs = [l for l in languages if not supported or l in supported]
            if langs:
                req.setRecognitionLanguages_(langs)
        except Exception:
            pass
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision OCR failed: {err}")
    lines: list[OcrLine] = []
    for obs in req.results() or []:
        cands = obs.topCandidates_(1)
        if not cands:
            continue
        cand = cands[0]
        bb = obs.boundingBox()  # normalised, bottom-left origin
        x = bb.origin.x * width
        w = bb.size.width * width
        h = bb.size.height * height
        y = (1.0 - bb.origin.y - bb.size.height) * height
        lines.append(OcrLine(str(cand.string()), x, y, w, h, float(cand.confidence())))
    return lines


def _tesseract_ocr(path: Path) -> list[OcrLine]:
    """Tesseract on the image and its negative (it misses light-on-dark text)."""
    import tempfile
    from PIL import Image, ImageOps
    lines = _tesseract_pass(path)
    with tempfile.TemporaryDirectory() as td:
        neg = Path(td) / "neg.png"
        ImageOps.invert(Image.open(path).convert("RGB")).save(neg)
        for ln in _tesseract_pass(neg):
            if not any(_overlap(ln, o) > 0.3 for o in lines):
                lines.append(ln)
    return _merge_rows(lines)


def _overlap(a: OcrLine, b: OcrLine) -> float:
    ix = max(0.0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0.0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    return ix * iy / max(1.0, min(a.w * a.h, b.w * b.h))


def _merge_rows(lines: list[OcrLine]) -> list[OcrLine]:
    """Join fragments on the same text row separated by a word-sized gap."""
    lines = sorted(lines, key=lambda l: l.x)
    out: list[OcrLine] = []
    for ln in lines:
        for o in out:
            cy_a, cy_b = ln.y + ln.h / 2, o.y + o.h / 2
            same_row = abs(cy_a - cy_b) < 0.35 * max(ln.h, o.h) and \
                0.6 < ln.h / o.h < 1.65
            gap = ln.x - (o.x + o.w)
            if same_row and -0.2 * o.h < gap < 1.2 * max(ln.h, o.h):
                x0, y0 = min(o.x, ln.x), min(o.y, ln.y)
                x1, y1 = max(o.x + o.w, ln.x + ln.w), max(o.y + o.h, ln.y + ln.h)
                o.text = f"{o.text} {ln.text}"
                o.confidence = (o.confidence + ln.confidence) / 2
                o.x, o.y, o.w, o.h = x0, y0, x1 - x0, y1 - y0
                break
        else:
            out.append(OcrLine(ln.text, ln.x, ln.y, ln.w, ln.h, ln.confidence))
    return out


def _tesseract_pass(path: Path) -> list[OcrLine]:
    out = subprocess.run(["tesseract", str(path), "stdout", "--psm", "11", "tsv"],
                         capture_output=True, text=True, check=True).stdout
    groups: dict[tuple, list] = {}
    for row in out.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        conf = float(f[10])
        if conf < 0:
            continue
        key = (f[1], f[2], f[3], f[4])  # page, block, paragraph, line
        groups.setdefault(key, []).append((int(f[6]), int(f[7]), int(f[8]), int(f[9]),
                                           conf / 100.0, f[11]))
    lines = []
    for words in groups.values():
        words.sort(key=lambda t: t[0])
        x0 = min(w[0] for w in words)
        y0 = min(w[1] for w in words)
        x1 = max(w[0] + w[2] for w in words)
        y1 = max(w[1] + w[3] for w in words)
        conf = sum(w[4] for w in words) / len(words)
        lines.append(OcrLine(" ".join(w[5] for w in words), x0, y0, x1 - x0, y1 - y0, conf))
    return lines


def detect_text(path: Path, width: int, height: int, languages: list[str] | None = None,
                min_confidence: float = 0.0) -> list[OcrLine]:
    path = Path(path)
    if vision_available():
        lines = _vision_ocr(path, width, height, languages or [])
    elif tesseract_available():
        lines = _tesseract_ocr(path)
    else:
        lines = []
    lines = [l for l in lines if l.text.strip() and l.confidence >= min_confidence
             and l.w >= 2 and l.h >= 2]
    lines.sort(key=lambda l: (round(l.y / max(1.0, l.h)), l.x))
    return lines
