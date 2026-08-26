"""video OUT schema：metadata 内嵌媒体引用读取时解析为公共 URL。"""

from datetime import datetime, timezone

from schemas.video import VideoOut, VideoQueryOut


def _video_out(metadata: dict):
    return VideoOut.model_validate({
        "id": 1,
        "scene_id": 1,
        "status": 3,
        "url": "uploads/0/20260820/x-video.mp4",
        "metadata": metadata,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })


def test_video_out_resolves_metadata_media(monkeypatch):
    """VideoOut 对 url 与 metadata 中的首尾帧/参考素材统一解析并写回。"""
    calls: list[str] = []
    monkeypatch.setattr(
        "schemas.video.resolve_media_url",
        lambda raw: calls.append(raw) or f"public://{raw}",
    )
    out = _video_out({
        "first_frame_url": "uploads/0/20260820/f.png",
        "last_frame_url": "uploads/0/20260820/e71e84865b40-last-frame-2.png",
        "last_frame_reference": {
            "type": "image",
            "url": "uploads/0/20260820/e71e84865b40-last-frame-2.png",
            "mention_url": "uploads/0/20260820/e71e84865b40-last-frame-2.png",
            "name": "分镜1生成尾帧.png",
        },
        "reference_media": [
            {"type": "image", "url": "uploads/0/20260820/r.png", "name": "r"},
        ],
        "generation_mode": "keyframes",
    })
    assert out.url == "public://uploads/0/20260820/x-video.mp4"
    assert out.metadata["first_frame_url"] == "public://uploads/0/20260820/f.png"
    assert out.metadata["last_frame_url"] == (
        "public://uploads/0/20260820/e71e84865b40-last-frame-2.png"
    )
    assert out.metadata["last_frame_reference"]["url"] == (
        "public://uploads/0/20260820/e71e84865b40-last-frame-2.png"
    )
    assert out.metadata["last_frame_reference"]["mention_url"] == (
        "uploads/0/20260820/e71e84865b40-last-frame-2.png"
    )
    assert out.metadata["reference_media"][0]["url"] == "public://uploads/0/20260820/r.png"
    assert out.metadata["generation_mode"] == "keyframes"
    assert calls == [
        "uploads/0/20260820/x-video.mp4",
        "uploads/0/20260820/f.png",
        "uploads/0/20260820/e71e84865b40-last-frame-2.png",
        "uploads/0/20260820/e71e84865b40-last-frame-2.png",
        "uploads/0/20260820/r.png",
    ]


def test_video_out_keeps_non_media_metadata(monkeypatch):
    """非字符串/缺失字段不触发解析，其它 metadata 原样保留。"""
    out = _video_out({"return_last_frame": True})
    assert out.metadata["return_last_frame"] is True
    assert "last_frame_url" not in out.metadata


def test_video_query_out_resolves_injected_oss_last_frame(monkeypatch):
    """生成完成轮询响应也必须把注入尾帧的 OSS key 转成浏览器可访问 URL。"""
    calls: list[str] = []
    monkeypatch.setattr(
        "schemas.video.resolve_media_url",
        lambda raw: calls.append(raw) or f"public://{raw}",
    )

    out = VideoQueryOut.model_validate({
        "id": 3,
        "scene_id": 1,
        "status": 3,
        "url": "uploads/0/20260823/video-3.mp4",
        "metadata": {
            "last_frame_url": "uploads/0/20260823/last-frame-3.png",
            "last_frame_reference": {
                "type": "image",
                "url": "uploads/0/20260823/last-frame-3.png",
                "name": "分镜1生成尾帧.png",
            },
        },
    })

    assert out.url == "public://uploads/0/20260823/video-3.mp4"
    assert out.metadata["last_frame_url"] == "public://uploads/0/20260823/last-frame-3.png"
    assert out.metadata["last_frame_reference"]["url"] == (
        "public://uploads/0/20260823/last-frame-3.png"
    )
    assert calls == [
        "uploads/0/20260823/video-3.mp4",
        "uploads/0/20260823/last-frame-3.png",
        "uploads/0/20260823/last-frame-3.png",
    ]
