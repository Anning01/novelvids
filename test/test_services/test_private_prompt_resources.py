import json
import subprocess

import pytest

import prompts.skill_pack as pack


@pytest.fixture
def public_pack(tmp_path, monkeypatch):
    for filename in pack.FILES.values():
        (tmp_path / filename).write_text((pack.ROOT / filename).read_text())
    monkeypatch.setattr(pack, 'ROOT', tmp_path)
    return tmp_path


@pytest.mark.parametrize('name', ['base', 'assets', 'image', 'storyboard', 'story'])
def test_markdown_override_replaces_whole_file_and_is_frozen_in_snapshot(public_pack, name):
    path = public_pack / pack.FILES[name]
    original = path.read_text()
    before = pack.snapshot_skills()
    private = path.with_name(path.stem + '.anning.md')
    private.write_text('Private test instructions')
    after = pack.snapshot_skills()
    assert pack.read_skill(name) == 'Private test instructions'
    assert after['contents'][name] == 'Private test instructions'
    assert before['contents'][name] == original
    assert after['revision'] != before['revision']
    private.write_text('Next revision')
    assert after['contents'][name] == 'Private test instructions'
    private.unlink()
    assert pack.read_skill(name) == original
    assert path.read_text() == original


@pytest.mark.parametrize('name', ['styles', 'strategies', 'asset_contract', 'storyboard_contract'])
def test_json_override_merges_top_level_keys_without_changing_public_file(public_pack, name):
    path = public_pack / pack.FILES[name]
    before = json.loads(path.read_text())
    value = {'label': 'Private', 'image': 'Test image', 'video': 'Test video'} if name == 'styles' else {'test': 'instructions'}
    path.with_name(path.stem + '.anning.json').write_text(json.dumps({'test-key': value}))
    assert json.loads(pack.read_skill(name)) == {**before, 'test-key': value}
    assert json.loads(path.read_text()) == before


@pytest.mark.parametrize('content', ['[]', '{broken', 'null'])
def test_invalid_private_json_fails_without_echoing_content(public_pack, content):
    (public_pack / 'strategies.anning.json').write_text(content)
    with pytest.raises(ValueError, match='Invalid private strategies') as error:
        pack.read_skill('strategies')
    assert content not in str(error.value)


def test_empty_private_markdown_cannot_silently_remove_instructions(public_pack):
    (public_pack / 'assets.anning.md').write_text('  \n')
    with pytest.raises(ValueError, match='must not be empty'):
        pack.read_skill('assets')


def test_private_resources_are_ignored_by_git():
    paths = ['prompts/skills/assets.anning.md', 'prompts/skills/SKILL.anning.md',
             'prompts/skills/styles.anning.json', 'prompts/skills/asset_contract.anning.json']
    result = subprocess.run(['git', 'check-ignore', '--stdin'], input='\n'.join(paths), text=True, capture_output=True, check=True)
    assert result.stdout.splitlines() == paths
