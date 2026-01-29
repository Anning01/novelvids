"""Person/Character extractor."""

import json
import re

from novelvids.domain.services.extraction.base import BaseExtractor, ExtractedEntity
from novelvids.domain.services.extraction.prompts import (
    PERSON_EXTRACTION_PROMPT,
    PERSON_SYSTEM_PROMPT,
)


class PersonExtractor(BaseExtractor):
    """Extracts person/character entities from text."""

    @property
    def entity_type(self) -> str:
        return "person"

    @property
    def system_prompt(self) -> str:
        return PERSON_SYSTEM_PROMPT

    def build_extraction_prompt(self, text: str, chapter_number: int) -> str:
        return PERSON_EXTRACTION_PROMPT.format(
            chapter_number=chapter_number,
            text=text[:8000],  # Limit text length
        )

    def parse_response(self, response: str, chapter_number: int) -> list[ExtractedEntity]:
        """Parse LLM response into ExtractedEntity objects."""
        entities = []

        # Extract JSON from response
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                return entities

        try:
            data = json.loads(json_str)
            persons = data.get("persons", [])

            for person in persons:
                entity = ExtractedEntity(
                    name=person.get("name", ""),
                    entity_type="person",
                    description=person.get("description", ""),
                    base_traits=person.get("base_traits", ""),
                    aliases=person.get("aliases", []),
                    appearances=person.get("appearances", []),
                )
                if entity.name:
                    entities.append(entity)

        except json.JSONDecodeError:
            pass

        return entities
