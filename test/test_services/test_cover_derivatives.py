from pathlib import Path

import cv2
import numpy as np
import pytest

from models.novel import Novel
from scripts.backfill_cover_derivatives import backfill_cover_derivatives
from services.cover_derivatives import (
    cover_derivative_reference,
    render_cover_derivatives,
    write_local_cover_derivatives,
)


def _test_image(width: int = 1664, height: int = 2496) -> bytes:
    image = np.full((height, width, 3), (42, 96, 182), dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success
    return encoded.tobytes()


def test_derivative_references_are_deterministic_for_local_and_oss():
    assert cover_derivative_reference(
        "/media/covers/novel-9-abc.png", "thumbnail"
    ) == "/media/covers/derivatives/novel-9-abc-thumbnail.webp"
    assert cover_derivative_reference(
        "uploads/2/20260901/abc-cover.png", "preview"
    ) == "uploads/2/20260901/derivatives/abc-cover-preview.webp"
    assert cover_derivative_reference(
        "media/assets/legacy.png", "thumbnail"
    ) == "/media/assets/derivatives/legacy-thumbnail.webp"
    assert cover_derivative_reference("https://external.example/cover.png", "thumbnail") is None


def test_rendered_cover_derivatives_have_expected_dimensions_and_small_payload():
    original = _test_image()
    derivatives = render_cover_derivatives(original)

    thumbnail = cv2.imdecode(
        np.frombuffer(derivatives["thumbnail"], dtype=np.uint8),
        cv2.IMREAD_UNCHANGED,
    )
    preview = cv2.imdecode(
        np.frombuffer(derivatives["preview"], dtype=np.uint8),
        cv2.IMREAD_UNCHANGED,
    )
    assert thumbnail.shape[:2] == (480, 320)
    assert preview.shape[:2] == (960, 640)
    assert len(derivatives["thumbnail"]) < len(original) * 0.1
    assert len(derivatives["preview"]) < len(original) * 0.2


def test_local_derivatives_are_written_beside_original(tmp_path: Path):
    cover = "/media/covers/novel-1-test.png"
    original = _test_image(400, 600)
    original_path = tmp_path / "covers/novel-1-test.png"
    original_path.parent.mkdir(parents=True)
    original_path.write_bytes(original)

    written = write_local_cover_derivatives(tmp_path, cover, original)

    assert written["thumbnail"] == (
        tmp_path / "covers/derivatives/novel-1-test-thumbnail.webp"
    )
    assert written["preview"].is_file()


@pytest.mark.asyncio
async def test_backfill_generates_missing_local_derivatives_once(
    tmp_path: Path,
    monkeypatch,
):
    from config import settings

    monkeypatch.setattr(settings, "MEDIA_PATH", str(tmp_path))
    cover = "/media/covers/legacy.png"
    original_path = tmp_path / "covers/legacy.png"
    original_path.parent.mkdir(parents=True)
    original_path.write_bytes(_test_image(400, 600))
    novel = await Novel.create(name="旧项目封面回填", cover=cover)

    first = await backfill_cover_derivatives([novel.id])
    second = await backfill_cover_derivatives([novel.id])

    assert first == {"scanned": 1, "generated": 1, "skipped": 0, "failed": 0}
    assert second == {"scanned": 1, "generated": 0, "skipped": 1, "failed": 0}
