import base64
import io
import stat
import zipfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from api.user_skill import router
from auth.deps import AuthContext, get_auth_context
from models.user_skill import UserSkill
from prompts.skill_packages import builtin_package
from schemas.user_skill import UserSkillInput, UserSkillUpdate
from services import user_skills
from utils.skill_package import MAX_FILE_BYTES, SkillPackage, package_file

ENTRY = '---\nname: demo-skill\ndescription: 用于测试完整的技能目录。\n---\n\nRead [method](references/method.md).\nRun `scripts/helper.py`.\n'
FILES = {'SKILL.md': ENTRY.encode(), 'references/method.md': '参考 {{max_seconds}} 秒'.encode(),
    'scripts/helper.py': b'print("stored, not executed")\n', 'assets/sample.bin': b'\x89PNG\0\xff'}


def archive(files=FILES, prefix='demo-skill/'):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for path, content in files.items():
            zipped.writestr(prefix + path, content)
    return output.getvalue()


def test_archive_roundtrip_preserves_folder_text_binary_and_script(tmp_path):
    package = SkillPackage.from_archive(archive())
    assert package.metadata['name'] == 'demo-skill'
    assert {file['path'] for file in package.files} == set(FILES)
    assert package.by_path['SKILL.md']['content'] == ENTRY
    assert base64.b64decode(package.by_path['assets/sample.bin']['content']) == FILES['assets/sample.bin']
    method = package.as_method()
    assert {file['name'] for file in method['references']} == {'references/method.md', 'scripts/helper.py'}
    assert 'assets/sample.bin' not in {file['path'] for file in method['file_manifest']}
    assert not (tmp_path / 'scripts').exists()
    assert SkillPackage.from_archive(package.archive()).files == package.files


@pytest.mark.parametrize('path', ['../outside.md', '/outside.md', 'C:/outside.md', 'a/../../outside.md', 'a\\outside.md', 'a//outside.md'])
def test_archive_never_accepts_paths_outside_the_skill(path):
    with pytest.raises(ValueError):
        SkillPackage.from_archive(archive({**FILES, path: b'bad'}, prefix=''))


def test_archive_rejects_symlinks_duplicates_multiple_roots_and_oversized_files():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as zipped:
        zipped.writestr('SKILL.md', ENTRY)
        link = zipfile.ZipInfo('scripts/link')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(link, '../outside')
    with pytest.raises(ValueError, match='符号链接'):
        SkillPackage.from_archive(output.getvalue())
    with pytest.raises(ValueError, match='重复'):
        SkillPackage.from_archive(archive({**FILES, 'skill.md': ENTRY.encode()}))
    with pytest.raises(ValueError, match='一个完整'):
        SkillPackage.from_archive(archive({'one/SKILL.md': ENTRY.encode(), 'two/SKILL.md': ENTRY.encode()}, prefix=''))
    with pytest.raises(ValueError, match='5 MB'):
        SkillPackage.from_archive(archive({**FILES, 'large.txt': b'a' * (MAX_FILE_BYTES + 1)}))
    with pytest.raises(ValueError, match='路径冲突'):
        SkillPackage.from_archive(archive({**FILES, 'references': b'not a directory'}))


@pytest.mark.parametrize('entry', ['# prompt only', '---\nname: demo\n---\nbody', '---\nname: Bad_Name\ndescription: text\n---', '---\nname: !!python/object/apply:os.system ["false"]\ndescription: text\n---'])
def test_skill_entry_requires_safe_standard_frontmatter(entry):
    with pytest.raises(ValueError):
        SkillPackage([package_file('SKILL.md', entry.encode())])


