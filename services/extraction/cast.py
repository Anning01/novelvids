"""Read chapter cast independently of visual design generation."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from prompts.extraction import render_cast_instructions
from services.creation_agent.plan_sources import plan_activity
from utils.messages import localized_message


class ChapterCharacter(BaseModel):
    name: str = Field(min_length=1)
    presence: Literal['present', 'flashback', 'mentioned']
    quote: str = Field(min_length=1, description='Exact source passage supporting this identity and presence')
    existing_asset_id: int | None = None


class ChapterCast(BaseModel):
    characters: list[ChapterCharacter]

    def required_names(self):
        return list(dict.fromkeys(item.name for item in self.characters if item.presence != 'mentioned'))


def validate_cast(cast: ChapterCast, content: str, registry: list[dict]):
    known = {asset['id']: asset for asset in registry}
    for item in cast.characters:
        if not item.name.strip() or not item.quote.strip() or item.quote not in content:
            raise ValueError('Character presence must include an exact passage from this chapter')
        if item.existing_asset_id is not None:
            asset = known.get(item.existing_asset_id)
            if asset is None or item.name not in [asset['canonical_name'], *(asset.get('aliases') or [])]:
                raise ValueError('Use an existing character ID and its registered name, or null for a new character')
        else:
            matches = [asset for asset in registry if item.name == asset['canonical_name']]
            if not matches:
                matches = [asset for asset in registry if item.name in (asset.get('aliases') or [])]
            if len(matches) > 1:
                raise ValueError('The character name matches multiple identities; disambiguate using the chapter')
            asset = matches[0] if matches else None
        if asset:
            item.name, item.existing_asset_id = asset['canonical_name'], asset['id']


async def read_chapter_cast(execution, messages) -> ChapterCast:
    chapter = json.loads(messages[3]['content'])
    registry = [{key: asset.get(key) for key in ('id', 'canonical_name', 'aliases')}
                for asset in json.loads(messages[2]['content']) if asset['asset_type'] == 1]
    async def validate(cast):
        validate_cast(cast, chapter['content'], registry)

    segment = f"chapter-cast:{chapter['id']}:{hashlib.sha256(chapter['content'].encode()).hexdigest()}"
    await plan_activity(execution, 'chapter-cast', localized_message('正在识别本章出场角色'))
    cast = await execution.generate('structured', {'segment': segment, 'chapter': chapter, 'known_characters': registry},
        ChapterCast, additional_instructions=render_cast_instructions(execution.language), output_validator=validate)
    await validate(cast)
    await plan_activity(execution, 'chapter-cast', localized_message('已核对本章出场角色'), status='completed',
        detail=str(len(cast.required_names())))
    return cast
