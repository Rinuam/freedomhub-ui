"""Tone, colour and detail adjustments applied after AI enhancement.

Spatial parameters (sharpen radius, clarity radius, grain size) are expressed in
*source-image pixels* and scaled by ``px_per_src`` so the on-screen preview and
any output resolution look the same.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import cv2
import numpy as np


@dataclass
class Adjustments:
    exposure: float = 0.0      # EV, -2..2
    contrast: float = 0.0      # -1..1
    highlights: float = 0.0    # -1..1 (negative recovers)
    shadows: float = 0.0       # -1..1 (positive lifts)
    saturation: float = 0.0    # -1..1
    vibrance: float = 0.0      # -1..1 (protects saturated colours)
    warmth: float = 0.0        # -1..1 (blue <-> amber)
    tint: float = 0.0          # -1..1 (green <-> magenta)
    clarity: float = 0.0       # 0..1 local contrast (large radius)
    clarity_radius: float = 6.0
    sharpen: float = 0.0       # 0..2 unsharp amount
    sharpen_radius: float = 0.6
    sharpen_threshold: float = 2.0   # levels; protects flat areas/gradients
    denoise: float = 0.0       # 0..1 (post, edge-preserving)
    grain: float = 0.0         # 0..1 film grain
    grain_size: float = 0.6

    def is_identity(self) -> bool:
        return all(abs(v) < 1e-6 for k, v in asdict(self).items()
                   if not k.endswith(("_radius", "_threshold", "_size")))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})


def _tone(f: np.ndarray, a: Adjustments) -> np.ndarray:
    """f: float32 RGB 0..1 (in place friendly)."""
    if a.exposure:
        f *= 2.0 ** a.exposure
    if a.warmth or a.tint:
        f[..., 0] *= 1 + 0.12 * a.warmth + 0.05 * a.tint
        f[..., 1] *= 1 - 0.08 * a.tint
        f[..., 2] *= 1 - 0.12 * a.warmth + 0.05 * a.tint
    if a.highlights or a.shadows:
        lum = (0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2])[..., None]
        hi = np.clip((lum - 0.5) * 2, 0, 1)
        lo = np.clip((0.5 - lum) * 2, 0, 1)
        f += (a.highlights * 0.35) * hi * hi * (f if a.highlights < 0 else (1 - f))
        f += (a.shadows * 0.35) * lo * lo * ((1 - f) if a.shadows > 0 else f)
    if a.contrast:
        k = 1 + a.contrast
        f[:] = (f - 0.5) * k + 0.5
    if a.saturation or a.vibrance:
        lum = (0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2])[..., None]
        sat = f.max(axis=2, keepdims=True) - f.min(axis=2, keepdims=True)
        k = 1 + a.saturation + a.vibrance * (1 - np.clip(sat * 1.5, 0, 1))
        f[:] = lum + (f - lum) * k
    np.clip(f, 0, 1, out=f)
    return f


def apply(img: np.ndarray, a: Adjustments, px_per_src: float = 1.0, seed: int = 7) -> np.ndarray:
    """Return adjusted uint8 RGB. Processes in bands to bound memory on A0/16x images."""
    if a.is_identity():
        return img
    H = img.shape[0]
    halo = int(3 * max(a.clarity_radius * px_per_src if a.clarity else 0,
                       a.sharpen_radius * px_per_src if a.sharpen else 0, 2)) + 2
    band = max(512, 4 * halo)
    out = np.empty_like(img)
    for y0 in range(0, H, band):
        y1 = min(H, y0 + band)
        p0, p1 = max(0, y0 - halo), min(H, y1 + halo)
        out[y0:y1] = _apply_band(img[p0:p1], a, px_per_src, seed + y0)[y0 - p0:y0 - p0 + (y1 - y0)]
    return out


def _apply_band(img, a: Adjustments, s: float, seed: int) -> np.ndarray:
    work = img
    if a.denoise > 0:
        h = 3 + 9 * a.denoise
        work = cv2.fastNlMeansDenoisingColored(work, None, h, h, 5, 15) if work.size < 40e6 else \
            cv2.bilateralFilter(work, 0, 12 * a.denoise + 4, max(1.0, 1.5 * s))
    f = work.astype(np.float32) / 255.0
    f = _tone(f, a)
    if a.clarity > 0 or a.sharpen > 0:
        lab = cv2.cvtColor(f, cv2.COLOR_RGB2LAB)
        L = lab[..., 0]
        if a.clarity > 0:
            sig = max(0.5, a.clarity_radius * s)
            blur = cv2.GaussianBlur(L, (0, 0), sig)
            detail = L - blur
            # midtone-weighted so blacks/whites don't clip
            w = 1 - ((L - 50) / 50) ** 2
            L += a.clarity * 0.9 * detail * np.clip(w, 0, 1)
        if a.sharpen > 0:
            sig = max(0.3, a.sharpen_radius * s)
            blur = cv2.GaussianBlur(L, (0, 0), sig)
            detail = L - blur
            thr = a.sharpen_threshold * 100 / 255
            soft = np.clip((np.abs(detail) - thr) / max(thr, 1e-3), 0, 1) if thr > 0 else 1
            L += a.sharpen * detail * soft
        lab[..., 0] = np.clip(L, 0, 100)
        f = np.clip(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB), 0, 1)
    if a.grain > 0:
        rng = np.random.default_rng(seed)
        n = rng.standard_normal(f.shape[:2]).astype(np.float32)
        gs = a.grain_size * s
        if gs > 0.6:
            n = cv2.GaussianBlur(n, (0, 0), gs * 0.5)
            n /= max(1e-6, n.std())
        lum = f.mean(axis=2, keepdims=True)
        f += (a.grain * 0.045) * n[..., None] * (1 - np.abs(lum - 0.5) * 1.2)
    return np.clip(f * 255 + 0.5, 0, 255).astype(np.uint8)