def test_resource_loading_follows_document_paths_without_reading_script_dependencies_or_unrelated_files():
    files = {**FILES, 'SKILL.md': (ENTRY + '\nMetadata is not a resource named data.\n').encode(),
        'scripts/helper.py': b'open("config.env"); print("{{input}}")\n', 'config.env': b'private', 'data': b'unrelated'}
    package = SkillPackage.from_archive(archive(files))
    method = package.as_method()
    assert {item['name'] for item in method['references']} == {'references/method.md', 'scripts/helper.py'}
    from prompts.text_tasks import render_text_task
    import json
    _, content = render_text_task(language='zh', skill=method, context={'input': 'material'})
    script = next(item for item in json.loads(content)['creative_method']['references'] if item['name'] == 'scripts/helper.py')
    assert '{{input}}' in script['content']
    assert 'private' not in content and 'unrelated' not in content


@pytest.mark.parametrize('task', ['story', 'screenplay', 'assets', 'storyboard'])
def test_builtin_folders_are_portable_and_include_their_linked_resources(task):
    package = builtin_package(task)
    assert package.by_path['SKILL.md']['content'].startswith('---')
    assert package.metadata['name']
    package.linked_paths()
    assert SkillPackage.from_archive(package.archive()).files == package.files
    if task == 'screenplay':
        from prompts.skill_pack import read_skill
        method = package.as_method()
        assert set(package.by_path) == {'SKILL.md', 'agents/openai.yaml'}
        assert method['instructions'] == read_skill(task)
        assert method['references'] == []
        return
    if task != 'story':
        assert any(file['path'].startswith('references/') for file in package.files)
        assert 'agents/openai.yaml' in package.by_path
        from prompts.skill_pack import read_skill
        method = package.as_method()
        assert 'references/source-skill.md' in package.by_path
        if task == 'storyboard':
            entry = package.by_path['SKILL.md']['content']
            continuity = read_skill('storyboard_continuity').strip()
            assert continuity in entry and entry.endswith(read_skill('strict_storyboard'))
            assert 'continuity.md' in read_skill('novelvids-storyboard')
            assert package.by_path['references/continuity.md']['content'].strip() == continuity
            assert method['instructions'] == entry
            assert not method['references']
        else:
            assert len(method['references']) == 1
            assert method['references'][0]['content'] == read_skill(f'strict_{task}')


@pytest.mark.asyncio
async def test_skill_folder_save_freezes_resources_and_preserves_legacy_rows():
    package = SkillPackage.from_archive(archive())
    body = UserSkillInput(task='screenplay', name='我的技能', files=package.files)
    saved = await user_skills.save_skill(12, body)
    assert saved['files'] == package.files
    snapshot = await user_skills.snapshot_method(12, 'screenplay', saved['id'])
    assert 'files' not in snapshot
    assert {item['name'] for item in snapshot['references']} == {'references/method.md', 'scripts/helper.py'}
    changed = [{**file, 'content': file['content'] + '\nchanged' if file['path'] == 'references/method.md' else file['content']} for file in package.files]
    await user_skills.save_skill(12, UserSkillUpdate(task='screenplay', name='我的技能', files=changed, expected_version=1), saved['id'])
    assert (await user_skills.snapshot_method(12, 'screenplay', saved['id']))['revision'] != snapshot['revision']
    assert snapshot['references'][0]['content'] == '参考 {{max_seconds}} 秒'
    legacy = await UserSkill.create(owner_id=12, task='story', name='旧技能', instructions='旧方法', references=[{'name': '旧资料', 'content': '旧内容'}])
    detail = await user_skills.detail_skill(12, 'story', legacy.id)
    assert any(file['content'] == '旧内容' for file in detail['files'])
    await legacy.refresh_from_db()
    assert legacy.files == [] and legacy.instructions == '旧方法'


@pytest.mark.asyncio
async def test_folder_uses_entry_metadata_and_old_clients_cannot_overwrite_its_files():
    from fastapi import HTTPException
    package = SkillPackage.from_archive(archive())
    saved = await user_skills.save_skill(11, UserSkillInput(task='screenplay', files=package.files))
    assert saved['name'] == 'demo-skill' and saved['description'] == '用于测试完整的技能目录。'
    with pytest.raises(HTTPException) as caught:
        await user_skills.save_skill(11, UserSkillUpdate(task='screenplay', name='old client', instructions='overwrite', expected_version=1), saved['id'])
    assert caught.value.status_code == 409
    assert (await UserSkill.get(id=saved['id'])).files == package.files


