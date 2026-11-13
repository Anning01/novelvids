"""Resolve current project standards and prepare validated prompts before persistence."""

import json

from models.asset import Asset
from models.asset_variant import AssetVariant
from services.language import generation_language
from models.novel import Novel
from prompts.creation_standards import ASSET_PROMPT_KINDS, visual_contract
from prompts.reference import CHARACTER_TURNAROUND, GROUP_PORTRAIT
from prompts.styles import image_project_style_suffix, video_project_style_suffix
from services.storyboard.strategies import storyboard_strategy_factory


class CreationPromptStandards:
    def __init__(self, novel_id: int):
        self.novel_id = novel_id

    async def context(self) -> dict:
        project = await Novel.get(id=self.novel_id)
        return {'language': await generation_language(),
                'aspect_ratio': project.aspect_ratio or '16:9',
                'strategy': storyboard_strategy_factory.resolve(project.storyboard_strategy)}

    async def contract(self, kind: str, layout: str = CHARACTER_TURNAROUND) -> dict:
        from services.creation_agent.skill_execution import current_execution
        execution = current_execution.get()
        if execution:
            options = await self.context()
            project = await Novel.get(id=self.novel_id)
            skill = 'storyboard' if kind == 'storyboard' else 'image'
            contract_kind = 'group' if kind == 'person' and layout == GROUP_PORTRAIT else kind
            specification = json.loads(execution.snapshot.contents.get('asset_contract', '{}')).get(execution.language, {}).get(contract_kind)
            asset_contract = ({**specification, 'task': specification['task'].format(aspect_ratio=options['aspect_ratio'])}
                              if specification else None)
            return {'kind': kind, 'language': execution.language, 'aspect_ratio': options['aspect_ratio'],
                    'reference_layout': layout, 'required_fields': specification['fields'] if specification else [],
                    'asset_contract': asset_contract, 'revision': execution.snapshot.revision,
                    'writing_rules': execution.snapshot.read(skill) + '\n' + execution.snapshot.read('assets'),
                    'styles': execution.snapshot.read('styles'), 'strategy': project.storyboard_strategy,
                    'project_style_key': project.style_key, 'custom_style_prompt': project.custom_style_prompt}
        contract = visual_contract(kind, layout=layout, **await self.context())
        project = await Novel.get(id=self.novel_id)
        style = video_project_style_suffix if kind == 'storyboard' else image_project_style_suffix
        return {**contract, 'project_style': style(project.style_key, project.custom_style_prompt, language=contract['language'])}

    async def asset_kind(self, target) -> tuple[str, str]:
        asset = await Asset.get(id=target.asset_id, novel_id=self.novel_id) if isinstance(target, AssetVariant) else target
        metadata = {**(asset.metadata or {}), **(target.metadata or {})}
        return ASSET_PROMPT_KINDS[asset.asset_type], metadata.get('reference_layout') or CHARACTER_TURNAROUND

    async def prepare_asset(self, text: str, *, asset_type: int, layout: str = CHARACTER_TURNAROUND,
                            previous: str | None = None, local_edit: bool = False) -> str:
        from services.extraction.extractor import validate_asset_design

        validate_asset_design(text)
        return text
