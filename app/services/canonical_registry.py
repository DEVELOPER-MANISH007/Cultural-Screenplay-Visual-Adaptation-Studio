"""Small typed registries for canonical characters, locations, and production entities."""
from __future__ import annotations

from copy import deepcopy
from typing import TypeVar

from pydantic import BaseModel

from app.models.extraction import Character, Location, ProductionElement

T = TypeVar("T", bound=BaseModel)


class CanonicalRegistry:
    """Registry for one Pydantic entity type; uncertain candidates are never merged."""

    def __init__(self, entity_type: type[T], *, id_field: str, name_field: str, aliases_field: str | None, scene_field: str, category_field: str | None = None):
        self.entity_type = entity_type
        self.id_field = id_field
        self.name_field = name_field
        self.aliases_field = aliases_field
        self.scene_field = scene_field
        self.category_field = category_field
        self._entities: dict[str, T] = {}
        self.warnings: list[str] = []

    def add_entity(self, entity: T) -> T:
        entity_id = getattr(entity, self.id_field)
        if entity_id in self._entities:
            raise ValueError(f"entity ID already exists: {entity_id}")
        candidates = self.find_candidates(getattr(entity, self.name_field), entity=entity)
        for existing, reason, certain in candidates:
            if certain:
                return self.merge_entities(getattr(existing, self.id_field), entity, confirmed=True)
            self.warnings.append(f"Possible duplicate kept separate: {getattr(existing, self.name_field)!r} / {getattr(entity, self.name_field)!r} ({reason}).")
        self._entities[entity_id] = entity
        return entity

    def get_entity(self, entity_id: str) -> T:
        return self._entities[entity_id]

    def find_candidates(self, name: str, *, entity: T | None = None) -> list[tuple[T, str, bool]]:
        from app.services.normalizer import normalize_name
        key = normalize_name(name)
        results = []
        for existing in self._entities.values():
            if self.category_field and entity is not None and getattr(existing, self.category_field) != getattr(entity, self.category_field):
                continue
            names = [getattr(existing, self.name_field)]
            if self.aliases_field:
                names += list(getattr(existing, self.aliases_field) or [])
            for existing_name in names:
                normalized = normalize_name(existing_name)
                if key and key == normalized:
                    results.append((existing, "same name after case/whitespace normalization", True))
                    break
                if key and normalized and (key in normalized or normalized in key):
                    results.append((existing, "one name contains the other; identity is uncertain", False))
                    break
        return results

    def merge_entities(self, target_id: str, duplicate: T | str, *, confirmed: bool = False) -> T:
        from app.services.normalizer import normalize_name
        if not confirmed:
            raise ValueError("merge requires explicit confirmation; uncertain entities stay separate")
        target = self._entities[target_id]
        other = self._entities[duplicate] if isinstance(duplicate, str) else duplicate
        target_data = target.model_dump()
        other_data = other.model_dump()
        if self.aliases_field:
            aliases = list(target_data.get(self.aliases_field) or [])
            other_name = other_data[self.name_field]
            if other_name != target_data[self.name_field]:
                aliases.append(other_name)
            aliases.extend(other_data.get(self.aliases_field) or [])
            target_data[self.aliases_field] = list(dict.fromkeys(x for x in aliases if x != target_data[self.name_field]))
        target_data[self.scene_field] = list(dict.fromkeys(
            list(target_data.get(self.scene_field) or []) + list(other_data.get(self.scene_field) or [])
        ))
        # Preserve supported metadata: fill absent values and union collection fields;
        # retain conflicting scalars on the canonical entity and record a warning.
        for field, value in other_data.items():
            if field in {self.id_field, self.name_field, self.aliases_field, self.scene_field}:
                continue
            current = target_data.get(field)
            if current in (None, "", [], {}):
                target_data[field] = deepcopy(value)
            elif isinstance(current, list) and isinstance(value, list):
                target_data[field] = list(dict.fromkeys(current + value))
            elif isinstance(current, dict) and isinstance(value, dict):
                merged = dict(value)
                for key in current.keys() & value.keys():
                    if current[key] != value[key]:
                        self.warnings.append(f"Conflicting {field}[{key!r}] values while merging {target_id}; canonical value retained.")
                merged.update(current)
                target_data[field] = merged
            elif value not in (None, "", [], {}) and value != current:
                self.warnings.append(f"Conflicting {field} values while merging {target_id}; canonical value retained.")
        merged_entity = self.entity_type.model_validate(target_data)
        self._entities[target_id] = merged_entity
        other_id = other_data[self.id_field]
        if other_id != target_id:
            self._entities.pop(other_id, None)
        return merged_entity

    def update_entity(self, entity_id: str, updates: dict) -> T:
        current = self._entities[entity_id].model_dump()
        current.update(updates)
        updated = self.entity_type.model_validate(current)
        if getattr(updated, self.id_field) != entity_id:
            raise ValueError("canonical IDs cannot be changed by update_entity")
        self._entities[entity_id] = updated
        return updated

    def list_entities(self) -> list[T]:
        return list(self._entities.values())


class CharacterRegistry(CanonicalRegistry):
    def __init__(self):
        super().__init__(Character, id_field="character_id", name_field="canonical_name", aliases_field="aliases", scene_field="scene_ids")


class LocationRegistry(CanonicalRegistry):
    def __init__(self):
        super().__init__(Location, id_field="location_id", name_field="canonical_name", aliases_field="aliases", scene_field="scenes")


class ProductionElementRegistry(CanonicalRegistry):
    def __init__(self):
        super().__init__(ProductionElement, id_field="element_id", name_field="name", aliases_field=None, scene_field="scenes", category_field="category")
