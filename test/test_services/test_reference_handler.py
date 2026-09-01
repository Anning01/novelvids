import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np
import pytest

from models.asset import Asset
from models.novel import Novel
from services.reference.handler import AssetReferenceHandler
from utils.enums import AssetTypeEnum


async def _asset() -> Asset:
    novel = await Novel.create(name="参考图任务")
    return await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="宫平",
        base_traits="稳定人物视觉描述",
    )


def _request(asset: Asset) -> dict:
    return {
        "asset_id": asset.id,
        "base_url": "https://images.example.test/v1",
        "api_key": "test-key",
        "model": "test-image-model",
    }


@pytest.mark.asyncio
async def test_参考图服务没有返回图片时任务必须失败():
    asset = await _asset()

    with patch(
        "services.reference.handler.generate_for_sora_consistency",
        new=AsyncMock(return_value=[]),
    ):
        with pytest.raises(RuntimeError, match="没有可持久化的图片"):
            await AssetReferenceHandler().execute(_request(asset))


@pytest.mark.asyncio
async def test_参考图全部下载失败时任务必须失败():
    asset = await _asset()
    generated = [SimpleNamespace(url="https://cdn.example.test/result.png")]

    with (
        patch(
            "services.reference.handler.generate_for_sora_consistency",
            new=AsyncMock(return_value=generated),
        ),
        patch(
            "services.reference.handler._download_image",
            new=AsyncMock(side_effect=RuntimeError("download failed")),
        ),
    ):
        with pytest.raises(RuntimeError, match="没有可持久化的图片"):
            await AssetReferenceHandler().execute(_request(asset))


@pytest.mark.asyncio
async def test_参考图至少一张落盘后才返回成功并更新资产():
    asset = await _asset()
    generated = [
        SimpleNamespace(url="https://cdn.example.test/first.png"),
        SimpleNamespace(url="https://cdn.example.test/second.png"),
    ]

    with (
        patch(
            "services.reference.handler.generate_for_sora_consistency",
            new=AsyncMock(return_value=generated),
        ),
        patch(
            "services.reference.handler._download_image",
            new=AsyncMock(
                side_effect=[
                    "/media/assets/first.png",
                    RuntimeError("second download failed"),
                ]
            ),
        ),
    ):
        result = await AssetReferenceHandler().execute(_request(asset))

    await asset.refresh_from_db()
    assert result == {"images": ["/media/assets/first.png"], "variant_id": None}
    assert asset.main_image == "/media/assets/first.png"


@pytest.mark.asyncio
async def test_参考图base64返回会落盘并更新资产(tmp_path, monkeypatch):
    asset = await _asset()
    png_bytes = b"\x89PNG\r\n\x1a\nreference-image"
    encoded = base64.b64encode(png_bytes).decode("ascii")
    generated = [SimpleNamespace(url=None, b64_json=encoded)]
    monkeypatch.setattr("services.reference.handler.settings.MEDIA_PATH", str(tmp_path))

    with patch(
        "services.reference.handler.generate_for_sora_consistency",
        new=AsyncMock(return_value=generated),
    ):
        result = await AssetReferenceHandler().execute(_request(asset))

    await asset.refresh_from_db()
    saved_path = tmp_path / "assets" / f"{asset.id}.png"
    assert saved_path.read_bytes() == png_bytes
    assert result["images"] == [f"/media/assets/{asset.id}.png"]
    assert asset.main_image == f"/media/assets/{asset.id}.png"


@pytest.mark.asyncio
async def test_有效参考图同时生成列表与预览派生图(tmp_path, monkeypatch):
    asset = await _asset()
    success, encoded = cv2.imencode(
        ".png",
        np.full((1200, 800, 3), (36, 92, 170), dtype=np.uint8),
    )
    assert success
    generated = [SimpleNamespace(
        url=None,
        b64_json=base64.b64encode(encoded.tobytes()).decode("ascii"),
    )]
    monkeypatch.setattr("services.reference.handler.settings.MEDIA_PATH", str(tmp_path))

    with patch(
        "services.reference.handler.generate_for_sora_consistency",
        new=AsyncMock(return_value=generated),
    ):
        await AssetReferenceHandler().execute(_request(asset))

    derivative_dir = tmp_path / "assets" / "derivatives"
    assert (derivative_dir / f"{asset.id}-thumbnail.webp").is_file()
    assert (derivative_dir / f"{asset.id}-preview.webp").is_file()


@pytest.mark.asyncio
async def test_图生图输入会解析本地图片并记录计费数量(tmp_path, monkeypatch):
    asset = await _asset()
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"\x89PNG\r\n\x1a\ninput-image")
    generated = [SimpleNamespace(url=None, b64_json=base64.b64encode(
        b"\x89PNG\r\n\x1a\noutput-image"
    ).decode("ascii"))]
    monkeypatch.setattr("services.image_inputs.settings.MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr("services.reference.handler.settings.MEDIA_PATH", str(tmp_path))
    generator = AsyncMock(return_value=generated)

    with patch(
        "services.reference.handler.generate_for_sora_consistency",
        new=generator,
    ):
        result = await AssetReferenceHandler().execute({
            **_request(asset),
            "reference_images": ["/media/reference.png"],
        })

    reference_images = generator.await_args.kwargs["reference_images"]
    assert len(reference_images) == 1
    assert reference_images[0].startswith("data:image/png;base64,")
    assert result["input_image_count"] == 1


@pytest.mark.asyncio
async def test_重新生成使用独立文件名保留历史图片(tmp_path, monkeypatch):
    asset = await _asset()
    png_bytes = b"\x89PNG\r\n\x1a\nregenerated-image"
    encoded = base64.b64encode(png_bytes).decode("ascii")
    generated = [SimpleNamespace(url=None, b64_json=encoded)]
    request = {**_request(asset), "generation_run_id": "run-2026/08"}
    monkeypatch.setattr("services.reference.handler.settings.MEDIA_PATH", str(tmp_path))

    with patch(
        "services.reference.handler.generate_for_sora_consistency",
        new=AsyncMock(return_value=generated),
    ):
        result = await AssetReferenceHandler().execute(request)

    expected = f"/media/assets/{asset.id}_generation_run-202608.png"
    assert result["images"] == [expected]
    assert (tmp_path / "assets" / f"{asset.id}_generation_run-202608.png").exists()
