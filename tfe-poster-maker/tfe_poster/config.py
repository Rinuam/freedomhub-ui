"""Settings and constants."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0

# ISO 216 A1
A1_SHORT_MM = 594.0
A1_LONG_MM = 841.0

UPSCALE_MODELS = {
    # name passed to -n : human label
    "realesr-animevideov3": "Anime/illustration, conservative (default)",
    "realesrgan-x4plus-anime": "Anime/illustration, stronger (6B)",
    "realesrgan-x4plus": "General photo",
}
DEFAULT_MODEL = "realesr-animevideov3"


@dataclass
class Settings:
    orientation: str = "auto"          # auto | portrait | landscape
    margin_mm: float = 15.0
    dpi: int = 300
    upscale: bool = True
    upscale_model: str = DEFAULT_MODEL
    upscale_tile: int = 0              # 0 = auto (ncnn decides)
    realesrgan_path: str = ""          # empty = auto-discover
    ocr_min_confidence: float = 0.3
    ocr_languages: list[str] = field(default_factory=lambda: ["en-US", "es-ES", "ca-ES"])
    default_font: str = ""             # font id (path#index); empty = auto
    inpaint_method: str = "telea"      # telea | ns
    pdf_background: str = "jpeg"       # jpeg | lossless
    jpeg_quality: int = 95
    batch_vectorise: str = "auto"      # all | none | auto (confidence >= 0.6)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)
