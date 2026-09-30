"""Cross-check visual specifications against canonical project and approved evidence."""
from __future__ import annotations

from collections import Counter

from app.models.adaptation import AdaptationPlan
from app.models.adapted_screenplay import AdaptedScreenplay
from app.models.cultural_evidence import CulturalEvidence
from app.models.project_state import ProjectState
from app.models.visual_pack import VisualProductionPack, VisualValidationResult


EVIDENCE_CATEGORIES = {
    "costume": {"clothing", "textiles"}, "grooming": {"grooming", "clothing"},
    "jewellery": {"jewellery", "clothing"}, "architecture": {"architecture"},
    "interior": {"interiors", "architecture", "textiles"}, "props": {"props", "textiles"},
    "transport": {"transport"}, "landscape": {"landscape"}, "music": {"music"},
    "sound": {"soundscape", "music"}, "ritual": {"rituals"}, "gesture": {"gestures"},
    "social_behavior": {"social_behavior", "greetings", "gestures", "kinship"},
}


def validate_visual_pack(
    project_state: ProjectState,
    pack: VisualProductionPack,
    adapted_screenplay: AdaptedScreenplay,
    adaptation_plan: AdaptationPlan,
    cultural_evidence: list[CulturalEvidence],
) -> VisualValidationResult:
    """Validate references, continuity and evidence linkage without changing any input."""
    errors: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    unsupported: list[str] = []
    scene_by_id = {scene.scene_id: scene for scene in project_state.scenes}
    character_by_id = {character.character_id: character for character in project_state.characters}
    prop_by_id = {element.element_id: element for element in project_state.production_elements}
    evidence_by_id = {item.evidence_id: item for item in cultural_evidence}
    change_by_id = {change.change_id: change for change in adaptation_plan.changes}
    approved_applied = set(adapted_screenplay.applied_change_ids) & {
        change.change_id for change in adaptation_plan.changes if change.status.value == "approved"
    }

    if pack.project_id != project_state.project_id:
        errors.append("Visual pack project_id does not match ProjectState.")
    if adapted_screenplay.project_id != project_state.project_id:
        errors.append("Adapted screenplay project_id does not match ProjectState.")
    if adaptation_plan.project_id != project_state.project_id:
        errors.append("Adaptation plan project_id does not match ProjectState.")

    character_ids = [item.character_id for item in pack.character_bibles]
    duplicates = sorted(key for key, count in Counter(character_ids).items() if count > 1)
    if duplicates:
        errors.append(f"Duplicate character bibles: {duplicates}.")
    for character_id, character in character_by_id.items():
        matches = [item for item in pack.character_bibles if item.character_id == character_id]
        if not matches:
            errors.append(f"Missing character bible for canonical character {character_id}.")
        elif any(item.canonical_name != character.canonical_name for item in matches):
            errors.append(f"Character bible identity conflicts with canonical name for {character_id}.")
    for bible in pack.character_bibles:
        if bible.character_id not in character_by_id:
            missing.append(f"Character bible references unknown character {bible.character_id}.")
        if bible.age_description and character_by_id.get(bible.character_id) and character_by_id[bible.character_id].age:
            if bible.age_description != character_by_id[bible.character_id].age:
                errors.append(f"Character age conflicts with ProjectState for {bible.character_id}.")
        if not bible.hair or not bible.grooming or not bible.baseline_wardrobe:
            warnings.append(f"Character appearance remains partially unspecified for {bible.character_id}; retain a consistent neutral baseline.")
        if bible.cultural_markers and not bible.evidence_ids:
            unsupported.append(f"Character bible {bible.character_id} has cultural markers without evidence.")
        for change_id in bible.applied_change_ids:
            change = change_by_id.get(change_id)
            if change_id not in approved_applied or change is None:
                errors.append(f"Character bible {bible.character_id} references unapproved change {change_id}.")
            elif change.target_type != "character" or change.target_id != bible.character_id:
                errors.append(f"Character bible {bible.character_id} references a change for a different target.")
            elif not set(change.evidence_ids).issubset(set(bible.evidence_ids)):
                errors.append(f"Character bible {bible.character_id} loses evidence IDs from change {change_id}.")

    costume_ids = [item.costume_id for item in pack.costume_bibles]
    if len(costume_ids) != len(set(costume_ids)):
        errors.append("Duplicate costume IDs are present.")
    variant_values: dict[tuple[str, str], tuple] = {}
    for costume in pack.costume_bibles:
        if costume.character_id not in character_by_id:
            missing.append(f"Costume {costume.costume_id} references unknown character {costume.character_id}.")
        for scene_id in costume.scene_ids:
            if scene_id not in scene_by_id:
                missing.append(f"Costume {costume.costume_id} references unknown scene {scene_id}.")
        variant_key = (costume.character_id, costume.variant_name)
        attrs = (tuple(costume.garments), costume.fabric, tuple(costume.colors), tuple(costume.patterns),
                 tuple(costume.jewellery), costume.footwear, costume.headwear, costume.grooming_relationship,
                 tuple(costume.cultural_details))
        if variant_key in variant_values and variant_values[variant_key] != attrs:
            errors.append(f"Costume variant {costume.variant_name} has contradictory attributes for {costume.character_id}.")
        variant_values[variant_key] = attrs
        specified_costume_details = bool(
            costume.garments or costume.fabric or costume.colors or costume.patterns or costume.jewellery
            or costume.footwear or costume.headwear or costume.grooming_relationship or costume.cultural_details
        )
        if specified_costume_details and not costume.evidence_ids:
            unsupported.append(f"Costume {costume.costume_id} has visual/cultural details without evidence IDs.")
        for change_id in costume.applied_change_ids:
            change = change_by_id.get(change_id)
            if change_id not in approved_applied or change is None:
                errors.append(f"Costume {costume.costume_id} references unapproved change {change_id}.")
            elif change.target_type != "character" or change.target_id != costume.character_id:
                errors.append(f"Costume {costume.costume_id} references a change for a different character.")
            elif change.scene_id not in costume.scene_ids:
                errors.append(f"Costume {costume.costume_id} omits the scene for approved change {change_id}.")
            elif not set(change.evidence_ids).issubset(set(costume.evidence_ids)):
                errors.append(f"Costume {costume.costume_id} loses evidence IDs from change {change_id}.")
        for evidence_id in costume.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence and evidence.category.casefold() not in {"clothing", "textiles", "grooming", "jewellery"}:
                unsupported.append(f"Costume {costume.costume_id} cites incompatible evidence {evidence_id} ({evidence.category}).")
        if not costume.cultural_details:
            warnings.extend(costume.warnings)

    scene_ids = [item.scene_id for item in pack.scene_keyframes]
    expected_scene_ids = [item.scene_id for item in project_state.scenes]
    if scene_ids != expected_scene_ids:
        errors.append("Scene keyframes must include every canonical scene exactly once and preserve scene order.")
    counts = Counter(scene_ids)
    for scene_id, count in counts.items():
        if count > 1:
            errors.append(f"Scene {scene_id} has {count} keyframes; expected exactly one.")

    costume_by_id = {item.costume_id: item for item in pack.costume_bibles}
    for keyframe in pack.scene_keyframes:
        scene = scene_by_id.get(keyframe.scene_id)
        if scene is None:
            missing.append(f"Keyframe references unknown scene {keyframe.scene_id}.")
            continue
        if keyframe.scene_number != scene.scene_number:
            errors.append(f"Scene number mismatch for {scene.scene_id}.")
        expected_location = scene.location or next((location.canonical_name for location in project_state.locations if scene.scene_id in location.scenes), None)
        if keyframe.location != expected_location:
            errors.append(f"Location mismatch for {scene.scene_id}.")
        if keyframe.time_of_day != scene.time_of_day:
            errors.append(f"Time-of-day mismatch for {scene.scene_id}.")
        if keyframe.weather != scene.weather:
            errors.append(f"Weather mismatch for {scene.scene_id}.")
        if keyframe.mood != scene.mood:
            errors.append(f"Mood mismatch for {scene.scene_id}.")
        if keyframe.character_visual_refs != keyframe.characters_present:
            errors.append(f"Character visual references do not match listed characters in {scene.scene_id}.")
        for character_id in keyframe.character_visual_refs:
            if character_id not in character_by_id:
                missing.append(f"Keyframe {scene.scene_id} references unknown character {character_id}.")
            elif character_id not in scene.character_ids:
                errors.append(f"Character {character_id} is not present in canonical scene {scene.scene_id}.")
        for costume_id in keyframe.costume_visual_refs:
            costume = costume_by_id.get(costume_id)
            if costume is None:
                missing.append(f"Keyframe {scene.scene_id} references unknown costume {costume_id}.")
            elif costume.character_id not in scene.character_ids or scene.scene_id not in costume.scene_ids:
                errors.append(f"Costume {costume_id} does not belong to a character/scene in {scene.scene_id}.")
        expected_props = [prop_by_id[prop_id].name for prop_id in scene.production_element_ids if prop_id in prop_by_id]
        if keyframe.props != expected_props:
            errors.append(f"Props do not match canonical production elements in {scene.scene_id}.")
        from app.services.visual_pack_generator import _generation_spec
        expected_prompt = _generation_spec(
            scene.scene_number, scene.summary,
            [character_by_id[cid] for cid in keyframe.character_visual_refs if cid in character_by_id],
            expected_location, scene.time_of_day, scene.weather, scene.mood, expected_props,
            keyframe.cultural_details,
        )
        if keyframe.generation_prompt != expected_prompt:
            unsupported.append(f"Generation prompt for {scene.scene_id} differs from its supported structured fields.")

        # Cultural details may only cite resolved, in-scope evidence and an approved applied plan item.
        if keyframe.cultural_details and not keyframe.evidence_ids:
            unsupported.append(f"Keyframe {scene.scene_id} contains cultural details without evidence IDs.")
        if (keyframe.architecture or keyframe.environment) and not keyframe.evidence_ids:
            unsupported.append(f"Keyframe {scene.scene_id} contains architecture/environment details without evidence IDs.")
        for evidence_id in keyframe.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                missing.append(f"Keyframe {scene.scene_id} references missing evidence {evidence_id}.")
            elif evidence.scope == "Rajasthan-general":
                warnings.append(f"Keyframe {scene.scene_id} cites Rajasthan-general evidence {evidence_id}; do not treat it as Marwar-specific.")
        for change_id in keyframe.applied_change_ids:
            if change_id not in approved_applied or change_id not in change_by_id:
                errors.append(f"Keyframe {scene.scene_id} uses unapproved adaptation {change_id}.")
            else:
                change = change_by_id[change_id]
                if change.scene_id != scene.scene_id:
                    errors.append(f"Approved adaptation {change_id} is attached to the wrong keyframe.")
                if not set(change.evidence_ids).issubset(set(keyframe.evidence_ids)):
                    errors.append(f"Keyframe {scene.scene_id} loses evidence references from approved change {change_id}.")
                expected_categories = EVIDENCE_CATEGORIES.get(change.category.value, set())
                if not expected_categories:
                    errors.append(f"Non-visual change {change_id} appears as a keyframe cultural detail.")
                for evidence_id in change.evidence_ids:
                    evidence = evidence_by_id.get(evidence_id)
                    if evidence and evidence.category.casefold() not in expected_categories:
                        unsupported.append(f"Keyframe {scene.scene_id} uses incompatible evidence {evidence_id} for {change.category.value}.")
        if keyframe.cultural_details and not keyframe.applied_change_ids:
            unsupported.append(f"Keyframe {scene.scene_id} has cultural details not traceable to an approved adaptation.")
        for change_id in keyframe.applied_change_ids:
            if change_id not in keyframe.generation_prompt:
                errors.append(f"Generation prompt for {scene.scene_id} omits approved change reference {change_id}.")

        if adapted_screenplay.applied_change_ids:
            missing_from_plan = set(adapted_screenplay.applied_change_ids) - set(change_by_id)
            if missing_from_plan:
                errors.append(f"Adapted screenplay references unknown change IDs: {sorted(missing_from_plan)}.")

    # Every evidence ID anywhere in the pack must resolve; claim IDs remain traceable at item level.
    all_items = [*pack.character_bibles, *pack.costume_bibles, *pack.scene_keyframes]
    linked_claims = 0
    for item in all_items:
        has_claim = bool(getattr(item, "cultural_markers", []) or getattr(item, "cultural_details", []))
        ids = item.evidence_ids
        if has_claim and not ids:
            unsupported.append(f"{type(item).__name__} {getattr(item, 'character_id', getattr(item, 'scene_id', getattr(item, 'costume_id', '?')))} has cultural claims without evidence.")
        if has_claim and ids:
            linked_claims += 1
        for evidence_id in ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                missing.append(f"{type(item).__name__} references missing evidence {evidence_id}.")
            elif evidence.scope == "Rajasthan-general":
                warnings.append(f"Evidence {evidence_id} is Rajasthan-general, not Marwar-specific.")
            if evidence and evidence.scope != "Rajasthan-general" and evidence.region:
                if pack.region.casefold() not in evidence.region.casefold() and evidence.region.casefold() not in pack.region.casefold():
                    warnings.append(f"Evidence {evidence_id} has scope {evidence.region!r}, which is broader/different than selected region {pack.region!r}; keep the scope explicit.")
        for warning in getattr(item, "warnings", []):
            if "Rajasthan-general" in warning or "Rajasthan general" in warning:
                warnings.append(warning)
    if unsupported:
        warnings.extend(unsupported)
    # Preserve useful diagnostics without repetitive duplicate messages.
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    missing = list(dict.fromkeys(missing))
    unsupported = list(dict.fromkeys(unsupported))
    return VisualValidationResult(
        valid=not errors and not missing and not unsupported,
        errors=errors, warnings=warnings, missing_references=missing,
        unsupported_cultural_details=unsupported, character_count=len(pack.character_bibles),
        costume_count=len(pack.costume_bibles), scene_keyframe_count=len(pack.scene_keyframes),
        evidence_linked_claim_count=linked_claims,
    )
