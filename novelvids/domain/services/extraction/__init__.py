"""Extraction services for extracting entities from novel text.

This module provides:
- PersonExtractor: Extract person/character entities
- SceneExtractor: Extract scene/location entities
- ItemExtractor: Extract item/object entities
- EntityResolver: Resolve and merge entities using union-find algorithm
"""

from novelvids.domain.services.extraction.base import BaseExtractor, ExtractionResult
from novelvids.domain.services.extraction.entity_resolver import EntityResolver, UnionFind
from novelvids.domain.services.extraction.item_extractor import ItemExtractor
from novelvids.domain.services.extraction.person_extractor import PersonExtractor
from novelvids.domain.services.extraction.scene_extractor import SceneExtractor

__all__ = [
    "BaseExtractor",
    "ExtractionResult",
    "PersonExtractor",
    "SceneExtractor",
    "ItemExtractor",
    "EntityResolver",
    "UnionFind",
]
