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


async def read_chapter_cast(execution, messages) -> ChapterCast:
    chapter = json.loads(messages[3]['content'])
    registry = [{key: asset.get(key) for key in ('id', 'asset_type', 'canonical_name', 'aliases')}
                for asset in json.loads(messages[2]['content'])]
    async def validate(cast):
        validate_cast(cast, chapter['content'], registry)

    # Old character-only inventories cannot safely classify panels, props or locations.
    source = json.dumps([chapter, execution.language, execution.snapshot.revision], ensure_ascii=False, sort_keys=True)
    segment = f"chapter-cast:v2:{chapter['id']}:{hashlib.sha256(source.encode()).hexdigest()}"
    await plan_activity(execution, 'chapter-cast', localized_message('正在清点本章角色、场景与道具'))
    from models.agent_operation import AgentOperation
    saved = await AgentOperation.get_or_none(task_id=execution.params['task_id'],
        key=f'model:structured:ChapterCast:{segment}', state='completed')
    if saved:
        cast = ChapterCast.model_validate(saved.result)
    else:
        cast = await execution.generate('structured', {'segment': segment, 'chapter': chapter, 'known_assets': registry},
            ChapterCast, additional_instructions=render_cast_instructions(execution.language), output_validator=validate)
    await validate(cast)
    await plan_activity(execution, 'chapter-cast', localized_message('已核对本章资产清单'), status='completed',
        detail=str(len(cast.required_assets())))
    return cast
