"""Read a typed chapter asset inventory independently of visual design generation."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from prompts.extraction import render_cast_instructions
from services.creation_agent.plan_sources import plan_activity
from utils.enums import AssetTypeEnum
from utils.messages import localized_message

INVENTORY_FIELDS = (('characters', AssetTypeEnum.person.value), ('scenes', AssetTypeEnum.scene.value),
                    ('items', AssetTypeEnum.item.value))


class ChapterPresence(BaseModel):
    name: str = Field(min_length=1)
    presence: Literal['present', 'flashback', 'mentioned', 'voice_only']
    quote: str = Field(min_length=1, description='Exact source passage supporting this identity and presence')
    existing_asset_id: int | None = None


class ChapterCast(BaseModel):
    characters: list[ChapterPresence]
    scenes: list[ChapterPresence] = Field(default_factory=list)
    items: list[ChapterPresence] = Field(default_factory=list)

    def required_names(self):
        return list(dict.fromkeys(item.name for item in self.characters if item.presence in {'present', 'flashback'}))

    def required_assets(self) -> list[tuple[int, str]]:
        return list(dict.fromkeys((kind, item.name) for field, kind in INVENTORY_FIELDS for item in getattr(self, field)
            if item.presence in {'present', 'flashback'}))


def validate_cast(cast: ChapterCast, content: str, registry: list[dict]):
    known = {asset['id']: asset for asset in registry}
    for kind, item in ((kind, item) for field, kind in INVENTORY_FIELDS for item in getattr(cast, field)):
        if not item.name.strip() or not item.quote.strip() or item.quote not in content:
            raise ValueError('Asset presence must include an exact passage from this chapter')
        if item.existing_asset_id is not None:
            asset = known.get(item.existing_asset_id)
            if asset is None or item.name not in [asset['canonical_name'], *(asset.get('aliases') or [])]:
                raise ValueError('Use an existing asset ID and its registered name, or null for a new asset')
        else:
            category = [asset for asset in registry if asset.get('asset_type', 1) == kind]
            matches = [asset for asset in category if item.name == asset['canonical_name']]
            if not matches:
                matches = [asset for asset in category if item.name in (asset.get('aliases') or [])]
            if len(matches) > 1:
                raise ValueError('The asset name matches multiple identities in this category; disambiguate using the chapter')
            asset = matches[0] if matches else None
        if asset:
            if asset.get('asset_type', 1) != kind:
                raise ValueError('Use the registered asset category: characters, scenes or items; do not turn a prop into a person')
            item.name, item.existing_asset_id = asset['canonical_name'], asset['id']


def rebind_cast(cast: ChapterCast, content: str, registry: list[dict]) -> ChapterCast:
    # The source inventory is stable; saved asset IDs can change after a deletion or rename.
    cast = cast.model_copy(deep=True)
    known = {asset['id']: asset for asset in registry}
    for field, kind in INVENTORY_FIELDS:
        for item in getattr(cast, field):
            asset = known.get(item.existing_asset_id)
            if asset and asset.get('asset_type', 1) == kind:
                item.name = asset['canonical_name']
            else:
                item.existing_asset_id = None
    validate_cast(cast, content, registry)
    return cast


async def read_chapter_cast(execution, messages, *, target_requirements=None) -> ChapterCast:
    chapter = json.loads(messages[3]['content'])
    registry = [{key: asset.get(key) for key in ('id', 'asset_type', 'canonical_name', 'aliases')}
                for asset in json.loads(messages[2]['content'])]
    async def validate(cast):
        validate_cast(cast, chapter['content'], registry)

    # Old character-only inventories cannot safely classify panels, props or locations.
    segment = cast_segment(chapter, execution.language, execution.snapshot.revision)
    instructions = render_cast_instructions(execution.language)
    if target_requirements is not None:
        from prompts.extraction import targeted_cast_instructions
        from services.creation_agent.plan_sources import fingerprint
        segment += ':targeted:' + fingerprint(target_requirements)
        instructions += '\n' + targeted_cast_instructions(execution.language)
    await plan_activity(execution, 'chapter-cast', localized_message('正在清点本章角色、场景与道具'))
    from models.agent_operation import AgentOperation
    saved = await AgentOperation.filter(key=f'model:structured:ChapterCast:{segment}', state='completed').order_by('-id').first()
    if saved:
        cast = ChapterCast.model_validate(saved.result)
        try:
            cast = rebind_cast(cast, chapter['content'], registry)
        except ValueError:
            saved = None
    if not saved:
        cast = await execution.generate('structured', {'segment': segment, 'chapter': chapter, 'known_assets': registry,
            **({'target_requirements': target_requirements} if target_requirements is not None else {})},
            ChapterCast, additional_instructions=instructions, output_validator=validate)
    await validate(cast)
    await AgentOperation.get_or_create(task_id=execution.params['task_id'], key=f'model:structured:ChapterCast:{segment}',
        defaults={'state': 'completed', 'result': cast.model_dump(mode='json')})
    await plan_activity(execution, 'chapter-cast', localized_message('已核对本章资产清单'), status='completed',
        detail=str(len(cast.required_assets())))
    return cast


def cast_segment(chapter: dict, language: str, revision: str) -> str:
    source = json.dumps([chapter, language, revision], ensure_ascii=False, sort_keys=True)
    return f"chapter-cast:v2:{chapter['id']}:{hashlib.sha256(source.encode()).hexdigest()}"
