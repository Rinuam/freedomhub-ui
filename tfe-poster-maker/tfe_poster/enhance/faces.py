"""Face restoration: YuNet detection -> 5-point alignment -> GFPGAN/CodeFormer -> paste back."""
from __future__ import annotations

from typing import Callable, Optional

import cv2
import numpy as np

from .zoo import model_path

# FFHQ 512 alignment template (left eye, right eye, nose, left mouth, right mouth; image coords)
TEMPLATE = np.array([[192.98138, 239.94708], [318.90277, 240.1936], [256.63416, 314.01935],
                     [201.26117, 371.41043], [313.08905, 371.15118]], np.float32)


def detect_faces(img: np.ndarray, min_size: float = 24, score: float = 0.75) -> list[np.ndarray]:
    """Return a list of 5x2 landmark arrays (image coords) for each face."""
    p = model_path("yunet")
    if p is None:
        return []
    h, w = img.shape[:2]
    k = min(1.0, 1600 / max(h, w))
    small = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else img
    det = cv2.FaceDetectorYN.create(str(p), "", (small.shape[1], small.shape[0]), score, 0.3, 5000)
    _, faces = det.detect(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
    out = []
    if faces is None:
        return out
    for f in faces:
        if min(f[2], f[3]) / k < min_size:
            continue
        lm = f[4:14].reshape(5, 2) / k
        eyes = lm[:2][np.argsort(lm[:2, 0])]
        mouth = lm[3:5][np.argsort(lm[3:5, 0])]
        out.append(np.vstack([eyes, lm[2:3], mouth]).astype(np.float32))
    return out


class FaceRestorer:
    def __init__(self, model_id: str = "gfpgan-1.4", device: str = "auto", fidelity: float = 0.7):
        from .torch_sr import _load, device_name
        path = model_path(model_id)
        if path is None:
            raise FileNotFoundError(f"Face model '{model_id}' is not installed")
        self.device = device_name(device)
        self.desc, self.dtype = _load(str(path), self.device, "fp32")
        self.is_codeformer = self.desc.architecture.name == "CodeFormer"
        self.fidelity = fidelity

    def _restore(self, face: np.ndarray) -> np.ndarray:
        import torch
        t = torch.from_numpy(face).permute(2, 0, 1)[None].to(self.device, self.dtype) / 255.0
        with torch.inference_mode():
            if self.is_codeformer:
                out = self.desc.model(t, weight=self.fidelity)[0].clamp(0, 1)
            else:
                out = self.desc(t)
        return (out[0].float().permute(1, 2, 0).cpu().numpy() * 255 + 0.5).clip(0, 255).astype(np.uint8)

    def apply(self, img: np.ndarray, strength: float = 1.0,
              progress: Optional[Callable[[float], None]] = None) -> tuple[np.ndarray, int]:
        faces = detect_faces(img)
        out = img.copy()
        h, w = img.shape[:2]
        for i, lm in enumerate(faces):
            M, _ = cv2.estimateAffinePartial2D(lm, TEMPLATE, method=cv2.LMEDS)
            if M is None:
                continue
            crop = cv2.warpAffine(img, M, (512, 512), flags=cv2.INTER_LANCZOS4 if M[0, 0] > 1 else cv2.INTER_AREA,
                                  borderMode=cv2.BORDER_REFLECT101)
            restored = self._restore(crop)
            Minv = cv2.invertAffineTransform(M)
            # paste only inside the face's bounding region for speed
            corners = cv2.transform(np.array([[[0, 0], [512, 0], [0, 512], [512, 512]]], np.float32), Minv)[0]
            x0, y0 = np.floor(corners.min(0)).astype(int)
            x1, y1 = np.ceil(corners.max(0)).astype(int)
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            T = Minv.copy()
            T[:, 2] -= (x0, y0)
            back = cv2.warpAffine(restored, T, (x1 - x0, y1 - y0), flags=cv2.INTER_LANCZOS4)
            mask = np.zeros((512, 512), np.float32)
            cv2.ellipse(mask, (256, 280), (205, 245), 0, 0, 360, 1.0, -1)
            mask = cv2.GaussianBlur(mask, (0, 0), 24)
            m = cv2.warpAffine(mask, T, (x1 - x0, y1 - y0))[..., None] * strength
            region = out[y0:y1, x0:x1].astype(np.float32)
            out[y0:y1, x0:x1] = np.clip(region * (1 - m) + back.astype(np.float32) * m + 0.5, 0, 255).astype(np.uint8)
            if progress:
                progress((i + 1) / len(faces))
        return out, len(faces)
