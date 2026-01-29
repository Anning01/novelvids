"""Base extractor interface and common types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ExtractedEntity:
    """Represents an extracted entity from text."""

    name: str
    entity_type: str  # "person", "scene", "item"
    description: str = ""
    base_traits: str = ""  # English traits for prompt generation
    aliases: list[str] = field(default_factory=list)
    appearances: list[dict] = field(default_factory=list)  # [{"line": 10, "context": "..."}]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "entity_type": self.entity_type,
            "description": self.description,
            "base_traits": self.base_traits,
            "aliases": self.aliases,
            "appearances": self.appearances,
        }


@dataclass
class ExtractionResult:
    """Result of extraction from a chapter."""

    chapter_number: int
    persons: list[ExtractedEntity] = field(default_factory=list)
    scenes: list[ExtractedEntity] = field(default_factory=list)
    items: list[ExtractedEntity] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chapter_number": self.chapter_number,
            "persons": [p.to_dict() for p in self.persons],
            "scenes": [s.to_dict() for s in self.scenes],
            "items": [i.to_dict() for i in self.items],
        }


class LLMClientProtocol(Protocol):
    """Protocol for LLM client used by extractors."""

    async def complete(self, prompt: str, system: str | None = None) -> str:
        """Send prompt to LLM and get response."""
        ...


class BaseExtractor(ABC):
    """Base class for entity extractors."""

    def __init__(self, llm_client: LLMClientProtocol):
        self.llm_client = llm_client

    @property
    @abstractmethod
    def entity_type(self) -> str:
        """Return the type of entity this extractor handles."""
        pass

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt for extraction."""
        pass

    @abstractmethod
    def build_extraction_prompt(self, text: str, chapter_number: int) -> str:
        """Build the extraction prompt for the given text."""
        pass

    @abstractmethod
    def parse_response(self, response: str, chapter_number: int) -> list[ExtractedEntity]:
        """Parse LLM response into extracted entities."""
        pass

    async def extract(self, text: str, chapter_number: int) -> list[ExtractedEntity]:
        """Extract entities from text.

        Args:
            text: The chapter text to extract from
            chapter_number: The chapter number

        Returns:
            List of extracted entities
        """
        prompt = self.build_extraction_prompt(text, chapter_number)
        response = await self.llm_client.complete(prompt, system=self.system_prompt)
        return self.parse_response(response, chapter_number)
