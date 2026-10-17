"""Curated model catalogue + offline model store.

Every entry was downloaded and loaded with spandrel during development; the
sha256/size are verified after each download. Licences are listed because
some models (e.g. CodeFormer) are non-commercial - check before company use.

Models live in (first match wins):
  1. the bundled  <app>/Contents/Resources/models   (read-only, shipped with the .app)
  2. the user dir ~/Library/Application Support/TFE Poster Maker/models  (downloads, imports)
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

GH = "https://github.com"
PH = f"{GH}/Phhofm/models/releases/download"


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    kind: str            # sr | face | inpaint
    arch: str
    scale: int
    file: str
    url: str
    sha256: str
    size: int
    license: str
    commercial_ok: bool
    speed: int           # 1 (slowest) .. 5 (fastest)
    best_for: str
    notes: str = ""

    @property
    def size_mb(self) -> float:
        return self.size / 1e6


CATALOG: list[ModelInfo] = [
    # ---- top quality transformers (slow, best) ----
    ModelInfo("drct-l-hq", "DRCT-L · Nomos2 HQ (max fidelity)", "sr", "DRCT", 4,
              "4xNomos2_hq_drct-l.safetensors", f"{PH}/4xNomos2_hq_drct-l/4xNomos2_hq_drct-l.safetensors",
              "1a10632101bb2aca6151301dd811921f1c438ff55159fd579fb576c143477797", 242543780,
              "CC-BY-4.0", True, 1, "Clean AI art & illustrations, crisp edges, no hallucinated texture",
              "Highest fidelity; best default for ChatGPT/Midjourney images saved as PNG."),
    ModelInfo("hat-l-real", "HAT-L · Nomos8k OTF (real-world detail)", "sr", "HAT", 4,
              "4xNomos8kHAT-L_otf.pth", f"{PH}/4xNomos8kHAT-L_otf/4xNomos8kHAT-L_otf.pth",
              "16c10572caf29b2381e75821364ef499a582039c5baeb6a5f9fc12d6366163ca", 165817474,
              "CC-BY-4.0", True, 1, "Photographic images with noise/blur/compression",
              "Trained with on-the-fly degradations: restores and adds plausible detail."),
    ModelInfo("dat2-webphoto", "DAT2 · RealWebPhoto v4 (compressed web images)", "sr", "DAT", 4,
              "4xRealWebPhoto_v4_dat2.safetensors",
              f"{PH}/4xRealWebPhoto_v4_dat2/4xRealWebPhoto_v4_dat2.safetensors",
              "819047acf43073f63ea7289ed94d6991ba8446a3bdf38e274fadfcbaa2b7381d", 139792588,
              "CC-BY-4.0", True, 2, "JPEG/WebP downloads, screenshots, social-media images",
              "Removes JPEG/WebP artefacts and resize blur while upscaling."),
    ModelInfo("atd-hq", "ATD · Nomos2 HQ", "sr", "ATD", 4,
              "4xNomos2_hq_atd.pth", f"{PH}/4xNomos2_hq_atd/4xNomos2_hq_atd.pth",
              "06e007a70af59c4e3acfbfbd5dca4ed20dfaeadd9857ffca63c8c807a8c40283", 81890530,
              "CC-BY-4.0", True, 1, "Clean images, fine structures", "Alternative to DRCT-L."),
    ModelInfo("dat-nomos8k", "DAT · Nomos8k (photo GAN)", "sr", "DAT", 4,
              "4xNomos8kDAT.pth", f"{PH}/4xNomos8kDAT/4xNomos8kDAT.pth",
              "2926aa419b6f47edfec125d5314af172b6c4ef16f483e44e0d2428bc0632d0f4", 154687598,
              "CC-BY-4.0", True, 2, "Photos, strong texture generation"),
    ModelInfo("swinir-l-real", "SwinIR-L · Real-world GAN", "sr", "SwinIR", 4,
              "003_realSR_BSRGAN_DFOWMFC_s64w8_SwinIR-L_x4_GAN.pth",
              f"{GH}/JingyunLiang/SwinIR/releases/download/v0.0/003_realSR_BSRGAN_DFOWMFC_s64w8_SwinIR-L_x4_GAN.pth",
              "99adfa91350a84c99e946c1eb3d8fce34bc28f57d807b09dc8fe40a316328c0a", 142473939,
              "Apache-2.0", True, 2, "Heavily degraded photos"),
    # ---- fast / balanced ----
    ModelInfo("plksr-nomos2", "RealPLKSR · Nomos2 (fast, sharp)", "sr", "PLKSR", 4,
              "4xNomos2_realplksr_dysample.pth",
              f"{PH}/4xNomos2_realplksr_dysample/4xNomos2_realplksr_dysample.pth",
              "96c8476ed2c42107628d10562b32ae89e7be3c2f7a53d29504823e9bafe8121d", 29715988,
              "CC-BY-4.0", True, 4, "Quick previews and batches with good quality"),
    ModelInfo("plksr-webphoto", "RealPLKSR · WebPhoto (fast, de-JPEG)", "sr", "PLKSR", 4,
              "4xNomosWebPhoto_RealPLKSR.pth", f"{PH}/4xNomosWebPhoto_RealPLKSR/4xNomosWebPhoto_RealPLKSR.pth",
              "a9db66c9b674c6a5025b6ef3bee71a57c33b8605d8a2de0980470f89002efbbe", 29683482,
              "CC-BY-4.0", True, 4, "Fast option for compressed web images"),
    ModelInfo("animesharp-v4", "RCAN · AnimeSharp V4 (2x, flat art)", "sr", "RCAN", 2,
              "2x-AnimeSharpV4_RCAN.safetensors",
              f"{GH}/Kim2091/Kim2091-Models/releases/download/2x-AnimeSharpV4/2x-AnimeSharpV4_RCAN.safetensors",
              "6470bb91d6622d6acdff81132c1a8615b961b919ce2b9a01ce993378500cfbe1", 31053198,
              "CC-BY-NC-SA-4.0", False, 3, "Anime, cartoons, flat vector-like art (2x per pass)"),
    ModelInfo("esrgan-x4plus", "Real-ESRGAN x4plus (classic)", "sr", "ESRGAN", 4,
              "RealESRGAN_x4plus.pth", f"{GH}/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
              "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1", 67040989,
              "BSD-3-Clause", True, 3, "General purpose"),
    ModelInfo("esrgan-anime6b", "Real-ESRGAN x4plus anime 6B", "sr", "ESRGAN", 4,
              "RealESRGAN_x4plus_anime_6B.pth",
              f"{GH}/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
              "f872d837d3c90ed2e05227bed711af5671a6fd1c9f7d7e91c911a61f155e99da", 17938799,
              "BSD-3-Clause", True, 4, "Anime illustrations"),
    ModelInfo("esrgan-x2plus", "Real-ESRGAN x2plus", "sr", "ESRGAN", 2,
              "RealESRGAN_x2plus.pth", f"{GH}/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
              "49fafd45f8fd7aa8d31ab2a22d14d91b536c34494a5cfe31eb5d89c2fa266abb", 67061725,
              "BSD-3-Clause", True, 3, "Mild 2x enlargement"),
    ModelInfo("esrgan-general-v3", "Real-ESRGAN general v3 (tiny, fastest)", "sr", "SRVGG", 4,
              "realesr-general-x4v3.pth",
              f"{GH}/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
              "8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292", 4885111,
              "BSD-3-Clause", True, 5, "Drafts"),
    # ---- faces ----
    ModelInfo("gfpgan-1.4", "GFPGAN 1.4 (face restoration)", "face", "GFPGAN", 1,
              "GFPGANv1.4.pth", f"{GH}/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth",
              "e2cd4703ab14f4d01fd1383a8a8b266f9a5833dacee8e6a79d3bf21a1b6be5ad", 348632874,
              "Apache-2.0", True, 3, "Faces in AI images and photos"),
    ModelInfo("codeformer", "CodeFormer (face restoration)", "face", "CodeFormer", 1,
              "codeformer.pth", f"{GH}/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth",
              "1009e537e0c2a07d4cabce6355f53cb66767cd4b4297ec7a4a64ca4b8a5684b7", 376637898,
              "S-Lab 1.0 (NON-COMMERCIAL)", False, 3, "Faces; fidelity slider",
              "Non-commercial licence: do not use for company deliverables without permission."),
    ModelInfo("yunet", "YuNet face detector (for face restoration)", "detector", "YuNet", 1,
              "face_detection_yunet_2023mar.onnx",
              "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
              "face_detection_yunet/face_detection_yunet_2023mar.onnx",
              "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4", 232589,
              "MIT", True, 5, "Finds faces and eye/mouth landmarks"),
    # ---- pre-restoration (run at source resolution before upscaling) ----
    ModelInfo("fbcnn", "FBCNN (JPEG artefact removal)", "restore", "FBCNN", 1,
              "fbcnn_color.pth", f"{GH}/jiaxi-jiang/FBCNN/releases/download/v1.0/fbcnn_color.pth",
              "8b0e4ef23d59cf7ac934a342cb31a17619e4fa4a0b3374a9d78c5174312387e8", 287755111,
              "Apache-2.0", True, 3, "Blocky/ringing JPEGs before upscaling"),
    ModelInfo("scunet", "SCUNet real (denoise)", "restore", "SCUNet", 1,
              "scunet_color_real_psnr.pth", f"{GH}/cszn/KAIR/releases/download/v1.0/scunet_color_real_psnr.pth",
              "fa78899ba2caec9d235a900e91d96c689da71c42029230c2028b00f09f809c2e", 71982841,
              "Apache-2.0", True, 3, "Noisy / grainy sources before upscaling"),
    # ---- inpainting ----
    ModelInfo("lama", "LaMa big (text removal / inpainting)", "inpaint", "LaMa", 1,
              "big-lama.pt", f"{GH}/Sanster/models/releases/download/add_big_lama/big-lama.pt",
              "344c77bbcb158f17dd143070d1e789f38a66c04202311ae3a258ef66667a9ea9", 205669692,
              "Apache-2.0", True, 4, "Removing text before vector replacement"),
]

BY_ID = {m.id: m for m in CATALOG}

# Models fetched by `scripts/fetch_models.sh default` and bundled into the .app.
DEFAULT_BUNDLE = ["drct-l-hq", "dat2-webphoto", "hat-l-real", "plksr-nomos2", "gfpgan-1.4", "yunet",
                  "fbcnn", "lama"]

PRESETS = {
    # name: (primary model, detail model, detail blend, description)
    "Auto (analyse image)": ("auto", "", 0.0,
                             "Clean PNG -> DRCT-L; JPEG/WebP-blocky -> FBCNN clean-up + HAT-L"),
    "Best · clean digital art (DRCT-L)": ("drct-l-hq", "", 0.0,
                                          "Highest fidelity on clean PNG art; razor-sharp edges"),
    "Best · real-world / photo (HAT-L)": ("hat-l-real", "", 0.0,
                                          "Restores blur, noise and compression; generates detail"),
    "Compressed JPEG / web image (DAT2)": ("dat2-webphoto", "", 0.0,
                                           "Removes JPEG/WebP blocking while upscaling; faster"),
    "Clean art + extra texture (DRCT-L + HAT-L)": ("drct-l-hq", "hat-l-real", 0.35,
                                                   "Blend of fidelity and generated micro-detail"),
    "Anime / flat colours (AnimeSharp V4)": ("animesharp-v4", "", 0.0, "2x per pass, flat shading"),
    "Fast preview (RealPLKSR)": ("plksr-nomos2", "", 0.0, "~20x faster; good for drafts and batches"),
}
DEFAULT_PRESET = "Auto (analyse image)"


def user_dir() -> Path:
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / "TFE Poster Maker" / "models"
    else:
        d = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "tfe-poster-maker" / "models"
    return d


def bundled_dirs() -> list[Path]:
    here = Path(__file__).resolve().parent.parent.parent
    dirs = []
    if getattr(sys, "_MEIPASS", None):
        dirs.append(Path(sys._MEIPASS) / "models")
    dirs.append(Path(sys.executable).resolve().parent.parent / "Resources" / "models")
    dirs.append(here / "vendor" / "models")
    if os.environ.get("TFE_MODELS"):
        dirs.insert(0, Path(os.environ["TFE_MODELS"]))
    return dirs


def model_path(model_id_or_file: str) -> Optional[Path]:
    """Path of an installed model (catalogue id, file name, or absolute path)."""
    p = Path(model_id_or_file)
    if p.is_absolute() and p.is_file():
        return p
    info = BY_ID.get(model_id_or_file)
    fname = info.file if info else model_id_or_file
    for d in bundled_dirs() + [user_dir()]:
        if (d / fname).is_file():
            return d / fname
    return None


def is_installed(model_id: str) -> bool:
    return model_path(model_id) is not None


def custom_models() -> list[Path]:
    """User-imported spandrel-compatible models (any OpenModelDB model works)."""
    known = {m.file for m in CATALOG}
    d = user_dir()
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.suffix in (".pth", ".safetensors", ".ckpt")
                  and p.name not in known)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def download(model_id: str, progress: Optional[Callable[[float], None]] = None,
             dest_dir: Optional[Path] = None, should_stop: Callable[[], bool] = lambda: False) -> Path:
    info = BY_ID[model_id]
    dest_dir = Path(dest_dir or user_dir())
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / info.file
    if dest.is_file() and dest.stat().st_size == info.size:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(info.url, headers={"User-Agent": "TFE-Poster-Maker"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as fh:
        total = int(r.headers.get("Content-Length") or info.size)
        done = 0
        while True:
            if should_stop():
                raise InterruptedError("download cancelled")
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if progress:
                progress(min(1.0, done / max(1, total)))
    digest = sha256(tmp)
    if digest != info.sha256:
        tmp.unlink(missing_ok=True)
        raise IOError(f"Checksum mismatch for {info.file}: got {digest}")
    tmp.replace(dest)
    return dest


def import_model(src: Path) -> Path:
    """Copy a user-provided .pth/.safetensors into the model store after validating it."""
    from .torch_sr import load_descriptor
    load_descriptor(src)                       # raises if spandrel can't load it
    d = user_dir()
    d.mkdir(parents=True, exist_ok=True)
    dst = d / src.name
    shutil.copy2(src, dst)
    return dst


def remove(model_id_or_path: str) -> None:
    p = model_path(model_id_or_path)
    if p and str(user_dir()) in str(p):
        p.unlink()
