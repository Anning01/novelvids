from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from api.user_skill import router
from auth.deps import AuthContext, get_auth_context
from models.config import AiModelConfig
from models.user_skill import UserSkill
from schemas.user_skill import UserSkillInput, UserSkillUpdate
from services import user_skills


def method(**updates):
    return UserSkillInput(task='story', name='悬疑分析', instructions='关注伏笔与人物动机。', **updates)


@pytest.mark.asyncio
async def test_markdown_roundtrip_preserves_frontmatter_placeholders_and_whitespace():
    source = '---\nname: test\n---\n# Method\n{{input}}  \n```json\n{}\n```\n'
    body = UserSkillInput(task='story', name=' Test ', instructions=source, references=[{'name': ' Reference ', 'content': source}])
    saved = await user_skills.save_skill(10, body)
    assert saved['instructions'] == source
    assert saved['references'][0]['content'] == source
    assert saved['name'] == 'Test'


@pytest.mark.asyncio
async def test_private_skills_defaults_versions_and_archived_selection():
    first = await user_skills.save_skill(11, method())
    assert (await user_skills.list_skills(12, 'story'))['items'][0]['builtin']
    assert len((await user_skills.list_skills(12, 'story'))['items']) == 1
    for owner, task in ((12, 'story'), (11, 'screenplay')):
        with pytest.raises(HTTPException) as error:
            await user_skills.snapshot_method(owner, task, first['id'])
        assert error.value.status_code == 404
    await user_skills.set_default(11, 'story', first['id'])
    frozen = await user_skills.snapshot_method(11, 'story')
    update = UserSkillUpdate(**{**method().model_dump(), 'instructions': '新的方法'}, expected_version=1)
    edited = await user_skills.save_skill(11, update, first['id'])
    assert edited['version'] == 2 and frozen['instructions'] == '关注伏笔与人物动机。'
    assert (await user_skills.snapshot_method(11, 'story'))['revision'] != frozen['revision']
    with pytest.raises(HTTPException) as conflict:
        await user_skills.save_skill(11, update, first['id'])
    assert conflict.value.status_code == 409
    await user_skills.save_skill(11, UserSkillUpdate(**{**method().model_dump(), 'is_active': False}, expected_version=2), first['id'])
    assert (await user_skills.snapshot_method(11, 'story'))['id'] == 0
    with pytest.raises(HTTPException):
        await user_skills.set_default(11, 'story', first['id'])
    with pytest.raises(HTTPException):
        await user_skills.snapshot_method(11, 'story', first['id'])


@pytest.mark.asyncio
async def test_skill_api_never_accepts_output_schemas_or_another_owner(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix='/skills')
    ctx = AuthContext(user=SimpleNamespace(id=11), is_super_admin=True)
    app.dependency_overrides[get_auth_context] = lambda: ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        body = method().model_dump()
        for injected in ({'schema': {}}, {'owner_id': 12}, {'task': 'video'}):
            assert (await client.post('/skills', json={**body, **injected})).status_code == 422
        saved = (await client.post('/skills', json=body)).json()['data']
        assert (await client.put('/skills/default/story', json={'skill_id': saved['id']})).status_code == 200
        response = await client.put(f'/skills/{saved["id"]}', json={**body, 'name': '修订', 'expected_version': 1})
        assert response.json()['data']['version'] == 2
        ctx.user.id = 12
        assert (await client.put(f'/skills/{saved["id"]}', json={**body, 'expected_version': 2})).status_code == 404
        assert (await client.put('/skills/default/story', json={'skill_id': saved['id']})).status_code == 404
        assert len((await client.get('/skills?task=story')).json()['data']['items']) == 1


@pytest.mark.asyncio
async def test_model_list_uses_strict_capability_and_hides_secrets():
    app = FastAPI()
    app.include_router(router, prefix='/skills')
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(is_super_admin=True)
    shared = dict(task_type=7, model='test', base_url='https://private.invalid', api_key='private-key', is_active=True)
    strict = await AiModelConfig.create(name='严格', supports_strict_output=True, **shared)
    await AiModelConfig.create(name='普通JSON', supports_json_output=True, supports_tool_calls=True, **shared)
    await AiModelConfig.create(name='其他团队', supports_json_output=True, team_id=5, **shared)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/skills/models')
        assert response.json()['data'] == [{'id': strict.id, 'name': '严格', 'model': 'test'}]
        assert 'private' not in response.text


@pytest.mark.asyncio
async def test_safe_schema_initialization_preserves_skills_and_defaults():
    from services.schema_compat import ensure_text_task_schema
    saved = await user_skills.save_skill(0, method())
    await user_skills.set_default(0, 'story', saved['id'])
    await ensure_text_task_schema()
    await ensure_text_task_schema()
    assert await UserSkill.all().count() == 1
    assert (await user_skills.snapshot_method(0, 'story'))['id'] == saved['id']


def test_old_sqlite_upgrade_preserves_data_and_defaults_to_no_strict_support(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE ai_model_configs(id INTEGER PRIMARY KEY, name TEXT); INSERT INTO ai_model_configs VALUES (1, 'existing');")
    script = '''
import asyncio, os
from tortoise import Tortoise
import models
from services.schema_compat import ensure_text_task_schema
async def run():
    await Tortoise.init(db_url=os.environ['DATABASE_URL'], modules={'models':[f'models.{n}' for n in models.__all__]})
    await ensure_text_task_schema()
    await ensure_text_task_schema()
    await Tortoise.close_connections()
asyncio.run(run())
'''
    subprocess.run([sys.executable, '-c', script], check=True, env={**os.environ, 'DATABASE_URL': f'sqlite://{path}'})
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT id,name,supports_strict_output,text_api FROM ai_model_configs').fetchall() == [(1, 'existing', 0, 'chat_completions')]
        assert db.execute('SELECT COUNT(*) FROM user_skills').fetchone() == (0,)
        assert db.execute('SELECT COUNT(*) FROM task_skill_preferences').fetchone() == (0,)


@pytest.mark.asyncio
async def test_postgres_upgrade_uses_safe_additive_statements(monkeypatch):
    from services.schema_compat import ensure_text_task_schema
    connection = Mock()
    connection.capabilities.dialect = 'postgres'
    connection.execute_script = AsyncMock()
    generator = connection.schema_generator.return_value
    generator._get_table_sql.side_effect = lambda model, safe: {'table_creation_string': f'CREATE TABLE IF NOT EXISTS {model._meta.db_table} (id INT);'}
    monkeypatch.setattr('services.schema_compat.Tortoise.get_connection', lambda _: connection)
    await ensure_text_task_schema()
    await ensure_text_task_schema()
    sql = '\n'.join(call.args[0] for call in connection.execute_script.await_args_list)
    assert 'ADD COLUMN IF NOT EXISTS supports_strict_output BOOL NOT NULL DEFAULT FALSE' in sql
    assert "ADD COLUMN IF NOT EXISTS files JSONB NOT NULL DEFAULT '[]'::jsonb" in sql
    assert 'DROP' not in sql and 'DELETE' not in sql
    assert all(call.kwargs['safe'] for call in generator._get_table_sql.call_args_list)
