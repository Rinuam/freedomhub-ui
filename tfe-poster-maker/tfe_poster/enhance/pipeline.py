"""Image enhancement: restore -> AI super-resolution passes (up to 16x) -> faces.

Backends, best first:
  * PyTorch + spandrel on the Apple GPU (MPS): DRCT-L, HAT-L, DAT2, ATD, PLKSR, …
  * realesrgan-ncnn-vulkan binary (fast, small)
  * Lanczos (always available)
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, asdict, field
from typing import Callable, Optional

import cv2
import numpy as np

from .adjust import Adjustments
from .zoo import BY_ID, DEFAULT_PRESET, PRESETS, model_path

Progress = Callable[[str, float], None]


def _noop(m, f):
    pass


@dataclass
class EnhanceSettings:
    preset: str = DEFAULT_PRESET
    model: str = "auto"                        # auto | zoo id | file path | "ncnn:<name>" | "lanczos"
    detail_model: str = ""                     # optional second model blended per tile
    detail_blend: float = 0.0                  # 0..1
    factor: str = "auto"                       # auto | 2 | 4 | 8 | 16
    max_factor: int = 16
    pre_restore: str = "off"                   # off | fbcnn | scunet
    pre_strength: float = 1.0
    face: str = "off"                          # off | gfpgan-1.4 | codeformer
    face_strength: float = 0.8
    face_fidelity: float = 0.7                 # CodeFormer only (0 = quality, 1 = fidelity)
    tta: bool = False                          # 8x self-ensemble (8x slower)
    precision: str = "fp32"                    # fp32 | fp16 | bf16
    tile: int = 384
    device: str = "auto"
    adjust: Adjustments = field(default_factory=Adjustments)

    def to_dict(self):
        d = asdict(self)
        d["adjust"] = self.adjust.to_dict()
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        adj = Adjustments.from_dict(d.pop("adjust", {}))
        s = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        s.adjust = adj
        return s

    def apply_preset(self, name: str) -> None:
        m, dm, blend, _ = PRESETS[name]
        self.preset, self.model, self.detail_model, self.detail_blend = name, m, dm, blend

    def cache_key(self) -> dict:
        d = self.to_dict()
        d.pop("adjust")
        d.pop("preset")
        d.pop("device")
        return d


@dataclass
class EnhanceResult:
    image: np.ndarray
    factor: float
    method: str
    passes: list[str]
    faces: int = 0
    seconds: float = 0.0


def resample(img: np.ndarray, w: int, h: int) -> np.ndarray:
    if img.shape[1] == w and img.shape[0] == h:
        return img
    shrink = w < img.shape[1] and h < img.shape[0]
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA if shrink else cv2.INTER_LANCZOS4)


def choose_factor(setting: str, needed: float, model_scale: int, max_factor: int = 16) -> int:
    if setting != "auto":
        return int(setting)
    f = model_scale
    while f < needed and f < max_factor:
        f *= 2
    return int(min(f, max_factor))


def jpeg_blockiness(img: np.ndarray) -> float:
    """Ratio of gradient energy on the 8x8 JPEG grid vs elsewhere (1.0 = no blocking)."""
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
    dx, dy = np.abs(np.diff(g, axis=1)), np.abs(np.diff(g, axis=0))
    cx, cy = np.arange(dx.shape[1]) % 8 == 7, np.arange(dy.shape[0]) % 8 == 7
    bx = dx[:, cx].mean() / max(1e-3, dx[:, ~cx].mean())
    by = dy[cy].mean() / max(1e-3, dy[~cy].mean())
    return float((bx + by) / 2)


BLOCKY = 1.12


def resolve_auto(s: EnhanceSettings, src: np.ndarray) -> tuple[EnhanceSettings, str]:
    """Resolve model == 'auto' to concrete models for this image."""
    if s.model != "auto":
        return s, ""
    r = EnhanceSettings.from_dict(s.to_dict())
    b = jpeg_blockiness(src)
    if b >= BLOCKY:
        r.model = "hat-l-real" if model_path("hat-l-real") else "dat2-webphoto"
        if r.pre_restore == "off" and model_path("fbcnn"):
            r.pre_restore = "fbcnn"
        why = f"JPEG blocking detected ({b:.2f}) -> FBCNN + {BY_ID.get(r.model).name if r.model in BY_ID else r.model}"
    else:
        r.model = "drct-l-hq"
        why = f"clean source ({b:.2f}) -> DRCT-L"
    for fallback in (r.model, "hat-l-real", "dat2-webphoto", "drct-l-hq", "plksr-nomos2"):
        if model_path(fallback):
            r.model = fallback
            break
    return r, why


class Enhancer:
    def __init__(self, s: EnhanceSettings, src: Optional[np.ndarray] = None):
        self.auto_reason = ""
        if s.model == "auto" and src is not None:
            s, self.auto_reason = resolve_auto(s, src)
        self.s = s
        self._sr = None
        self._detail = None
        self.backend = self._pick_backend()

    # ------------------------------------------------------------ backends
    def _pick_backend(self) -> str:
        m = self.s.model
        if m == "lanczos":
            return "lanczos"
        if m.startswith("ncnn:"):
            from ..upscale import find_realesrgan
            return "ncnn" if find_realesrgan() else "lanczos"
        from .torch_sr import torch_available
        if torch_available() and model_path(m):
            return "torch"
        from ..upscale import find_realesrgan
        return "ncnn" if find_realesrgan() else "lanczos"

    @property
    def model_scale(self) -> int:
        if self.backend == "torch":
            return self._get_sr().scale
        return 4

    def _get_sr(self):
        if self._sr is None:
            from .torch_sr import SRModel
            s = self.s
            self._sr = SRModel(model_path(s.model), s.device, s.precision, s.tta)
            if s.detail_model and s.detail_blend > 0 and model_path(s.detail_model):
                d = SRModel(model_path(s.detail_model), s.device, s.precision, s.tta)
                if d.scale == self._sr.scale:
                    self._detail = d
        return self._sr

    def describe(self) -> str:
        s = self.s
        if self.backend == "torch":
            name = BY_ID[s.model].name if s.model in BY_ID else str(s.model).rsplit("/", 1)[-1]
            extra = ""
            if self._detail is not None or (s.detail_model and s.detail_blend > 0):
                dn = BY_ID[s.detail_model].name if s.detail_model in BY_ID else s.detail_model
                extra = f" + {int(s.detail_blend * 100)}% {dn}"
            return f"{name}{extra}{' · TTA x8' if s.tta else ''}"
        if self.backend == "ncnn":
            n = s.model[5:] if s.model.startswith("ncnn:") else "realesr-animevideov3"
            return f"Real-ESRGAN ncnn {n}"
        return "Lanczos (no AI model available)"

    # -------------------------------------------------------------- passes
    def _sr_pass(self, img, progress, should_stop) -> np.ndarray:
        if self.backend == "torch":
            from .torch_sr import tiled_upscale, blend_fn
            sr = self._get_sr()
            fn = blend_fn(sr, self._detail, self.s.detail_blend) if self._detail else sr
            return tiled_upscale(img, fn, sr.scale, self.s.tile, 32, progress, should_stop)
        if self.backend == "ncnn":
            from ..upscale import find_realesrgan, realesrgan_upscale
            name = self.s.model[5:] if self.s.model.startswith("ncnn:") else "realesr-animevideov3"
            return realesrgan_upscale(img, find_realesrgan(), name, 4, 0, progress)
        h, w = img.shape[:2]
        return cv2.resize(img, (w * 4, h * 4), interpolation=cv2.INTER_LANCZOS4)

    def pre_restore(self, img: np.ndarray, progress: Progress = _noop, should_stop=lambda: False) -> np.ndarray:
        s = self.s
        if s.pre_restore == "off" or not model_path(s.pre_restore):
            return img
        from .torch_sr import SRModel, tiled_upscale
        m = SRModel(model_path(s.pre_restore), s.device, "fp32", False)
        out = tiled_upscale(img, m, 1, 512, 32, lambda f: progress("Restoring (JPEG/noise)…", f), should_stop)
        if s.pre_strength < 1:
            out = cv2.addWeighted(out, s.pre_strength, img, 1 - s.pre_strength, 0)
        return out

    def run(self, src: np.ndarray, factor: int, progress: Progress = _noop,
            should_stop: Callable[[], bool] = lambda: False, faces: bool = True) -> EnhanceResult:
        t0 = time.time()
        s = self.s
        img = self.pre_restore(src, progress, should_stop)
        passes = []
        if s.pre_restore != "off" and model_path(s.pre_restore):
            passes.append(BY_ID[s.pre_restore].name)
        if factor <= 1:
            return EnhanceResult(img, 1, "none", passes, 0, time.time() - t0)
        m = self.model_scale if self.backend == "torch" else 4
        plan = []        # list of (downscale_before, model_scale) ; overall product = factor
        remaining = float(factor)
        while remaining > 1.001:
            if remaining >= m - 1e-6:
                plan.append((1.0, m))
                remaining /= m
            else:
                plan.append((remaining / m, m))
                remaining = 1.0
        # progress weight ~ input pixels of each pass
        h, w = img.shape[:2]
        cost, cur = [], 1.0
        for pre, sc in plan:
            cur *= pre
            cost.append(cur * cur)
            cur *= sc
        tot = sum(cost)
        done = 0.0
        nfaces = 0
        for i, (pre, sc) in enumerate(plan):
            if pre < 0.999:
                img = cv2.resize(img, (max(1, round(img.shape[1] * pre)), max(1, round(img.shape[0] * pre))),
                                 interpolation=cv2.INTER_AREA)
            msg = f"AI enhance pass {i + 1}/{len(plan)} ({self.describe()})"
            base, wgt = done, cost[i] / tot
            img = self._sr_pass(img, lambda f: progress(msg, 0.95 * (base + wgt * f)), should_stop)
            done += wgt
            passes.append(f"x{sc * pre:g} {self.describe()}")
            if i == 0 and faces and s.face != "off" and model_path(s.face) and model_path("yunet"):
                from .faces import FaceRestorer
                progress("Restoring faces…", 0.95 * done)
                fr = FaceRestorer(s.face, s.device, s.face_fidelity)
                img, nfaces = fr.apply(img, s.face_strength)
                if nfaces:
                    passes.append(f"{nfaces} face(s) {BY_ID[s.face].name}")
        # exact factor (plan products are exact; guard rounding)
        tw, th = round(src.shape[1] * factor), round(src.shape[0] * factor)
        img = resample(img, tw, th)
        progress("Enhancement done", 1.0)
        return EnhanceResult(img, factor, self.describe(), passes, nfaces, time.time() - t0)

    def run_region(self, src: np.ndarray, factor: int, should_stop=lambda: False) -> np.ndarray:
        """Same pipeline on a crop (used after inpainting) - no face pass."""
        return self.run(src, factor, _noop, should_stop, faces=False).image


def estimate_seconds(model_id: str, src_px: int, factor: int, tta: bool = False,
                     device: str = "mps") -> float:
    """Very rough planning estimate for the UI (M1/M2-class GPU)."""
    speed = BY_ID[model_id].speed if model_id in BY_ID else 1
    mp_per_s = {1: 0.006, 2: 0.02, 3: 0.06, 4: 0.15, 5: 0.8}[speed]   # input MP/s at 4x (M-series GPU)
    if device == "cpu":
        mp_per_s /= 10
    passes_px = 0.0
    cur, f = src_px / 1e6, factor
    while f > 1.001:
        step = min(4, f)
        passes_px += cur * (step / 4) ** 2 if step < 4 else cur
        cur *= step * step
        f /= step
    return passes_px / mp_per_s * (8 if tta else 1)
