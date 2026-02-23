import pytest

from models.novel import Novel
from models.chapter import Chapter
from models.config import AiModelConfig
from utils.enums import AiTaskTypeEnum


@pytest.mark.asyncio
async def test_novel_str():
    """Novel.__str__ 返回小说名称。"""
    novel = await Novel.create(name="测试小说", author="作者")
    assert str(novel) == "测试小说"
    print(f"    Novel.__str__: '{str(novel)}'")


@pytest.mark.asyncio
async def test_chapter_str():
    """Chapter.__str__ 返回章节名称。"""
    novel = await Novel.create(name="章节测试小说", author="作者")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="第一章 开端", content="内容"
    )
    assert str(chapter) == "第一章 开端"
    print(f"    Chapter.__str__: '{str(chapter)}'")


@pytest.mark.asyncio
async def test_ai_model_config_str_active():
    """AiModelConfig.__str__ 启用状态显示。"""
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.storyboard.value,
        name="deepseek-v3",
        base_url="https://api.example.com",
        api_key="sk-test",
        model="deepseek-v3",
        is_active=True,
    )
    result = str(config)
    assert "✓" in result
    assert "deepseek-v3" in result
    assert AiTaskTypeEnum.storyboard.nickname in result
    print(f"    AiModelConfig.__str__ (active): '{result}'")


@pytest.mark.asyncio
async def test_ai_model_config_str_inactive():
    """AiModelConfig.__str__ 禁用状态显示。"""
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="gpt-4o",
        base_url="https://api.example.com",
        api_key="sk-test",
        model="gpt-4o",
        is_active=False,
    )
    result = str(config)
    assert "✗" in result
    assert "gpt-4o" in result
    print(f"    AiModelConfig.__str__ (inactive): '{result}'")
