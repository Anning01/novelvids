"""Idempotent ten-chapter, three-identity material for local agent acceptance."""

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.scene import Scene
from prompts.storyboard import format_storyboard_prompt
from services.creation_agent.tools import PromptEditService
from test.test_services.test_asset_design_instructions import fixed_asset_prompt
from test.test_services.test_storyboard_handler import _shot


async def seed_project_identities(novel):
    if not novel.project_setting:
        novel.project_setting = '群岛王朝；灯塔与渡口属于同一世界。'
    if not novel.custom_style_prompt:
        novel.custom_style_prompt = '国风水墨，靛青与暖灰，保持统一世界画风。'
    novel.author = novel.author or 'Agent 创建'
    novel.total_chapters = 10
    await novel.save(update_fields=['project_setting', 'custom_style_prompt', 'author', 'total_chapters'])
    for number in range(1, 11):
        await Chapter.get_or_create(novel=novel, number=number, defaults={
            'name': f'第{number}章', 'content': '第十章回忆第二章渡口时期的林舟，应使用原渡口学徒身份而非守望者身份。' if number == 10 else f'第{number}章：林舟在同一世界中的经历。'})
    base = fixed_asset_prompt(ratio=novel.aspect_ratio or '16:9').replace('Realistic drama', novel.custom_style_prompt)
    hero, _ = await Asset.get_or_create(novel=novel, canonical_name='林舟', asset_type=1, defaults={
        'aliases': ['主角', '阿舟'], 'is_global': True, 'source_chapters': list(range(1, 11)),
        'description': '同一位主角的三个已登记身份。', 'base_traits': base})
    variants = []
    for name, numbers, outfit in [('渡口学徒', [1, 2, 3], '靛青棉麻短衣'),
            ('城卫身份', [4, 5, 6, 7], '玄铁护卫铠甲'), ('灯塔守望者', [8, 9, 10], '灰白灯塔长袍')]:
        variant, _ = await AssetVariant.get_or_create(asset=hero, name=name, defaults={
            'description': f'林舟的{name}身份；保持同一人物的脸，不另建人物卡。',
            'chapter_numbers': numbers, 'base_traits': base.replace('Navy cotton school jacket', outfit)})
        variants.append(variant)
    tenth = await Chapter.get(novel=novel, number=10)
    scene, created = await Scene.get_or_create(chapter=tenth, sequence=1, defaults={
        'description': '回忆渡口学徒', 'duration': 4, 'metadata': {'asset_variant_ids': {str(hero.id): variants[2].id}}})
    if created:
        await scene.assets.add(hero)
        shot = _shot(1, '@{林舟}站在渡口回忆旧船票。').model_copy(update={'description': scene.description})
        scene.prompt = format_storyboard_prompt(shot, entities=await PromptEditService._entities(scene))
        scene.prompt_params = {**shot.model_dump(mode='json'), 'prompt_contract_version': 2}
        await scene.save(update_fields=['prompt', 'prompt_params'])
    return hero, variants, tenth, scene
