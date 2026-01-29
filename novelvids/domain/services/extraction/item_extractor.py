"""Item/Object extractor."""

import json
import re

from novelvids.domain.services.extraction.base import BaseExtractor, ExtractedEntity
from novelvids.domain.services.extraction.prompts import (
    ITEM_EXTRACTION_PROMPT,
    ITEM_SYSTEM_PROMPT,
)


class ItemExtractor(BaseExtractor):
    """Extracts item/object entities from text."""

    @property
    def entity_type(self) -> str:
        return "item"

    @property
    def system_prompt(self) -> str:
        return ITEM_SYSTEM_PROMPT

    def build_extraction_prompt(self, text: str, chapter_number: int) -> str:
        return ITEM_EXTRACTION_PROMPT.format(
            chapter_number=chapter_number,
            text=text[:8000],
        )

    def parse_response(self, response: str, chapter_number: int) -> list[ExtractedEntity]:
        """Parse LLM response into ExtractedEntity objects."""
        entities = []

        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                return entities

        try:
            data = json.loads(json_str)
            items = data.get("items", [])

            for item in items:
                entity = ExtractedEntity(
                    name=item.get("name", ""),
                    entity_type="item",
                    description=item.get("description", ""),
                    base_traits=item.get("base_traits", ""),
                    aliases=item.get("aliases", []),
                    appearances=item.get("appearances", []),
                )
                if entity.name:
                    entities.append(entity)

        except json.JSONDecodeError:
            pass

        return entities
