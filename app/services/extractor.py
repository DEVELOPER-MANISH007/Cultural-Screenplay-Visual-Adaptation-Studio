"""Phase 2 structured extraction orchestration."""
from __future__ import annotations

from app.models.extraction import ScreenplayExtraction
from app.models.screenplay import ExtractionStatus, ScreenplayDocument

EXTRACTION_PROMPT = '''You are a screenplay structure extraction system.
Extract only information supported by the screenplay. Do not invent characters, locations,
relationships, ages, props, cultural facts, motivations, or events. If information is absent,
use null/empty values. Preserve scene order. Identify repeated entities and normalize them
into canonical records when supported by the text. Return only structured data matching the
provided schema. Extract scene boundaries, scene headings, characters, production elements,
and continuity/state observations. Do not culturally adapt or rewrite the screenplay.'''


def extract_screenplay(screenplay: ScreenplayDocument, llm_provider) -> ScreenplayExtraction:
    if screenplay.extraction_status == ExtractionStatus.FAILED or not screenplay.raw_text.strip():
        raise ValueError("ScreenplayDocument must contain successfully extracted raw_text")
    raw = llm_provider.generate_structured(prompt=EXTRACTION_PROMPT, schema=ScreenplayExtraction, screenplay=screenplay)
    if isinstance(raw, ScreenplayExtraction):
        payload = raw.model_dump()
    elif isinstance(raw, dict):
        payload = dict(raw)
    else:
        raise TypeError("provider must return a mapping or ScreenplayExtraction")
    payload["screenplay_id"] = screenplay.document_id
    warnings = list(payload.get("extraction_warnings") or [])
    # Stable IDs derived from order/name, ensuring provider IDs do not collide; references are remapped.
    scene_map = {}
    for i, scene in enumerate(payload.get("scenes", []), 1):
        old = scene.get("scene_id") or f"scene-{i}"
        new = f"SCENE_{i:03d}"
        scene_map[old] = new
        scene["scene_id"] = new
        scene.setdefault("scene_number", i)
    char_map = {}
    for i, character in enumerate(payload.get("characters", []), 1):
        old = character.get("character_id") or f"character-{i}"
        new = f"CHAR_{i:03d}"
        char_map[old] = new
        character["character_id"] = new
        for field in ("entrance_scene_id", "exit_scene_id"):
            if character.get(field) in scene_map: character[field] = scene_map[character[field]]
        character["scene_ids"] = [scene_map.get(x, x) for x in character.get("scene_ids", [])]
    elem_map = {}
    category_counts = {}
    for i, element in enumerate(payload.get("production_elements", []), 1):
        old = element.get("element_id") or f"element-{i}"
        prefix = "PROP" if element.get("category", "").upper() == "PROP" else "ELEM"
        category_counts[prefix] = category_counts.get(prefix, 0) + 1
        elem_map[old] = f"{prefix}_{category_counts[prefix]:03d}"
        element["element_id"] = elem_map[old]
    for scene in payload.get("scenes", []):
        scene["character_ids"] = [char_map.get(x, x) for x in scene.get("character_ids", [])]
        scene["production_element_ids"] = [elem_map.get(x, x) for x in scene.get("production_element_ids", [])]
    for i, location in enumerate(payload.get("locations", []), 1):
        location["location_id"] = f"LOC_{i:03d}"
    category_counts = {}
    for element in payload.get("production_elements", []):
        element["scenes"] = [scene_map.get(x, x) for x in element.get("scenes", [])]
        category = element.get("category", "element").upper()
        prefix = "PROP" if category == "PROP" else "ELEM"
        category_counts[prefix] = category_counts.get(prefix, 0) + 1
        element["element_id"] = f"{prefix}_{category_counts[prefix]:03d}"
    for location in payload.get("locations", []): location["scenes"] = [scene_map.get(x, x) for x in location.get("scenes", [])]
    for state in payload.get("continuity_states", []): state["scene_id"] = scene_map.get(state["scene_id"], state["scene_id"])
    for character in payload.get("characters", []):
        character["scene_ids"] = list(dict.fromkeys(character.get("scene_ids", [])))
    payload["extraction_warnings"] = warnings
    return ScreenplayExtraction.model_validate(payload)
