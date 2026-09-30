"""Deterministic offline generator for evidence-backed visual production specs."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.models.adaptation import AdaptationCategory, AdaptationChangeStatus, AdaptationPlan
from app.models.adapted_screenplay import AdaptedScreenplay
from app.models.cultural_evidence import CulturalEvidence, CulturalEvidenceStatus
from app.models.project_state import ProjectState
from app.models.visual_pack import (
    CharacterVisualBible, CostumeVisualBible, SceneVisualKeyframe,
    VisualProductionPack, VisualValidationResult,
)


VISUAL_CATEGORIES = {
    AdaptationCategory.COSTUME: {"clothing", "textiles"},
    AdaptationCategory.GROOMING: {"grooming", "clothing"},
    AdaptationCategory.JEWELLERY: {"jewellery", "clothing"},
    AdaptationCategory.ARCHITECTURE: {"architecture"},
    AdaptationCategory.INTERIOR: {"interiors", "architecture", "textiles"},
    AdaptationCategory.PROPS: {"props", "textiles"},
    AdaptationCategory.TRANSPORT: {"transport"},
    AdaptationCategory.LANDSCAPE: {"landscape"},
    AdaptationCategory.MUSIC: {"music"},
    AdaptationCategory.SOUND: {"soundscape", "music"},
    AdaptationCategory.RITUAL: {"rituals"},
    AdaptationCategory.GESTURE: {"gestures"},
    AdaptationCategory.SOCIAL_BEHAVIOR: {"social_behavior", "greetings", "gestures", "kinship"},
}
DEFAULT_NEGATIVE = (
    "No unsupported modern clothing; no generic fantasy architecture; no invented or incorrect cultural markers; "
    "preserve the same character identity and appearance; no duplicate people; no text, captions, logos, or watermarks; "
    "avoid anachronistic objects unless explicitly present in the screenplay."
)


@dataclass(frozen=True)
class _VisualClaim:
    change_id: str
    scene_id: str
    text: str
    evidence_ids: tuple[str, ...]
    evidence_claims: tuple[str, ...]
    warnings: tuple[str, ...]
    target_character_id: str | None


class MockVisualPackGenerator:
    """Build stable visual specifications without image APIs or cultural guesswork."""

    def generate(self, project_state: ProjectState, adapted_screenplay: AdaptedScreenplay,
                 adaptation_plan: AdaptationPlan, cultural_evidence: list[CulturalEvidence]) -> VisualProductionPack:
        if adaptation_plan.project_id != project_state.project_id:
            raise ValueError("AdaptationPlan project_id does not match ProjectState")
        if adapted_screenplay.project_id != project_state.project_id:
            raise ValueError("AdaptedScreenplay project_id does not match ProjectState")
        if adapted_screenplay.plan_id != adaptation_plan.plan_id or adapted_screenplay.plan_version != adaptation_plan.version:
            raise ValueError("AdaptedScreenplay must be generated from the supplied adaptation plan version")
        evidence_by_id = {item.evidence_id: item for item in cultural_evidence}
        changes_by_id = {item.change_id: item for item in adaptation_plan.changes}
        applied = set(adapted_screenplay.applied_change_ids)
        global_warnings: list[str] = []
        claims: dict[str, _VisualClaim] = {}
        for change in adaptation_plan.changes:
            if change.status != AdaptationChangeStatus.APPROVED:
                continue
            allowed_categories = VISUAL_CATEGORIES.get(change.category, set())
            if not allowed_categories:
                continue
            if change.change_id not in applied:
                missing_ids = [eid for eid in change.evidence_ids if eid not in evidence_by_id]
                if missing_ids:
                    global_warnings.extend(f"Cultural claim {change.change_id} blocked: evidence {eid} is missing; detail was not included." for eid in missing_ids)
                elif not change.evidence_ids:
                    global_warnings.append(f"Cultural claim {change.change_id} blocked: it has no evidence and was not included.")
                else:
                    for evidence_id in change.evidence_ids:
                        if evidence_by_id[evidence_id].scope == "Rajasthan-general":
                            global_warnings.append(f"Evidence {evidence_id} is Rajasthan-general; it cannot be narrowed to {adaptation_plan.culture} / {adaptation_plan.region}.")
                    insufficient = [eid for eid in change.evidence_ids if evidence_by_id[eid].status == CulturalEvidenceStatus.INSUFFICIENT_EVIDENCE]
                    if insufficient:
                        global_warnings.extend(f"Cultural claim {change.change_id} unresolved: evidence {eid} is insufficient; detail remains unknown." for eid in insufficient)
                    else:
                        global_warnings.append(f"Approved visual claim {change.change_id} was not applied in the saved Phase 6 screenplay; it was not included.")
                continue
            claim_warnings: list[str] = []
            resolved: list[CulturalEvidence] = []
            blocked = False
            for evidence_id in change.evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    claim_warnings.append(f"Cultural claim {change.change_id} blocked: evidence {evidence_id} is missing.")
                    blocked = True
                    continue
                if evidence.status == CulturalEvidenceStatus.INSUFFICIENT_EVIDENCE:
                    claim_warnings.append(f"Cultural claim {change.change_id} unresolved: evidence {evidence_id} is insufficient.")
                    blocked = True
                    continue
                if evidence.category.casefold() not in allowed_categories:
                    claim_warnings.append(f"Cultural claim {change.change_id} blocked: evidence {evidence_id} category {evidence.category!r} does not support {change.category.value!r}.")
                    blocked = True
                    continue
                if evidence.culture.casefold() not in {adaptation_plan.culture.casefold(), "rajasthan"}:
                    claim_warnings.append(f"Cultural claim {change.change_id} blocked: evidence {evidence_id} is for culture {evidence.culture!r}.")
                    blocked = True
                    continue
                if evidence.scope == "Rajasthan-general":
                    claim_warnings.append(f"Evidence {evidence_id} is Rajasthan-general; it is not Marwar-specific and must remain labeled as general.")
                elif evidence.region and adaptation_plan.region.casefold() not in evidence.region.casefold() and evidence.region.casefold() not in adaptation_plan.region.casefold():
                    claim_warnings.append(f"Cultural claim {change.change_id} blocked: evidence {evidence_id} scope {evidence.region!r} does not match {adaptation_plan.region!r}.")
                    blocked = True
                    continue
                resolved.append(evidence)
            conflict_groups = {item.conflict_group for item in resolved if item.conflict_group}
            for group in sorted(conflict_groups):
                competing = [item for item in cultural_evidence if item.conflict_group == group]
                claim_warnings.append(
                    f"Cultural evidence conflict in {group}: preserve all cited claims for human review; do not choose one silently."
                )
                # If a conflict is known, retain every catalog claim in the record list where it is in-scope/category-compatible.
                for competing_item in competing:
                    region_matches = (
                        competing_item.scope == "Rajasthan-general" or not competing_item.region
                        or adaptation_plan.region.casefold() in competing_item.region.casefold()
                        or competing_item.region.casefold() in adaptation_plan.region.casefold()
                    )
                    culture_matches = competing_item.culture.casefold() in {adaptation_plan.culture.casefold(), "rajasthan"}
                    if (competing_item not in resolved and competing_item.category.casefold() in allowed_categories
                            and competing_item.status != CulturalEvidenceStatus.INSUFFICIENT_EVIDENCE
                            and region_matches and culture_matches):
                        resolved.append(competing_item)
            if blocked or not resolved:
                if not resolved and not claim_warnings:
                    claim_warnings.append(f"Cultural claim {change.change_id} unresolved: no supporting evidence was supplied.")
                global_warnings.extend(claim_warnings)
                continue
            claims[change.change_id] = _VisualClaim(
                change_id=change.change_id, scene_id=change.scene_id,
                text=change.proposed_change,
                evidence_ids=tuple(item.evidence_id for item in resolved),
                evidence_claims=tuple(
                    (f"Rajasthan-general (not Marwar-specific): {item.claim}" if item.scope == "Rajasthan-general" else item.claim)
                    for item in resolved
                ),
                warnings=tuple(claim_warnings),
                target_character_id=change.target_id if change.target_type == "character" else None,
            )
            global_warnings.extend(claim_warnings)

        character_bibles: list[CharacterVisualBible] = []
        for character in project_state.characters:
            character_warnings = [
                "Face, body, hair, grooming and baseline wardrobe are unspecified by the source; do not infer cultural appearance.",
            ]
            visual_change_ids = [
                change_id for change_id, claim in claims.items()
                if claim.target_character_id == character.character_id
                and changes_by_id[change_id].category in {AdaptationCategory.COSTUME, AdaptationCategory.GROOMING, AdaptationCategory.JEWELLERY}
            ]
            char_claims = [claims[cid] for cid in visual_change_ids]
            character_bibles.append(CharacterVisualBible(
                character_id=character.character_id, canonical_name=character.canonical_name,
                age_description=character.age, role=character.role,
                face_identity=None, body_description=None, hair=None, grooming=None,
                baseline_wardrobe=None, accessories=[], cultural_markers=[claim.text for claim in char_claims],
                personality_visual_cues=list(character.personality), expression_baseline=None,
                continuity_notes=[f"Use canonical identity {character.character_id} consistently in every referenced scene."],
                evidence_ids=list(dict.fromkeys(eid for claim in char_claims for eid in claim.evidence_ids)),
                applied_change_ids=visual_change_ids,
                warnings=character_warnings,
            ))

        costume_bibles: list[CostumeVisualBible] = []
        costume_by_character_scene: dict[tuple[str, str], list[str]] = {}
        for change_id, claim in claims.items():
            change = changes_by_id[change_id]
            if change.category not in {AdaptationCategory.COSTUME, AdaptationCategory.GROOMING, AdaptationCategory.JEWELLERY}:
                continue
            character_id = claim.target_character_id
            if character_id is None:
                global_warnings.append(f"Approved visual change {change_id} is scene-targeted; no character was inferred for a costume variant.")
                continue
            if character_id not in {item.character_id for item in character_bibles}:
                global_warnings.append(f"Approved visual change {change_id} references an unknown character and was omitted from costume specs.")
                continue
            digest = hashlib.sha256(f"{project_state.project_id}|{character_id}|{change_id}".encode("utf-8")).hexdigest()[:10].upper()
            costume_id = f"COSTUME_{digest}"
            costume_bibles.append(CostumeVisualBible(
                costume_id=costume_id, character_id=character_id,
                variant_name=f"approved_change_{change_id}", scene_ids=[claim.scene_id],
                garments=[], fabric=None, colors=[], patterns=[], jewellery=[], footwear=None,
                headwear=None, grooming_relationship=None,
                cultural_details=list(claim.evidence_claims), evidence_ids=list(claim.evidence_ids),
                applied_change_ids=[change_id],
                continuity_notes=["Only the cited, approved visual detail is specified; other costume attributes remain unknown."],
                warnings=list(claim.warnings),
            ))
            costume_by_character_scene.setdefault((character_id, claim.scene_id), []).append(costume_id)

        location_by_scene: dict[str, str] = {}
        for location in project_state.locations:
            for scene_id in location.scenes:
                location_by_scene.setdefault(scene_id, location.canonical_name)
        production_by_id = {item.element_id: item for item in project_state.production_elements}
        scene_by_id = {item.scene_id: item for item in project_state.scenes}
        keyframes: list[SceneVisualKeyframe] = []
        for scene in project_state.scenes:
            scene_character_ids = list(scene.character_ids)
            scene_characters = [item for item in project_state.characters if item.character_id in scene_character_ids]
            scene_claims = [claim for claim in claims.values() if claim.scene_id == scene.scene_id]
            # A character-targeted visual detail can only appear in the scene it was approved for.
            costume_refs = list(dict.fromkeys(
                costume_id for character_id in scene_character_ids
                for costume_id in costume_by_character_scene.get((character_id, scene.scene_id), [])
            ))
            cultural_details = list(dict.fromkeys(
                f"Approved change {claim.change_id}: {claim.text} Evidence: {'; '.join(claim.evidence_claims)}"
                for claim in scene_claims
            ))
            evidence_ids = list(dict.fromkeys(eid for claim in scene_claims for eid in claim.evidence_ids))
            warnings = [
                "Architecture and environmental specifics are unspecified; use only location and environment stated in the screenplay.",
                "Lighting, composition and camera framing are unspecified; do not add culture-specific assumptions.",
            ]
            for claim in scene_claims:
                warnings.extend(claim.warnings)
            props = [production_by_id[element_id].name for element_id in scene.production_element_ids if element_id in production_by_id]
            scene_location = scene.location or location_by_scene.get(scene.scene_id)
            keyframes.append(SceneVisualKeyframe(
                scene_id=scene.scene_id, scene_number=scene.scene_number, location=scene_location,
                time_of_day=scene.time_of_day, weather=scene.weather, mood=scene.mood,
                characters_present=scene_character_ids, character_visual_refs=scene_character_ids.copy(),
                costume_visual_refs=costume_refs, props=props, architecture=None,
                environment=None, lighting=None, composition=None, camera_framing=None,
                atmosphere=None, cultural_details=cultural_details,
                generation_prompt=_generation_spec(
                    scene.scene_number, scene.summary, scene_characters, scene_location,
                    scene.time_of_day, scene.weather, scene.mood, props, cultural_details,
                ),
                negative_prompt=DEFAULT_NEGATIVE, evidence_ids=evidence_ids,
                applied_change_ids=[claim.change_id for claim in scene_claims], warnings=list(dict.fromkeys(warnings)),
            ))

        pack = VisualProductionPack(
            project_id=project_state.project_id, culture=adaptation_plan.culture,
            dialect=adaptation_plan.dialect, region=adaptation_plan.region,
            setting=adaptation_plan.setting, script=adaptation_plan.script,
            character_bibles=character_bibles, costume_bibles=costume_bibles,
            scene_keyframes=keyframes, continuity_warnings=list(dict.fromkeys(global_warnings)),
            validation_result=VisualValidationResult(),
            created_at=adapted_screenplay.created_at, updated_at=adapted_screenplay.updated_at, version=1,
        )
        from app.services.visual_continuity_validator import validate_visual_pack
        result = validate_visual_pack(project_state, pack, adapted_screenplay, adaptation_plan, cultural_evidence)
        pack.validation_result = result
        pack.continuity_warnings = list(dict.fromkeys([*pack.continuity_warnings, *result.warnings]))
        return pack


def _generation_spec(scene_number: int, summary: str, characters, location: str | None,
                     time_of_day: str | None, weather: str | None, mood: str | None,
                     props: list[str], cultural_details: list[str]) -> str:
    """Emit a labeled provider-ready prompt with explicit unknowns instead of guesses."""
    return "\n".join([
        f"Subject: Screenplay scene {scene_number}: {summary or 'unspecified scene action'}",
        "Characters: " + (", ".join(f"{item.canonical_name} ({item.character_id})" for item in characters) if characters else "none specified"),
        "Appearance: follow the character bibles; unspecified traits remain unknown",
        "Costume: follow referenced approved costume variants only; otherwise unspecified",
        f"Location: {location or 'unspecified'}",
        "Architecture: unspecified",
        "Environment: " + (weather or "unspecified") + "; other environmental details unspecified",
        "Props: " + (", ".join(props) if props else "none specified"),
        "Lighting: unspecified",
        "Camera framing: unspecified",
        "Composition: unspecified",
        f"Mood: {mood or 'unspecified'}",
        "Time: " + (time_of_day or "unspecified"),
        "Cultural visual details (approved and evidence-linked): " + (" | ".join(cultural_details) if cultural_details else "none specified"),
    ])
