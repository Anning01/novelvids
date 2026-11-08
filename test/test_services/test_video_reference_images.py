import base64
import cv2
import numpy as np

from services.image_inputs import resolve_image_source
from services.video.asset_resolver import resolve_image_source as resolve_video_image


def test_video_reference_preserves_original_bytes_format_and_dimensions(tmp_path):
    path = tmp_path / 'reference.png'
    cv2.imwrite(str(path), np.full((2304, 4096, 3), 128, dtype=np.uint8))
    original = path.read_bytes()
    data = resolve_video_image(str(path))
    assert data.startswith('data:image/png;base64,')
    transmitted = base64.b64decode(data.split(',', 1)[1])
    assert transmitted == original
    image = cv2.imdecode(np.frombuffer(transmitted, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert image.shape[:2] == (2304, 4096)
    assert path.read_bytes() == original
    assert resolve_image_source(str(path)).startswith('data:image/png;base64,')


def test_video_reference_keeps_transparency(tmp_path):
    path = tmp_path / 'cutout.png'
    image = np.full((2000, 3000, 4), [30, 60, 90, 128], dtype=np.uint8)
    cv2.imwrite(str(path), image)
    data = resolve_video_image(str(path))
    assert data.startswith('data:image/png;base64,')
    transmitted = base64.b64decode(data.split(',', 1)[1])
    assert transmitted == path.read_bytes()
    image = cv2.imdecode(np.frombuffer(transmitted, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert image.shape[:2] == (2000, 3000)
    assert image[:, :, 3].min() == image[:, :, 3].max() == 128


def test_public_video_reference_image_url_is_forwarded_verbatim():
    url = 'https://example.invalid/reference.png?signature=preserved'
    assert resolve_video_image(url) == url