@pytest.mark.asyncio
async def test_zip_import_is_a_private_draft_until_explicit_save_and_exports_exact_files():
    app = FastAPI()
    app.include_router(router, prefix='/skills')
    ctx = AuthContext(user=SimpleNamespace(id=11), is_super_admin=True)
    app.dependency_overrides[get_auth_context] = lambda: ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        imported = await client.post('/skills/import', data={'task': 'screenplay'}, files={'file': ('demo.zip', archive(), 'application/zip')})
        assert imported.status_code == 200, imported.text
        draft = imported.json()['data']
        assert await UserSkill.all().count() == 0
        payload = {key: draft[key] for key in ('task', 'name', 'description', 'files', 'is_active')}
        created = (await client.post('/skills', json=payload)).json()['data']
        listed = (await client.get('/skills?task=screenplay')).json()['data']['items'][1]
        assert listed['is_summary'] and 'files' not in listed
        assert (await client.get(f'/skills/{created["id"]}?task=screenplay')).json()['data']['files'] == draft['files']
        exported = await client.post('/skills/export', json=payload)
        assert exported.headers['content-type'] == 'application/zip'
        assert SkillPackage.from_archive(exported.content).files == draft['files']
        await client.put('/skills/default/screenplay', json={'skill_id': created['id']})
        status = await client.patch(f'/skills/{created["id"]}/status', json={'is_active': False, 'expected_version': 1})
        assert status.status_code == 200 and status.json()['data']['version'] == 2
        stored = await UserSkill.get(id=created['id'])
        assert stored.files == draft['files'] and not stored.is_active
        assert (await client.get('/skills?task=screenplay')).json()['data']['default_skill_id'] == 0
        assert (await client.patch(f'/skills/{created["id"]}/status', json={'is_active': True, 'expected_version': 1})).status_code == 409
        ctx.user.id = 12
        assert (await client.get(f'/skills/{created["id"]}?task=screenplay')).status_code == 404
        assert (await client.patch(f'/skills/{created["id"]}/status', json={'is_active': True, 'expected_version': 2})).status_code == 404


def test_old_skill_table_gets_files_without_losing_legacy_data_or_preferences(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as db:
        db.executescript('''
CREATE TABLE user_skills(id INTEGER PRIMARY KEY, owner_id INT, task VARCHAR(24), name VARCHAR(100),
description VARCHAR(1000), instructions TEXT, "references" JSON, version INT, is_active INT,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
INSERT INTO user_skills(id,owner_id,task,name,description,instructions,"references",version,is_active)
VALUES(1,11,'story','legacy','','unchanged','[{"name":"notes","content":"keep"}]',3,1);
CREATE TABLE task_skill_preferences(id INTEGER PRIMARY KEY, owner_id INT, task VARCHAR(24), skill_id INT,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
INSERT INTO task_skill_preferences(id,owner_id,task,skill_id) VALUES(1,11,'story',1);
''')
    script = '''
import asyncio, os
from tortoise import Tortoise
import models
from services.schema_compat import ensure_text_task_schema
async def run():
    await Tortoise.init(db_url=os.environ['DATABASE_URL'], modules={'models':[f'models.{name}' for name in models.__all__]})
    await ensure_text_task_schema()
    await ensure_text_task_schema()
    await Tortoise.close_connections()
asyncio.run(run())
'''
    subprocess.run([sys.executable, '-c', script], check=True, env={**os.environ, 'DATABASE_URL': f'sqlite://{path}'})
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT instructions,"references",version,files FROM user_skills').fetchone() == ('unchanged', '[{"name":"notes","content":"keep"}]', 3, '[]')
        assert db.execute('SELECT skill_id FROM task_skill_preferences').fetchone() == (1,)
