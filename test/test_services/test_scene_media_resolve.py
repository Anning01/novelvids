"""scene 媒体引用：读取时重新签发 + 落库时降级为 key。"""

from datetime import datetime, timezone

from schemas.scene import SceneOut


def _scene_out(metadata: dict):
    return SceneOut.model_validate({
        "id": 1,
        "chapter_id": 2,
        "sequence": 1,
        "description": "shot",
        "prompt": "p",
        "duration": 6,
        "metadata": metadata,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })


def test_scene_out_resolves_first_last_frame(monkeypatch):
    """SceneOut 对 metadata 中的首尾帧与参考素材 URL 调用重新签发并写回。"""
    calls: list[str] = []
    monkeypatch.setattr(
        "schemas.scene.resolve_media_url",
        lambda raw: calls.append(raw) or f"signed://{raw}",
    )
    out = _scene_out({
        "first_frame_url": "uploads/0/1/first.png",
        "last_frame_url": "uploads/0/1/last.png",
        "video_reference_media": [
            {"type": "image", "url": "uploads/0/1/ref.png", "name": "参考图"},
        ],
    })
    assert out.metadata["first_frame_url"] == "signed://uploads/0/1/first.png"
    assert out.metadata["last_frame_url"] == "signed://uploads/0/1/last.png"
    assert out.metadata["video_reference_media"][0]["url"] == "signed://uploads/0/1/ref.png"
    assert calls == [
        "uploads/0/1/first.png",
        "uploads/0/1/last.png",
        "uploads/0/1/ref.png",
    ]


def test_scene_out_keeps_non_string_metadata(monkeypatch):
    """非字符串/缺失的媒体字段不触发解析，metadata 其它字段原样保留。"""
    out = _scene_out({"video_generation_mode": "keyframes"})
    assert out.metadata["video_generation_mode"] == "keyframes"
    assert "first_frame_url" not in out.metadata


def test_scene_metadata_normalize_downgrades_signed_urls(monkeypatch):
    """落库归一化：把指向本桶的签名 URL 降级为 key。"""
    from controllers.scene import _normalize_scene_metadata

    calls: list[str] = []
    monkeypatch.setattr(
        "controllers.scene.normalize_media_url",
        lambda raw: calls.append(raw) or ("uploads/0/1/x.png" if "aliyuncs.com" in raw else raw),
    )
    metadata = {
        "first_frame_url": "https://dramas-x.oss-cn-guangzhou.aliyuncs.com/uploads/0/1/first.png?Expires=1&Signature=old",
        "last_frame_url": "/media/local.png",
        "video_reference_media": [
            {"type": "image", "url": "https://dramas-x.oss-cn-guangzhou.aliyuncs.com/uploads/0/1/ref.png?Signature=old", "name": "r"},
            {"type": "video", "url": "https://external.example.com/v.mp4", "name": "v"},
        ],
        "video_generation_mode": "keyframes",
    }
    normalized = _normalize_scene_metadata(metadata)
    assert normalized["first_frame_url"] == "uploads/0/1/x.png"
    assert normalized["last_frame_url"] == "/media/local.png"
    assert normalized["video_reference_media"][0]["url"] == "uploads/0/1/x.png"
    assert normalized["video_reference_media"][1]["url"] == "https://external.example.com/v.mp4"
    assert normalized["video_generation_mode"] == "keyframes"
