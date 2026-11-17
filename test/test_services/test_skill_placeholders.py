import json

import pytest

from prompts.text_tasks import builtin_method, render_text_task, render_skill_markdown


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('pacing', [None, {'preset': 'fast', 'max_seconds': 75}, {'preset': 'slow', 'max_seconds': 180}])
def test_screenplay_placeholders_use_episode_settings_without_changing_saved_template(language, pacing):
    skill = builtin_method('screenplay')
    original = next(reference['content'] for reference in skill['references'] if reference['name'] == 'references/screenplay.md')
    system, user = render_text_task(language=language, skill=skill,
        context={'input': {'source_text': '渡口来了一条陌生的船。', 'episode_pacing': pacing}})
    rendered = next(reference['content'] for reference in json.loads(user)['creative_method']['references'] if reference['name'] == 'references/screenplay.md')
    assert '{{episode_pacing}}' in original and '{{max_seconds}}' in original
    assert '90 秒' not in original and '90s' not in original
    assert '{{episode_pacing}}' not in rendered and '{{max_seconds}}' not in rendered
    assert next(reference['content'] for reference in skill['references'] if reference['name'] == 'references/screenplay.md') == original
    assert f'language={language}' in system
    if pacing is None:
        assert '本集参考秒数：null' in rendered and '本集按剧情自然展开' in rendered
        assert '"preset": "smart"' in rendered
    else:
        assert f'本集参考时长：约 {pacing["max_seconds"]} 秒' in rendered
        assert f'Target episode duration: about {pacing["max_seconds"]}s' in rendered
        assert json.dumps(pacing, ensure_ascii=False) in rendered


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
