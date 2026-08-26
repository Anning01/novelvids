import pytest
from fastapi import HTTPException

from services.video.capabilities import capabilities_for
from schemas.video import VideoReferenceMedia
from services.video.reference_media import (
    _validate_probe,
    reference_mention_syntax,
    render_reference_mentions,
    select_referenced_media,
)


def test_只选择提示词显式引用的上传素材():
    image = VideoReferenceMedia(type="image", url="/media/video-references/look 1.png", name="造型图")
    video = VideoReferenceMedia(type="video", url="/media/video-references/motion.mp4", name="动作.mp4")
    prompt = f"使用 {reference_mention_syntax('video', video.url)} 的动作"

    assert select_referenced_media(prompt, [image, video]) == [video]
    assert render_reference_mentions(prompt, [video]) == "使用 【参考视频：动作.mp4】 的动作"


def test_已删除素材遗留的内部标记不会进入供应商提示词():
    stale = reference_mention_syntax("image", "/media/video-references/deleted.png")

    assert render_reference_mentions(f"画面参考 {stale}", []) == "画面参考 "


def test_签名展示地址通过稳定地址匹配_prompt_引用():
    image = VideoReferenceMedia(
        type="image",
        url="https://oss.example.com/last.png?signature=renewed",
        mention_url="uploads/1/last.png",
        name="上一镜头尾帧.png",
    )
    mention = reference_mention_syntax("image", image.mention_url)
    prompt = f"{mention} 作为本镜头首帧"

    assert select_referenced_media(prompt, [image]) == [image]
    assert render_reference_mentions(prompt, [image]) == (
        "【参考图片：上一镜头尾帧.png】 作为本镜头首帧"
    )


def _video_probe(*, duration: float = 10, fps: str = "30/1", codec: str = "h264", audio: str = "aac"):
    return {
        "format": {"duration": str(duration), "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": codec,
                "width": 1280,
                "height": 720,
                "avg_frame_rate": fps,
            },
            {"codec_type": "audio", "codec_name": audio},
        ],
    }


def test_reference_video_probe_enforces_seedance_media_contract():
    metadata = _validate_probe("video", _video_probe(), 20 * 1024 * 1024, capabilities_for("seedance_2"))

    assert metadata == {
        "width": 1280,
        "height": 720,
        "duration": 10.0,
        "fps": 30.0,
        "codec": "h264",
    }


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        (_video_probe(duration=16), "2-15 秒"),
        (_video_probe(fps="23/1"), "24-60 FPS"),
        (_video_probe(codec="vp9"), "H.264/AVC"),
        (_video_probe(audio="opus"), "AAC 或 MP3"),
    ],
)
def test_reference_video_probe_rejects_invalid_media(probe, message):
    with pytest.raises(HTTPException, match=message):
        _validate_probe("video", probe, 1024, capabilities_for("seedance_2"))


def test_seedance_2_5_accepts_longer_reference_video_than_2_0():
    metadata = _validate_probe("video", _video_probe(duration=25), 1024, capabilities_for("seedance_2_5"))
    assert metadata["duration"] == 25


def test_wan3_uses_different_side_limits_for_images_and_videos():
    image_probe = _video_probe(duration=1)
    image_probe["streams"][0].update(width=5000, height=1000)
    assert _validate_probe("image", image_probe, 1024, capabilities_for("wan_3"))["width"] == 5000

    video_probe = _video_probe(duration=1)
    video_probe["streams"][0].update(width=5000, height=1000)
    with pytest.raises(HTTPException, match="240-4096px"):
        _validate_probe("video", video_probe, 1024, capabilities_for("wan_3"))
