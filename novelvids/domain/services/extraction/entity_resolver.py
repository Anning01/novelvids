"""Entity resolver using Union-Find algorithm for identifying same entities."""

from collections import defaultdict
from dataclasses import dataclass, field

from novelvids.domain.services.extraction.base import ExtractedEntity


class UnionFind:
    """Union-Find (Disjoint Set Union) data structure for connected components."""

    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        """Find the root of the set containing x with path compression."""
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: str, y: str) -> None:
        """Unite the sets containing x and y using union by rank."""
        px, py = self.find(x), self.find(y)
        if px == py:
            return

        # Union by rank
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1

    def connected(self, x: str, y: str) -> bool:
        """Check if x and y are in the same set."""
        return self.find(x) == self.find(y)

    def get_components(self) -> dict[str, set[str]]:
        """Get all connected components as {root: {members}}."""
        components: dict[str, set[str]] = defaultdict(set)
        for x in self.parent:
            root = self.find(x)
            components[root].add(x)
        return dict(components)


@dataclass
class ResolvedEntity:
    """An entity after resolution with merged information."""

    canonical_name: str
    entity_type: str
    aliases: set[str] = field(default_factory=set)
    description: str = ""
    base_traits: str = ""
    source_chapters: set[int] = field(default_factory=set)
    appearances: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "canonical_name": self.canonical_name,
            "entity_type": self.entity_type,
            "aliases": list(self.aliases),
            "description": self.description,
            "base_traits": self.base_traits,
            "source_chapters": sorted(self.source_chapters),
            "appearances": self.appearances,
        }


class EntityResolver:
    """Resolves and merges entities using Union-Find algorithm.

    This class handles:
    1. Identifying same entities across different chapters
    2. Merging aliases and information
    3. Tracking entity appearances across chapters

    The algorithm uses:
    - Union-Find for efficient connected component tracking
    - Name similarity for initial matching
    - Alias-based merging
    """

    def __init__(self):
        self.uf = UnionFind()
        self.entities: dict[str, ResolvedEntity] = {}  # canonical_name -> ResolvedEntity
        self.name_to_canonical: dict[str, str] = {}  # any name -> canonical_name

    def _normalize_name(self, name: str) -> str:
        """Normalize a name for comparison."""
        return name.strip().lower()

    def _find_existing_entity(
        self, name: str, aliases: list[str], entity_type: str
    ) -> str | None:
        """Find if an entity already exists by name or alias.

        Returns:
            The canonical name if found, None otherwise.
        """
        # Check the name itself
        normalized = self._normalize_name(name)
        if normalized in self.name_to_canonical:
            return self.name_to_canonical[normalized]

        # Check aliases
        for alias in aliases:
            normalized_alias = self._normalize_name(alias)
            if normalized_alias in self.name_to_canonical:
                return self.name_to_canonical[normalized_alias]

        return None

    def add_entity(
        self,
        entity: ExtractedEntity,
        chapter_number: int,
    ) -> str:
        """Add an entity and resolve it with existing entities.

        Args:
            entity: The extracted entity to add
            chapter_number: The chapter where this entity was found

        Returns:
            The canonical name of the resolved entity
        """
        all_names = [entity.name, *entity.aliases]

        # Try to find existing entity
        existing = self._find_existing_entity(entity.name, entity.aliases, entity.entity_type)

        if existing:
            # Merge with existing entity
            resolved = self.entities[existing]
            resolved.aliases.add(entity.name)
            resolved.aliases.update(entity.aliases)
            resolved.aliases.discard(resolved.canonical_name)
            resolved.source_chapters.add(chapter_number)
            resolved.appearances.extend(entity.appearances)

            # Update description and traits if better
            if entity.description and len(entity.description) > len(resolved.description):
                resolved.description = entity.description
            if entity.base_traits and len(entity.base_traits) > len(resolved.base_traits):
                resolved.base_traits = entity.base_traits

            # Register all names to this canonical name
            for name in all_names:
                normalized = self._normalize_name(name)
                self.name_to_canonical[normalized] = existing
                self.uf.union(existing, normalized)

            return existing

        # Create new entity
        canonical_name = entity.name
        resolved = ResolvedEntity(
            canonical_name=canonical_name,
            entity_type=entity.entity_type,
            aliases=set(entity.aliases),
            description=entity.description,
            base_traits=entity.base_traits,
            source_chapters={chapter_number},
            appearances=entity.appearances.copy(),
        )
        self.entities[canonical_name] = resolved

        # Register all names
        for name in all_names:
            normalized = self._normalize_name(name)
            self.name_to_canonical[normalized] = canonical_name
            self.uf.union(canonical_name, normalized)

        return canonical_name

    def merge_entities(self, name1: str, name2: str) -> str | None:
        """Manually merge two entities.

        Args:
            name1: First entity name
            name2: Second entity name

        Returns:
            The canonical name of the merged entity, or None if either doesn't exist
        """
        normalized1 = self._normalize_name(name1)
        normalized2 = self._normalize_name(name2)

        canonical1 = self.name_to_canonical.get(normalized1)
        canonical2 = self.name_to_canonical.get(normalized2)

        if not canonical1 or not canonical2:
            return None

        if canonical1 == canonical2:
            return canonical1

        # Merge into the one with more information
        entity1 = self.entities[canonical1]
        entity2 = self.entities[canonical2]

        # Keep the one with more chapters as primary
        if len(entity2.source_chapters) > len(entity1.source_chapters):
            canonical1, canonical2 = canonical2, canonical1
            entity1, entity2 = entity2, entity1

        # Merge entity2 into entity1
        entity1.aliases.add(canonical2)
        entity1.aliases.update(entity2.aliases)
        entity1.aliases.discard(entity1.canonical_name)
        entity1.source_chapters.update(entity2.source_chapters)
        entity1.appearances.extend(entity2.appearances)

        if entity2.description and len(entity2.description) > len(entity1.description):
            entity1.description = entity2.description
        if entity2.base_traits and len(entity2.base_traits) > len(entity1.base_traits):
            entity1.base_traits = entity2.base_traits

        # Update all references
        for name in entity2.aliases | {canonical2}:
            normalized = self._normalize_name(name)
            self.name_to_canonical[normalized] = canonical1
            self.uf.union(canonical1, normalized)

        # Remove old entity
        del self.entities[canonical2]

        return canonical1

    def get_entity(self, name: str) -> ResolvedEntity | None:
        """Get a resolved entity by any of its names."""
        normalized = self._normalize_name(name)
        canonical = self.name_to_canonical.get(normalized)
        if canonical:
            return self.entities.get(canonical)
        return None

    def get_all_entities(self, entity_type: str | None = None) -> list[ResolvedEntity]:
        """Get all resolved entities, optionally filtered by type."""
        entities = list(self.entities.values())
        if entity_type:
            entities = [e for e in entities if e.entity_type == entity_type]
        return entities

    def get_global_entities(self, min_chapters: int = 2) -> list[ResolvedEntity]:
        """Get entities that appear in multiple chapters (global entities)."""
        return [e for e in self.entities.values() if len(e.source_chapters) >= min_chapters]

    def get_chapter_entities(self, chapter_number: int) -> list[ResolvedEntity]:
        """Get entities that appear in a specific chapter."""
        return [e for e in self.entities.values() if chapter_number in e.source_chapters]
