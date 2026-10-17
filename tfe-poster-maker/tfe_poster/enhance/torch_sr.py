"""PyTorch super-resolution via spandrel, on Apple-Silicon GPU (MPS) or CPU.

* any spandrel architecture (DRCT, HAT, DAT, ATD, SwinIR, PLKSR, RCAN, ESRGAN…)
* tiled inference with overlap + feathered blending (no seams), processed in
  row bands so 16x outputs never need a full float buffer
* optional 8-way self-ensemble (TTA) for a little extra fidelity
* optional blend of a second "detail" model per tile
"""
from __future__ import annotations

import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import numpy as np

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")   # unsupported ops -> CPU


class Cancelled(Exception):
    pass


TORCH_ERROR = ""


def torch_available() -> bool:
    global TORCH_ERROR
    try:
        import torch  # noqa: F401
        import spandrel  # noqa: F401
        return True
    except Exception as e:      # keep the reason for `doctor`
        TORCH_ERROR = f"{type(e).__name__}: {e}"
        return False


def device_name(prefer: str = "auto") -> str:
    import torch
    if prefer in ("cpu", "mps", "cuda"):
        return prefer
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


_lock = threading.Lock()


@lru_cache(maxsize=4)
def _load(path: str, device: str, precision: str):
    import spandrel
    try:
        import spandrel_extra_arches
        spandrel_extra_arches.install(ignore_duplicates=True)
    except Exception:
        pass
    desc = spandrel.ModelLoader(device="cpu").load_from_file(path)
    desc.model.eval()
    import torch
    dtype = torch.float32
    if precision == "fp16" and desc.supports_half and device != "cpu":
        dtype = torch.float16
    elif precision == "bf16" and desc.supports_bfloat16:
        dtype = torch.bfloat16
    desc.to(device)
    desc.model.to(dtype)
    return desc, dtype


def load_descriptor(path, device: str = "cpu", precision: str = "fp32"):
    return _load(str(path), device, precision)[0]


def model_scale(path) -> int:
    return int(load_descriptor(path).scale)


class SRModel:
    """Callable: RGB uint8 tile (h, w, 3) -> RGB float32 tile (h*s, w*s, 3) in 0..1."""

    def __init__(self, path, device: str = "auto", precision: str = "fp32", tta: bool = False):
        self.device = device_name(device)
        self.desc, self.dtype = _load(str(path), self.device, precision)
        self.scale = int(self.desc.scale)
        self.tta = tta

    def _run(self, t):
        import torch
        with torch.inference_mode():
            return self.desc(t)          # spandrel pads to size requirements, I/O in [0, 1]

    def __call__(self, tile: np.ndarray) -> np.ndarray:
        import torch
        t = torch.from_numpy(np.ascontiguousarray(tile)).permute(2, 0, 1)[None]
        t = t.to(self.device, dtype=self.dtype) / 255.0
        with _lock:   # one GPU job at a time
            if not self.tta:
                out = self._run(t)
            else:
                acc = None
                for rot in range(4):
                    for flip in (False, True):
                        x = torch.rot90(t, rot, (2, 3))
                        if flip:
                            x = torch.flip(x, (3,))
                        y = self._run(x)
                        if flip:
                            y = torch.flip(y, (3,))
                        y = torch.rot90(y, -rot, (2, 3))
                        acc = y.float() if acc is None else acc + y.float()
                out = acc / 8.0
            res = out[0].float().clamp(0, 1).permute(1, 2, 0).cpu().numpy()
        if self.device == "mps":
            torch.mps.empty_cache()
        return res


def _starts(n: int, tile: int, overlap: int) -> list[int]:
    if n <= tile:
        return [0]
    step = tile - overlap
    s = list(range(0, n - tile, step))
    s.append(n - tile)
    return s


def _ramp(n: int, ov_lo: int, ov_hi: int) -> np.ndarray:
    w = np.ones(n, np.float32)
    if ov_lo > 0:
        w[:ov_lo] = np.linspace(0.0, 1.0, ov_lo + 2, dtype=np.float32)[1:-1]
    if ov_hi > 0:
        w[n - ov_hi:] = np.linspace(1.0, 0.0, ov_hi + 2, dtype=np.float32)[1:-1]
    return w


def tiled_upscale(img: np.ndarray, fn: Callable[[np.ndarray], np.ndarray], scale: int,
                  tile: int = 384, overlap: int = 32,
                  progress: Optional[Callable[[float], None]] = None,
                  should_stop: Callable[[], bool] = lambda: False) -> np.ndarray:
    """Run ``fn`` over overlapping tiles; returns uint8 (H*s, W*s, 3)."""
    H, W = img.shape[:2]
    s = scale
    tile = max(32, min(tile, max(H, W)))
    overlap = min(overlap, tile // 4)
    ys, xs = _starts(H, tile, overlap), _starts(W, tile, overlap)
    out = np.empty((H * s, W * s, 3), np.uint8)
    total = len(ys) * len(xs)
    done = 0
    carry = None                                 # (out_y0, acc, wsum) awaiting next band
    for yi, y0 in enumerate(ys):
        y1 = min(y0 + tile, H)
        ov_top = (ys[yi - 1] + tile - y0) if yi > 0 else 0
        ov_bot = (y1 - ys[yi + 1]) if yi + 1 < len(ys) else 0
        bh = (y1 - y0) * s
        acc = np.zeros((bh, W * s, 3), np.float32)
        wsum = np.zeros((bh, W * s, 1), np.float32)
        wy = _ramp(bh, max(0, ov_top) * s, max(0, ov_bot) * s)
        for xi, x0 in enumerate(xs):
            if should_stop():
                raise Cancelled()
            x1 = min(x0 + tile, W)
            ov_l = (xs[xi - 1] + tile - x0) if xi > 0 else 0
            ov_r = (x1 - xs[xi + 1]) if xi + 1 < len(xs) else 0
            res = fn(img[y0:y1, x0:x1])
            wx = _ramp((x1 - x0) * s, max(0, ov_l) * s, max(0, ov_r) * s)
            w = (wy[:, None] * wx[None, :])[..., None]
            acc[:, x0 * s:x1 * s] += res * w
            wsum[:, x0 * s:x1 * s] += w
            done += 1
            if progress:
                progress(done / total)
        if carry is not None:
            cy0, cacc, cw = carry
            off = cy0 - y0 * s
            n = cacc.shape[0]
            acc[off:off + n] += cacc
            wsum[off:off + n] += cw
        fin = (ys[yi + 1] * s) if yi + 1 < len(ys) else y1 * s   # rows final after this band
        k = fin - y0 * s
        out[y0 * s:fin] = np.clip(acc[:k] / np.maximum(wsum[:k], 1e-6) * 255.0 + 0.5, 0, 255).astype(np.uint8)
        carry = (fin, acc[k:].copy(), wsum[k:].copy()) if k < bh else None
    return out


def blend_fn(a: Callable, b: Callable, amount: float) -> Callable:
    def f(tile):
        ra = a(tile)
        if amount <= 0:
            return ra
        rb = b(tile)
        return ra * (1 - amount) + rb * amount
    return f
