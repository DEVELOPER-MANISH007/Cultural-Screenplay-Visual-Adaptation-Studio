"""Conservative canonicalization of Phase 2 entities into persistent project state."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from app.models.extraction import Character, Location, ProductionElement, ScreenplayExtraction
from app.models.project_state import ProjectState, ProjectStateStatus
from app.services.canonical_registry import CanonicalRegistry


def normalize_name(value: str) -> str:
    """Normalize only case, whitespace, and surrounding punctuation for comparison."""
    return re.sub(r"\s+", " ", value).strip().strip(" .,").casefold()


def _stable_id(prefix: str, index: int) -> str:
    return f"{prefix}_{index:03d}"


def build_project_state(
    extraction: ScreenplayExtraction,
    *,
    title: str = "Untitled Screenplay",
    project_id: str | None = None,
    source_filename: str | None = None,
    culture: str | None = None,
    dialect: str | None = None,
    region: str | None = None,
    setting: str | None = None,
    script: str | None = None,
) -> ProjectState:
    """Convert a Phase 2 extraction without culturally enriching or dropping data."""
    project_id = project_id or uuid4().hex
    warnings: list[str] = []
    scene_map = {scene.scene_id: _stable_id("SCENE", i) for i, scene in enumerate(extraction.scenes, 1)}
    scenes = []
    for scene in extraction.scenes:
        data = scene.model_dump()
        data["scene_id"] = scene_map[scene.scene_id]
        scenes.append(data)

    char_registry = CanonicalRegistry(Character, id_field="character_id", name_field="canonical_name", aliases_field="aliases", scene_field="scene_ids")
    character_id_map: dict[str, str] = {}
    for character in extraction.characters:
        data = character.model_dump()
        data["character_id"] = _stable_id("CHAR", len(char_registry.list_entities()) + 1)
        data["scene_ids"] = [scene_map[x] for x in character.scene_ids if x in scene_map]
        for field in ("entrance_scene_id", "exit_scene_id"):
            data[field] = scene_map.get(data[field]) if data[field] else None
        normalized_character = char_registry.add_entity(char_registry.entity_type.model_validate(data))
        character_id_map[character.character_id] = normalized_character.character_id
    for scene_data, original_scene in zip(scenes, extraction.scenes):
        refs = [character_id_map[x] for x in original_scene.character_ids if x in character_id_map]
        scene_data["character_ids"] = list(dict.fromkeys(refs))
        for char_id in refs:
            char = char_registry.get_entity(char_id)
            if scene_data["scene_id"] not in char.scene_ids:
                char_registry.update_entity(char_id, {"scene_ids": char.scene_ids + [scene_data["scene_id"]]})
            if char.entrance_scene_id is None:
                char_registry.update_entity(char_id, {"entrance_scene_id": scene_data["scene_id"]})
    warnings.extend(char_registry.warnings)

    location_registry = CanonicalRegistry(Location, id_field="location_id", name_field="canonical_name", aliases_field="aliases", scene_field="scenes")
    location_map: dict[str, str] = {}
    for location in extraction.locations:
        data = location.model_dump()
        data["location_id"] = _stable_id("LOC", len(location_registry.list_entities()) + 1)
        data["scenes"] = [scene_map[x] for x in location.scenes if x in scene_map]
        entity = location_registry.add_entity(Location.model_validate(data))
        location_map[location.location_id] = entity.location_id
    # Include explicit scene-heading locations that a provider did not emit as records.
    for scene in extraction.scenes:
        if scene.location and normalize_name(scene.location):
            matches = location_registry.find_candidates(scene.location)
            if matches and matches[0][2]:
                location = matches[0][0]
                if scene_map[scene.scene_id] not in location.scenes:
                    location_registry.update_entity(location.location_id, {"scenes": location.scenes + [scene_map[scene.scene_id]]})
            else:
                if matches:
                    warnings.append(f"Location reference {scene.location!r} may match an existing different location; kept separate.")
                new_data = {"location_id": _stable_id("LOC", len(location_registry.list_entities()) + 1),
                            "canonical_name": scene.location, "aliases": [], "type": None,
                            "description": None, "scenes": [scene_map[scene.scene_id]]}
                location_registry.add_entity(Location.model_validate(new_data))
    warnings.extend(location_registry.warnings)

    element_registry = CanonicalRegistry(ProductionElement, id_field="element_id", name_field="name", aliases_field=None, scene_field="scenes", category_field="category")
    element_map: dict[str, str] = {}
    prefix_counts: dict[str, int] = {}
    def prefix_for(category: str) -> str:
        normalized = category.casefold()
        return {"prop": "PROP", "costume": "COSTUME"}.get(normalized, "ELEM")
    for element in extraction.production_elements:
        data = element.model_dump()
        prefix = prefix_for(element.category)
        prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
        data["element_id"] = _stable_id(prefix, prefix_counts[prefix])
        data["scenes"] = [scene_map[x] for x in element.scenes if x in scene_map]
        entity = element_registry.add_entity(ProductionElement.model_validate(data))
        element_map[element.element_id] = entity.element_id
    for scene_data, original_scene in zip(scenes, extraction.scenes):
        scene_data["production_element_ids"] = list(dict.fromkeys(
            element_map[x] for x in original_scene.production_element_ids if x in element_map
        ))
    warnings.extend(element_registry.warnings)

    continuities = []
    for state in extraction.continuity_states:
        data = state.model_dump()
        data["scene_id"] = scene_map[state.scene_id]
        continuities.append(data)
    return ProjectState(
        project_id=project_id, screenplay_id=extraction.screenplay_id, title=title.strip() or "Untitled Screenplay",
        source_filename=source_filename, culture=culture, dialect=dialect, region=region, setting=setting, script=script,
        scenes=scenes, characters=char_registry.list_entities(), locations=location_registry.list_entities(),
        production_elements=element_registry.list_entities(), continuity_states=continuities,
        version=1, updated_at=datetime.now(timezone.utc).isoformat(), state_status=ProjectStateStatus.EXTRACTED,
        normalization_warnings=warnings,
    )
