"""设定资产输出必须分别解析原图与派生图，避免复用原图签名。"""

from datetime import datetime, timezone
from uuid import uuid4

from schemas.asset import AssetBriefOut, AssetGenerationRecordOut
from schemas.asset_variant import AssetVariantOut


def _patch_media_resolution(monkeypatch, module: str) -> None:
    monkeypatch.setattr(
        f"{module}.normalize_media_url",
        lambda raw: (
            raw.split("signed/", 1)[1].split("?", 1)[0]
            if raw and "signed/" in raw
            else raw
        ),
    )
    monkeypatch.setattr(
        f"{module}.resolve_media_url",
        lambda raw: f"public://{raw}" if raw else None,
    )


def test_asset_output_resolves_distinct_original_thumbnail_and_preview(monkeypatch):
    _patch_media_resolution(monkeypatch, "schemas.asset")
    now = datetime.now(timezone.utc)

    asset = AssetBriefOut.model_validate({
        "id": 1,
        "novel_id": 2,
        "asset_type": 1,
        "canonical_name": "书生",
        "main_image": "https://cdn.example/signed/uploads/2/actor.png?token=old",
        "metadata": {"image_gallery": ["uploads/2/gallery.png"]},
        "created_at": now,
        "updated_at": now,
    })

    assert asset.main_image == "public://uploads/2/actor.png"
    assert asset.main_image_thumbnail == (
        "public://uploads/2/derivatives/actor-thumbnail.webp"
    )
    assert asset.main_image_preview == (
        "public://uploads/2/derivatives/actor-preview.webp"
    )
    assert asset.metadata["image_gallery"] == ["public://uploads/2/gallery.png"]
    assert asset.metadata["image_gallery_thumbnails"] == [
        "public://uploads/2/derivatives/gallery-thumbnail.webp"
    ]


def test_asset_history_and_variant_expose_aligned_derivative_arrays(monkeypatch):
    _patch_media_resolution(monkeypatch, "schemas.asset")
    _patch_media_resolution(monkeypatch, "schemas.asset_variant")
    now = datetime.now(timezone.utc)
    image = "uploads/2/history.png"

    record = AssetGenerationRecordOut.model_validate({
        "id": uuid4(),
        "status": 3,
        "images": [image],
        "created_at": now,
    })
    variant = AssetVariantOut.model_validate({
        "id": 3,
        "asset_id": 1,
        "name": "便装",
        "images": [image],
        "created_at": now,
        "updated_at": now,
    })

    assert record.images == [f"public://{image}"]
    assert record.image_thumbnails == [
        "public://uploads/2/derivatives/history-thumbnail.webp"
    ]
    assert record.image_previews == [
        "public://uploads/2/derivatives/history-preview.webp"
    ]
    assert variant.image_thumbnails == record.image_thumbnails
    assert variant.image_previews == record.image_previews
