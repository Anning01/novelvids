import json
from copy import deepcopy

import pytest

from prompts.text_tasks import builtin_method, render_text_task, render_skill_markdown


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('pacing', [None, {'preset': 'smart', 'max_seconds': None},
    {'preset': 'compact', 'max_seconds': 45}, {'preset': 'fast', 'max_seconds': 75},
    {'preset': 'smart', 'max_seconds': 120}, {'preset': 'slow', 'max_seconds': 180},
    {'preset': 'detailed', 'max_seconds': 240}])
def test_screenplay_settings_are_in_task_content_without_changing_skill(language, pacing):
    skill = builtin_method('screenplay')
    original = deepcopy(skill)
    context = {'input': {'source_text': '渡口来了一条陌生的船。', 'episode_pacing': pacing}}
    original_context = deepcopy(context)
    system, user = render_text_task(language=language, skill=skill,
        context=context)
    payload = json.loads(user)
    task = payload['task_context']
    settings = {'preset': 'smart', 'max_seconds': None, **(pacing or {})}
    assert task['episode_pacing'] == settings
    assert task['input'] == context['input']
    assert payload['creative_method']['instructions'] == original['instructions']
    assert payload['creative_method']['references'] == []
    assert '{{' not in original['instructions']
    assert skill == original and context == original_context
    assert f'language={language}' in system
    requirements = task['screenplay_requirements']
    assert settings['preset'] in requirements
    assert requirements not in payload['creative_method']['instructions']
    if settings['max_seconds'] is None:
        assert '按剧情自然展开' in requirements and '省略参考时长行' in requirements
        assert '本集参考时长：约' not in requirements and 'Target episode duration:' not in requirements
    else:
        seconds = settings['max_seconds']
        header = f'Target episode duration: about {seconds}s' if language == 'en' else f'本集参考时长：约 {seconds} 秒'
        assert header in requirements and '集标题下一行' in requirements
        assert '不是硬性上限' in requirements


@pytest.mark.parametrize('task', ['story', 'assets', 'storyboard'])
def test_screenplay_output_requirements_are_not_injected_into_other_tasks(task):
    context = {'input': {'episode_pacing': {'preset': 'fast', 'max_seconds': 75}}}
    _, user = render_text_task(language='zh', skill=builtin_method(task), context=context)
    assert json.loads(user)['task_context'] == context


def test_placeholder_rendering_is_literal_single_pass_and_dictionary_only():
    values = {'input': '原文中有 {{max_seconds}} 与 \\1', 'max_seconds': 75, 'project': {'name': '渡口'}, 'empty': None}
    rendered = render_skill_markdown('{{input}}\n{{ max_seconds }}\n{{project.name}}\n{{missing}}\n{{project.__class__}}\n{{empty}}', values)
    assert rendered == '原文中有 {{max_seconds}} 与 \\1\n75\n渡口\n{{missing}}\n{{project.__class__}}\nnull'


def test_references_and_custom_skills_share_the_same_placeholder_renderer():
    skill = {'instructions': '节奏 {{episode_pacing.preset}}，目标 {{max_seconds}} 秒',
        'references': [{'name': '示例', 'content': '输入 {{input}}；语言 {{language}}'}]}
    _, user = render_text_task(language='en', skill=skill,
        context={'input': '素材', 'episode_pacing': {'preset': 'detailed', 'max_seconds': 130}})
    method = json.loads(user)['creative_method']
    assert method['instructions'] == '节奏 detailed，目标 130 秒'
    assert method['references'][0]['content'] == '输入 素材；语言 en'
    assert skill['references'][0]['content'] == '输入 {{input}}；语言 {{language}}'
