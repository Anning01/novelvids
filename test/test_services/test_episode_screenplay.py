from unittest.mock import AsyncMock

import pytest
from auth.deps import AuthContext
from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from services.ai_task_executor import ai_task_executor
from services.chapter_screenplay import EpisodeScript, submit_screenplay
from services.creation_agent.skill_execution import SkillExecution
from services.extraction.context import ExtractionContextLoader


@pytest.mark.asyncio
async def test_explicit_adaptation_deduplicates_and_preserves_source(configured_creation_agent, monkeypatch):
    novel = await Novel.create(name="救人")
    chapter = await Chapter.create(novel=novel, number=1, name="救人", content="徐长寿牵牛走在泥路上。")
    text = "1-1　泥路　外　黄昏\n出场：徐长寿、老黄牛\n△ 徐长寿牵牛停下。"
    generate = AsyncMock(return_value=EpisodeScript(screenplay=text))
    monkeypatch.setattr(SkillExecution, 'generate', generate)
    assert not await AiTask.all().exists()
    from controllers.chapter import chapter_controller
    from schemas.chapter import ChapterPatch
    pacing = {"preset": "fast", "max_seconds": 90}
    await chapter_controller.patch(chapter.id, ChapterPatch(episode_pacing=pacing))
    task = await submit_screenplay(chapter.id, AuthContext())
    assert (await submit_screenplay(chapter.id, AuthContext())).id == task.id
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    await chapter.refresh_from_db()
    assert chapter.content == "徐长寿牵牛走在泥路上。" and chapter.screenplay == text
    assert generate.await_args.args[0] == "screenplay"
    assert generate.await_args.args[1]["source_text"] == chapter.content
    assert generate.await_args.args[1]["episode_pacing"] == pacing
    context = await ExtractionContextLoader().load(novel_id=novel.id, chapter_id=chapter.id)
    assert context.chapter.content == text


@pytest.mark.asyncio
async def test_changed_source_is_not_overwritten(configured_creation_agent, monkeypatch):
    novel = await Novel.create(name="迟到的稿")
    chapter = await Chapter.create(novel=novel, number=1, name="救人", content="初稿")
    async def generate(*args, **kwargs):
        await Chapter.filter(id=chapter.id).update(content="用户修订")
        return EpisodeScript(screenplay="# 第1集 救人\n本集时长上限：90 秒\n迟到的导演稿")
    monkeypatch.setattr(SkillExecution, 'generate', generate)
    task = await submit_screenplay(chapter.id, AuthContext())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    await chapter.refresh_from_db()
    assert task.status == 4 and not chapter.screenplay and chapter.content == "用户修订"


