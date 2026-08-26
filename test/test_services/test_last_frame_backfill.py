import pytest

from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from services.video.last_frame_backfill import backfill_last_frame_continuity
from services.video.reference_media import reference_mention_syntax


@pytest.mark.asyncio
async def test_旧尾帧引用启动时补齐_prompt_且重复执行幂等():
    novel = await Novel.create(name="尾帧兼容测试", author="test")
    chapter = await Chapter.create(novel=novel, number=1, name="第一章", content="内容")
    scene = await Scene.create(
        chapter=chapter,
        sequence=2,
        prompt="【镜头描述】\n人物继续前行",
        metadata={
            "video_reference_media": [{
                "type": "image",
                "url": "uploads/1/last-frame-1.png",
                "name": "分镜1生成尾帧.png",
                "source": "previous_scene_last_frame",
                "source_scene_id": 1,
            }],
        },
    )

    assert await backfill_last_frame_continuity() == {"scanned": 1, "updated": 1}
    await scene.refresh_from_db()
    reference = scene.metadata["video_reference_media"][0]
    mention = reference_mention_syntax("image", reference["url"])
    assert reference["mention_url"] == reference["url"]
    assert f"{mention} 作为本镜头首帧" in scene.prompt
    assert scene.prompt.endswith("人物继续前行")

    assert await backfill_last_frame_continuity() == {"scanned": 1, "updated": 0}
