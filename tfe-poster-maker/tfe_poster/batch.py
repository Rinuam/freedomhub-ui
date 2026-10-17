"""Batch processing of a folder (no review step; reuses saved project edits when present)."""
from __future__ import annotations

import csv
import traceback
from pathlib import Path
from typing import Callable, Optional

from .enhance.pipeline import EnhanceSettings
from .formats import OutputTarget
from .project import PROJECT_SUFFIX, Project

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def find_images(folder: Path) -> list[Path]:
    return sorted(p for p in Path(folder).iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith("."))


def process_one(path: Path, out_dir: Path, enhance: EnhanceSettings, targets: list[OutputTarget],
                vectorise: str = "auto", font_id: str = "",
                progress: Callable[[str, float], None] = lambda m, f: None,
                should_stop: Callable[[], bool] = lambda: False) -> dict:
    proj = Project(Path(path))
    proj.enhance = EnhanceSettings.from_dict(enhance.to_dict())
    proj.targets = [OutputTarget.from_dict(t.to_dict()) for t in targets]
    proj.default_vectorise = vectorise
    proj.load()
    saved = [out_dir / f"{path.stem}{PROJECT_SUFFIX}", path.with_name(path.stem + PROJECT_SUFFIX)]
    reused = any(sc.is_file() and proj.load_edits(sc, settings=False) for sc in saved)
    if not reused:
        proj.detect_text(lambda m, f: progress(m, 0.03 * f))
        if font_id:
            from .text.engine import autofit
            for b in proj.blocks:
                b.font_id = font_id
                autofit(b)
    proj.ocr_backend = proj.ocr_backend or "saved edits"
    proj.run_enhance(lambda m, f: progress(m, 0.03 + 0.67 * f), should_stop)
    rep = proj.export(out_dir, lambda m, f: progress(m, 0.7 + 0.3 * f), should_stop)
    rep["reused_edits"] = reused
    return rep


def run_batch(folder: Path, out_dir: Path, enhance: EnhanceSettings, targets: list[OutputTarget],
              vectorise: str = "auto", font_id: str = "",
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
            rep = process_one(img, out_dir, enhance, targets, vectorise, font_id, cb, should_stop)
            rows.append({"file": img.name, "status": "ok", "ai": f"x{rep['ai_factor']} "
                         f"{rep['enhancement'].get('method', '')}",
                         "text_blocks": rep["text_blocks"], "vectorised": rep["vector_blocks"],
                         "outputs": " | ".join(rep["outputs"]), "error": ""})
        except Exception as e:
            rows.append({"file": img.name, "status": "error", "ai": "", "text_blocks": "",
                         "vectorised": "", "outputs": "",
                         "error": f"{e}\n{traceback.format_exc(limit=3)}"})
    if rows:
        with open(out_dir / "batch_summary.csv", "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
    return rows
