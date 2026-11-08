import re

from test.test_services.test_asset_design_instructions import fixed_asset_prompt, synthetic_snapshot
from test.test_services.test_prompt_language import _shot


def design_fields(kind='person', language='zh'):
    return dict(re.findall(r'^\*\*(.+?)\*\*:\s*(.+)$', fixed_asset_prompt(language, kind), re.M))


def remake_shot(index=1, duration=4.2, refs=None):
    payload = _shot().model_dump()
    payload.update(sequence=index, duration=f'{duration:g}s', description=f'专业镜头 {index}',
        spatial_relationships='将军站在军帐中央，镜头正对将军', visual_prose='将军在烛光中抬眼。',
        actions=[f'0s-{duration:g}s: @将军抬眼。'], shot_index=index, file=f'scene-{index:03d}.mp4',
        duration_seconds=duration, confidence=.9,
        asset_refs=refs if refs is not None else [{'asset_id':'character-001','asset_name':'将军','asset_type':'character'}])
    if refs == []:
        payload.update(spatial_relationships='空地与镜头间保持固定距离', visual_prose='空地上光影平稳。',
            actions=[f'0s-{duration:g}s: 光线缓慢变化。'])
    elif refs:
        payload['visual_prose'] = '、'.join(reference['asset_name'] for reference in refs) + '出现在画面中央。'
    return payload
