"""Scene/Location extractor."""

import json
import re

from novelvids.domain.services.extraction.base import BaseExtractor, ExtractedEntity
from novelvids.domain.services.extraction.prompts import (
    SCENE_EXTRACTION_PROMPT,
    SCENE_SYSTEM_PROMPT,
)


class SceneExtractor(BaseExtractor):
    """Extracts scene/location entities from text."""

    @property
    def entity_type(self) -> str:
        return "scene"

    @property
    def system_prompt(self) -> str:
        return SCENE_SYSTEM_PROMPT

    def build_extraction_prompt(self, text: str, chapter_number: int) -> str:
        return SCENE_EXTRACTION_PROMPT.format(
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
            scenes = data.get("scenes", [])

            for scene in scenes:
                entity = ExtractedEntity(
                    name=scene.get("name", ""),
                    entity_type="scene",
                    description=scene.get("description", ""),
                    base_traits=scene.get("base_traits", ""),
                    aliases=scene.get("aliases", []),
                    appearances=scene.get("appearances", []),
                )
                if entity.name:
                    entities.append(entity)

        except json.JSONDecodeError:
            pass

        return entities
