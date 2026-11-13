"""Worker-safe image codecs; no application or credential dependencies."""
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from utils.messages import localized_message

CoverDerivativeKind = Literal["thumbnail", "preview"]

@dataclass(frozen=True)
class CoverDerivativeSpec:
    max_width: int
    max_height: int
    quality: int


COVER_DERIVATIVE_SPECS: dict[CoverDerivativeKind, CoverDerivativeSpec] = {
    "thumbnail": CoverDerivativeSpec(max_width=320, max_height=480, quality=78),
    "preview": CoverDerivativeSpec(max_width=640, max_height=960, quality=82),
}


def render_derivatives(image_bytes: bytes) -> dict[CoverDerivativeKind, bytes]:
    """解码一次原图并输出两个 WebP 派生尺寸。"""
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if image is None or image.size == 0:
        raise ValueError(localized_message('封面图片无法解码'))

    return {
        kind: _render_variant(image, spec)
        for kind, spec in COVER_DERIVATIVE_SPECS.items()
    }


def _render_variant(image: np.ndarray, spec: CoverDerivativeSpec) -> bytes:
    height, width = image.shape[:2]
    scale = min(1.0, spec.max_width / width, spec.max_height / height)
    if scale < 1.0:
        target = (
            max(1, round(width * scale)),
            max(1, round(height * scale)),
        )
        image = cv2.resize(image, target, interpolation=cv2.INTER_AREA)

    success, output = cv2.imencode(
        ".webp",
        image,
        [cv2.IMWRITE_WEBP_QUALITY, spec.quality],
    )
    if not success:
        raise ValueError(localized_message('封面 WebP 编码失败'))
    return output.tobytes()
