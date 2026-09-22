"""Resolve current project standards and prepare validated prompts before persistence."""

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.config import GeneralConfig
from models.novel import Novel
from prompts.creation_standards import ASSET_PROMPT_KINDS, validate_person_visual_traits, validate_reference_kind, visual_contract
from prompts.reference import CHARACTER_TURNAROUND, is_complete_reference_prompt, render_default_asset_prompt
from prompts.styles import image_project_style_suffix, video_project_style_suffix
from services.storyboard.strategies import storyboard_strategy_factory
from utils.prompt_language import DEFAULT_PROMPT_LANGUAGE


class CreationPromptStandards:
    def __init__(self, novel_id: int):
        self.novel_id = novel_id

    async def context(self) -> dict:
        project = await Novel.get(id=self.novel_id)
        config = await GeneralConfig.first()
        return {'language': config.prompt_language if config else DEFAULT_PROMPT_LANGUAGE,
                'aspect_ratio': project.aspect_ratio or '16:9',
                'strategy': storyboard_strategy_factory.resolve(project.storyboard_strategy)}

    async def contract(self, kind: str, layout: str = CHARACTER_TURNAROUND) -> dict:
        contract = visual_contract(kind, layout=layout, **await self.context())
        project = await Novel.get(id=self.novel_id)
        style = video_project_style_suffix if kind == 'storyboard' else image_project_style_suffix
        return {**contract, 'project_style': style(project.style_key, project.custom_style_prompt)}

    async def asset_kind(self, target) -> tuple[str, str]:
        asset = await Asset.get(id=target.asset_id, novel_id=self.novel_id) if isinstance(target, AssetVariant) else target
        metadata = {**(asset.metadata or {}), **(target.metadata or {})}
        return ASSET_PROMPT_KINDS[asset.asset_type], metadata.get('reference_layout') or CHARACTER_TURNAROUND

    async def prepare_asset(self, text: str, *, asset_type: int, layout: str = CHARACTER_TURNAROUND,
                            previous: str | None = None, local_edit: bool = False) -> str:
        kind = ASSET_PROMPT_KINDS[asset_type]
        validate_reference_kind(text, kind)
        if local_edit and previous and is_complete_reference_prompt(previous) and not is_complete_reference_prompt(text):
            raise ValueError('局部修改不能删除参考图任务，请保留原有构图规范')
        if kind == 'person':
            if local_edit and previous is not None:
                try:
                    validate_person_visual_traits(previous, layout)
                except ValueError:
                    # Precise edits of old hand-written drafts remain local.
                    # Full replacements and new settings must satisfy the contract.
                    return text
            validate_person_visual_traits(text, layout)
        if local_edit:
            return text
        options = await self.context()
        rendered = render_default_asset_prompt(asset_type=kind, visual_traits=text,
            prompt_language=options['language'], aspect_ratio=options['aspect_ratio'], reference_layout=layout)
        # Existing complete prompts are editable source documents. Fixed task
        # text must not disappear when only the visual description is submitted.
        if previous and kind == 'person':
            labels = ('角色描述：', 'Character description:')
            for marker in labels:
                if marker in previous and marker not in text:
                    return previous.split(marker, 1)[0] + marker + '\n' + text.strip()
        return rendered
