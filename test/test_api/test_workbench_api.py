import pytest
from httpx import AsyncClient
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from utils.enums import AssetTypeEnum, TaskStatusEnum


@pytest.mark.asyncio
async def test_workbench_capabilities(client: AsyncClient):
    response = await client.get("/api/workbench/capabilities")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "upload_media": True,
        "generate_asset": True,
        "generate_video": True,
        "apply_watermark": False,
        "compose_video": False,
        "prompt_editors": [
            {
                "editor_key": "asset_prompt",
                "node_kind": "asset",
                "field_key": "prompt",
                "label": "图片 Prompt",
                "placeholder": "描述希望生成的主体、场景、光线与画面风格",
                "hint": "输入 @ 引用已连接的参考图片",
                "allowed_asset_types": None,
                "excluded_asset_types": [
                    "watermark",
                    "image",
                    "video",
                    "background_audio",
                    "sound_effect",
                ],
                "reference_limits": {"image": 10, "video": 0, "audio": 0},
                "allow_prompt_injection": False,
            },
            {
                "editor_key": "shot_prompt",
                "node_kind": "shot",
                "field_key": "prompt",
                "label": "镜头画面 Prompt",
                "placeholder": "描述镜头主体、动作、环境、运镜与节奏",
                "hint": "输入 @ 引用已连接的图片、视频、音频或文字素材",
                "allowed_asset_types": None,
                "excluded_asset_types": None,
                "reference_limits": {"image": 9, "video": 3, "audio": 3},
                "allow_prompt_injection": True,
            },
        ],
        "refresh_policy": {
            "poll_interval_ms": 1500,
            "poll_max_interval_ms": 12000,
        },
    }


@pytest.mark.asyncio
async def test_workbench_bootstrap_returns_only_current_chapter_working_set(client: AsyncClient):
    novel = await Novel.create(name="Large Novel")
    first = await Chapter.create(novel_id=novel.id, number=1, name="第一章", content="正文")
    second = await Chapter.create(novel_id=novel.id, number=2, name="第二章", content="正文")
    current = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="当前章人物",
        source_chapters=[2],
    )
    unrelated = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.scene.value,
        canonical_name="第一章场景",
        source_chapters=[1],
    )
    reused = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.item.value,
        canonical_name="复用道具",
        source_chapters=[1],
    )
    await AssetVariant.create(
        asset_id=current.id,
        name="升级形态",
        images=["/media/variant-a.png", "/media/variant-b.png"],
        chapter_numbers=[2],
    )
    scene = await Scene.create(chapter_id=second.id, sequence=1, prompt="镜头", duration=4)
    await scene.assets.add(reused)
    video = await Video.create(
        scene_id=scene.id,
        model_type=1,
        status=TaskStatusEnum.pending.value,
    )

    response = await client.get(
        f"/api/workbench/bootstrap?novel_id={novel.id}&chapter_id={second.id}"
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["chapter"]["id"] == second.id
    assert {asset["id"] for asset in data["assets"]} == {current.id, reused.id}
    assert unrelated.id not in {asset["id"] for asset in data["assets"]}
    assert data["assets"][0]["variants"][0]["images"] == [
        "/media/variant-a.png",
        "/media/variant-b.png",
    ]
    assert data["scenes"][0]["assets"][0]["id"] == reused.id
    assert data["videos"][str(scene.id)][0]["id"] == video.id
    assert first.id != second.id