def test_upgrade_classifies_only_proven_legacy_screenplays_and_runs_twice(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys

    db = tmp_path / 'legacy.db'
    with sqlite3.connect(db) as conn:
        conn.executescript("""
          CREATE TABLE chapters (id INTEGER PRIMARY KEY, content TEXT);
          CREATE TABLE work_sync_objects (kind TEXT, local_id INTEGER);
          INSERT INTO chapters VALUES (11,'原文'),(12,'已编辑的导演稿');
          INSERT INTO work_sync_objects VALUES ('episode',12),('asset',11);
        """)
    code = """
import asyncio, os
from tortoise import Tortoise
import models
from services.schema_compat import ensure_chapter_screenplay_schema
async def main():
    await Tortoise.init(db_url=os.environ['DATABASE_URL'], modules={'models':[f'models.{n}' for n in models.__all__]})
    await ensure_chapter_screenplay_schema()
    await ensure_chapter_screenplay_schema()
    await Tortoise.close_connections()
asyncio.run(main())
"""
    subprocess.run([sys.executable, '-c', code], check=True, env={**os.environ,'DATABASE_URL': f'sqlite://{db}'})
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT episode_pacing FROM chapters').fetchall() == [(None,), (None,)]
        assert conn.execute('SELECT content,screenplay FROM chapters ORDER BY id').fetchall() == [
            ('原文', None), ('', '已编辑的导演稿')]


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent_edit", [False, True])
async def test_regenerate_requires_the_confirmed_script_and_protects_later_edits(configured_creation_agent, monkeypatch, concurrent_edit):
    from fastapi import HTTPException
    novel = await Novel.create(name="重新改编")
    chapter = await Chapter.create(novel=novel, number=1, name="救人", content="小说", screenplay="原导演稿")
    with pytest.raises(HTTPException):
        await submit_screenplay(chapter.id, AuthContext())
    async def generate(*args):
        if concurrent_edit:
            await Chapter.filter(id=chapter.id).update(screenplay="手动改稿")
        return EpisodeScript(screenplay="# 第1集 救人\n本集时长上限：90 秒\n新导演稿")
    monkeypatch.setattr(SkillExecution, "generate", generate)
    task = await submit_screenplay(chapter.id, AuthContext(), "原导演稿")
    await ai_task_executor.run(task)
    await chapter.refresh_from_db()
    await task.refresh_from_db()
    assert task.status == (4 if concurrent_edit else 3)
    assert chapter.content == "小说" and chapter.screenplay == ("手动改稿" if concurrent_edit else "# 第1集 救人\n本集时长上限：90 秒\n新导演稿")


@pytest.mark.asyncio
@pytest.mark.parametrize("pacing", [None, {"preset": "smart", "max_seconds": None}])
async def test_smart_pacing_saves_script_without_duration_header(configured_creation_agent, monkeypatch, pacing):
    novel = await Novel.create(name="自动估时")
    chapter = await Chapter.create(novel=novel, number=1, name="救人", content="小说", screenplay="原导演稿", episode_pacing=pacing)
    generate = AsyncMock(return_value=EpisodeScript(screenplay="没有时长的新导演稿"))
    monkeypatch.setattr(SkillExecution, "generate", generate)
    task = await submit_screenplay(chapter.id, AuthContext(), "原导演稿")
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    await chapter.refresh_from_db()
    generate.assert_awaited_once()
    assert generate.await_args.args[1]["episode_pacing"] == (pacing or {"preset": "smart"})
    assert task.status == 3, task.error_message
    assert chapter.screenplay == "没有时长的新导演稿"


@pytest.mark.asyncio
async def test_screenplay_sends_complete_skill_without_lookup_or_output_retry(configured_creation_agent, monkeypatch):
    import json

    import httpx
    from openai import AsyncOpenAI

    from test.agent_stream_fixtures import completion_stream_response

    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return completion_stream_response({
            "id": "screenplay", "created": 1, "model": "mock-model", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
        })

    monkeypatch.setattr("services.creation_agent.handler.AsyncOpenAI", lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    novel = await Novel.create(name="单次改编")
    chapter = await Chapter.create(novel=novel, number=1, name="救人", content="徐长寿牵牛回村。")
    task = await submit_screenplay(chapter.id, AuthContext())
    await ai_task_executor.run(task)
    await task.refresh_from_db()

    assert task.status == 4
    assert len(requests) == 1 and not requests[0].get("tools")
    messages = str(requests[0]["messages"])
    assert "episode_pacing" in messages and "本集按剧情自然展开" in messages
    assert "Target episode duration:" in messages
    assert "不是硬性上限" in messages


@pytest.mark.asyncio
async def test_adaptation_runs_with_selected_model_and_rejects_switch_while_running(configured_creation_agent):
    from fastapi import HTTPException
    from models.config import AiModelConfig

    novel = await Novel.create(name="选择改编模型")
    chapter = await Chapter.create(novel=novel, number=1, name="本集", content="原文")
    other = await AiModelConfig.create(name="另一模型", model="other", task_type=7,
        base_url="https://example.invalid", api_key="test", supports_tool_calls=True, is_active=True)
    selected = configured_creation_agent.id
    task = await submit_screenplay(chapter.id, AuthContext(), assistant_model_config_id=selected)
    assert task.request_params["assistant_model_config_id"] == selected
    with pytest.raises(HTTPException) as conflict:
        await submit_screenplay(chapter.id, AuthContext(), assistant_model_config_id=other.id)
    assert conflict.value.status_code == 409
