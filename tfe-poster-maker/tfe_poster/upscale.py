"""Real-ESRGAN (ncnn/Vulkan) wrapper with a Lanczos fallback.

The ncnn build runs on Apple Silicon through MoltenVK (statically linked into
the macOS release binary) and needs no Python ML stack and no network.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
from PIL import Image

BIN_NAME = "realesrgan-ncnn-vulkan"
_PCT = re.compile(r"(\d+(?:\.\d+)?)%")


@dataclass
class UpscaleResult:
    image: np.ndarray        # RGB uint8 at the upscaled resolution
    factor: int              # 1 when no AI upscale happened
    method: str              # human-readable description


def _candidate_dirs() -> list[Path]:
    here = Path(__file__).resolve().parent
    dirs = []
    if getattr(sys, "_MEIPASS", None):                 # PyInstaller bundle
        dirs.append(Path(sys._MEIPASS) / "realesrgan")
    exe = Path(sys.executable).resolve()
    dirs.append(exe.parent.parent / "Resources" / "realesrgan")   # .app/Contents/Resources
    dirs.append(here.parent / "vendor" / "realesrgan")             # source checkout
    dirs.append(Path.home() / ".tfe-poster-maker" / "realesrgan")
    return dirs


def _ensure_executable(b: Path) -> Optional[Path]:
    """Bundled data files can lose their exec bit; fix it or run from a user copy."""
    if os.access(b, os.X_OK):
        return b
    try:
        b.chmod(b.stat().st_mode | 0o111)
        return b
    except OSError:
        pass
    dst = Path.home() / ".tfe-poster-maker" / "realesrgan"
    try:
        if not (dst / BIN_NAME).is_file():
            shutil.copytree(b.parent, dst, dirs_exist_ok=True)
        (dst / BIN_NAME).chmod(0o755)
        return dst / BIN_NAME
    except OSError:
        return None


def find_realesrgan(explicit: str = "") -> Optional[Path]:
    """Locate the realesrgan-ncnn-vulkan binary, or None."""
    for p in (explicit, os.environ.get("TFE_REALESRGAN", "")):
        if p and Path(p).is_file():
            return _ensure_executable(Path(p))
    for d in _candidate_dirs():
        b = d / BIN_NAME
        if b.is_file():
            return _ensure_executable(b)
    w = shutil.which(BIN_NAME)
    return Path(w) if w else None


def models_dir_for(binary: Path) -> Path:
    return binary.parent / "models"


def available_models(binary: Optional[Path]) -> list[str]:
    if not binary:
        return []
    md = models_dir_for(binary)
    return sorted({p.stem.rsplit("-x", 1)[0] if p.stem.startswith("realesr-animevideov3") else p.stem
                   for p in md.glob("*.param")})


def _model_file_stem(model: str, scale: int) -> str:
    # animevideov3 ships one file per scale (…-x2/-x3/-x4); the others are 4x only.
    return f"{model}-x{scale}" if model == "realesr-animevideov3" else model


def realesrgan_upscale(img: np.ndarray, binary: Path, model: str, scale: int = 4,
                       tile: int = 0,
                       progress: Optional[Callable[[float], None]] = None) -> np.ndarray:
    md = models_dir_for(binary)
    if not (md / f"{_model_file_stem(model, scale)}.param").is_file():
        raise FileNotFoundError(f"Model '{model}' (x{scale}) not found in {md}")
    with tempfile.TemporaryDirectory(prefix="tfe_esr_") as td:
        src, dst = Path(td) / "in.png", Path(td) / "out.png"
        Image.fromarray(img).save(src, compress_level=1)
        cmd = [str(binary), "-i", str(src), "-o", str(dst), "-n", model,
               "-s", str(scale), "-m", str(md), "-f", "png"]
        if tile:
            cmd += ["-t", str(tile)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        log = []
        assert proc.stdout is not None
        for line in proc.stdout:
            log.append(line.rstrip())
            m = _PCT.search(line)
            if m and progress:
                progress(min(100.0, float(m.group(1))) / 100.0)
        rc = proc.wait()
        if rc != 0 or not dst.is_file():
            raise RuntimeError(f"Real-ESRGAN failed (exit {rc}):\n" + "\n".join(log[-15:]))
        out = np.asarray(Image.open(dst).convert("RGB"))
    exp = (img.shape[0] * scale, img.shape[1] * scale)
    if out.shape[:2] != exp:
        raise RuntimeError(f"Real-ESRGAN produced {out.shape[:2]}, expected {exp}")
    return out


def upscale(img: np.ndarray, needed_factor: float, enabled: bool, model: str,
            binary_path: str = "", tile: int = 0,
            progress: Optional[Callable[[float], None]] = None) -> UpscaleResult:
    """AI-upscale 4x when the print needs more pixels than the source has."""
    if not enabled:
        return UpscaleResult(img, 1, "disabled (Lanczos resample only)")
    if needed_factor <= 1.0:
        return UpscaleResult(img, 1, "not needed (source already >= target dpi)")
    binary = find_realesrgan(binary_path)
    if binary is None:
        return UpscaleResult(img, 1, "Real-ESRGAN not found - Lanczos fallback")
    out = realesrgan_upscale(img, binary, model, 4, tile, progress)
    return UpscaleResult(out, 4, f"Real-ESRGAN {model} x4")


def resample(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """Resize to exactly (w, h): Lanczos when enlarging, area when shrinking."""
    if img.shape[1] == w and img.shape[0] == h:
        return img
    shrinking = w < img.shape[1] and h < img.shape[0]
    interp = cv2.INTER_AREA if shrinking else cv2.INTER_LANCZOS4
    return cv2.resize(img, (w, h), interpolation=interp)
