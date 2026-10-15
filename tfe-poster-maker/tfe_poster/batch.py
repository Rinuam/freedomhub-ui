"""Batch processing of a folder (no review step; uses saved edits when present)."""
from __future__ import annotations

import csv
import traceback
from pathlib import Path
from typing import Callable, Optional

from .config import Settings
from .project import Project, SIDE_CAR_SUFFIX

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


def find_images(folder: Path) -> list[Path]:
    return sorted(p for p in Path(folder).iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith("."))


def process_one(path: Path, out_dir: Path, settings: Settings,
                progress: Callable[[str, float], None] = lambda m, f: None) -> dict:
    proj = Project(Path(path), settings)
    proj.load()
    sidecars = [out_dir / f"{path.stem}{SIDE_CAR_SUFFIX}", path.with_name(path.stem + SIDE_CAR_SUFFIX)]
    reused = any(sc.is_file() and proj.load_sidecar(sc) for sc in sidecars)
    if not reused:
        proj.detect_text(lambda m, f: progress(m, 0.05 * f))
    proj.ocr_backend = proj.ocr_backend or "saved edits"
    proj.prepare(lambda m, f: progress(m, 0.05 + 0.6 * f))
    rep = proj.export(out_dir, lambda m, f: progress(m, 0.65 + 0.35 * f))
    rep["reused_edits"] = reused
    return rep


def run_batch(folder: Path, out_dir: Path, settings: Settings,
              on_progress: Optional[Callable[[int, int, str, float], None]] = None,
              should_stop: Callable[[], bool] = lambda: False) -> list[dict]:
    folder, out_dir = Path(folder), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    images = find_images(folder)
    rows = []
    for i, img in enumerate(images):
        if should_stop():
            break
        cb = (lambda m, f, i=i, n=img.name: on_progress(i, len(images), f"{n}: {m}", f)) \
            if on_progress else (lambda m, f: None)
        try:
            rep = process_one(img, out_dir, settings, cb)
            rows.append({"file": img.name, "status": "ok", "native_ppi": rep["native_ppi"],
                         "effective_ppi": rep["effective_ppi"], "upscale": rep["upscale"]["method"],
                         "text_boxes": rep["text_boxes"], "vectorised": rep["vector_text_boxes"],
                         "pdf": rep["outputs"]["pdf"], "png": rep["outputs"]["png"], "error": ""})
        except Exception as e:  # keep going; report at the end
            rows.append({"file": img.name, "status": "error", "native_ppi": "", "effective_ppi": "",
                         "upscale": "", "text_boxes": "", "vectorised": "", "pdf": "", "png": "",
                         "error": f"{e}\n{traceback.format_exc(limit=3)}"})
    if rows:
        with open(out_dir / "batch_summary.csv", "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
    return rows
