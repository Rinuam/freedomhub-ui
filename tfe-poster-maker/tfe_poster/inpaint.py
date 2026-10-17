"""Text removal at source resolution: LaMa (big-lama) when installed, else OpenCV.

Removing text on the *source* image and then enhancing the cleaned region with
the same SR model keeps the texture consistent with the rest of the picture.
"""
from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np

from .enhance.zoo import model_path

MAX_LAMA_SIDE = 1024


def lama_available() -> bool:
    if model_path("lama") is None:
        return False
    try:
        import torch  # noqa: F401
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _lama(device: str):
    import torch
    m = torch.jit.load(str(model_path("lama")), map_location="cpu")
    m.eval()
    try:
        m = m.to(device)
    except Exception:
        device = "cpu"
    return m, device


def _run_lama(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    import torch
    from .enhance.torch_sr import device_name, _lock
    h, w = img.shape[:2]
    ph, pw = (-h) % 8, (-w) % 8
    im = np.pad(img, ((0, ph), (0, pw), (0, 0)), mode="reflect") if (ph or pw) else img
    mk = np.pad(mask, ((0, ph), (0, pw)), mode="constant") if (ph or pw) else mask
    for dev in dict.fromkeys([device_name(), "cpu"]):
        try:
            model, dev = _lama(dev)
            t = torch.from_numpy(im).permute(2, 0, 1)[None].float().to(dev) / 255.0
            m = torch.from_numpy((mk > 127).astype(np.float32))[None, None].to(dev)
            t = t * (1 - m)                     # the network must not see the text it removes
            with _lock, torch.inference_mode():
                out = model(t, m)
            res = out[0].permute(1, 2, 0).float().cpu().numpy()
            if res.max() <= 1.5:
                res = res * 255.0
            return np.clip(res, 0, 255).astype(np.uint8)[:h, :w]
        except Exception:
            continue
    raise RuntimeError("LaMa inpainting failed")


def _clusters(mask: np.ndarray, gap: int) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of mask regions, merging ones closer than ``gap``."""
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * gap + 1, 2 * gap + 1))
    merged = cv2.dilate((mask > 0).astype(np.uint8), k)
    n, _, stats, _ = cv2.connectedComponentsWithStats(merged)
    boxes = []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        boxes.append((x, y, x + w, y + h))
    return boxes


def inpaint(img: np.ndarray, mask: np.ndarray, method: str = "auto") -> np.ndarray:
    """Return a copy of ``img`` with ``mask`` (uint8, >0 = remove) filled."""
    if not mask.any():
        return img
    use_lama = method in ("auto", "lama") and lama_available()
    out = img.copy()
    H, W = img.shape[:2]
    for x0, y0, x1, y1 in _clusters(mask, 8):
        bw, bh = x1 - x0, y1 - y0
        ctx = int(max(24, 0.6 * max(bw, bh) if use_lama else 0.25 * max(bw, bh)))
        cx0, cy0, cx1, cy1 = max(0, x0 - ctx), max(0, y0 - ctx), min(W, x1 + ctx), min(H, y1 + ctx)
        crop, cm = out[cy0:cy1, cx0:cx1], mask[cy0:cy1, cx0:cx1]
        if use_lama:
            k = min(1.0, MAX_LAMA_SIDE / max(crop.shape[:2]))
            if k < 1:
                sw, sh = int(crop.shape[1] * k), int(crop.shape[0] * k)
                small = cv2.resize(crop, (sw, sh), interpolation=cv2.INTER_AREA)
                smask = (cv2.resize(cm, (sw, sh), interpolation=cv2.INTER_AREA) > 0).astype(np.uint8) * 255
                filled = cv2.resize(_run_lama(small, smask), (crop.shape[1], crop.shape[0]),
                                    interpolation=cv2.INTER_CUBIC)
            else:
                filled = _run_lama(crop, cm)
        else:
            flag = cv2.INPAINT_NS if method == "ns" else cv2.INPAINT_TELEA
            filled = cv2.inpaint(crop, (cm > 0).astype(np.uint8) * 255, 5, flag)
        a = cv2.GaussianBlur((cm > 0).astype(np.float32), (0, 0), 1.0)
        a = np.maximum(a, (cm > 0).astype(np.float32))[..., None]
        out[cy0:cy1, cx0:cx1] = np.clip(crop * (1 - a) + filled * a + 0.5, 0, 255).astype(np.uint8)
    return out


def method_name(method: str = "auto") -> str:
    if method in ("auto", "lama") and lama_available():
        return "LaMa"
    return "OpenCV Navier-Stokes" if method == "ns" else "OpenCV Telea"
