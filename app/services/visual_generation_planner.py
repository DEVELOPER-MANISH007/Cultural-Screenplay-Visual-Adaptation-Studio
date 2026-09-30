"""Create stable, pending visual generation requests from validated Phase 7 specs."""
from __future__ import annotations

import hashlib
import json

from app.models.adaptation import AdaptationPlan
from app.models.adapted_screenplay import AdaptedScreenplay
from app.models.cultural_evidence import CulturalEvidence
from app.models.project_state import ProjectState
from app.models.visual_generation import (
    VisualAssetType, VisualBatchStatus, VisualGenerationBatch,
    VisualGenerationRequest, VisualGenerationStatus,
)
from app.models.visual_pack import VisualProductionPack


def deterministic_prompt_hash(*, project_id: str, asset_type: VisualAssetType,
                              source_entity_id: str, scene_id: str | None, prompt: str,
                              negative_prompt: str, evidence_ids: list[str],
                              visual_spec_version: int,
                              expected_character_ids: list[str] | None = None,
                              expected_costume_ids: list[str] | None = None,
                              expected_scene_ids: list[str] | None = None) -> str:
    payload = {
        "project_id": project_id, "asset_type": asset_type.value,
        "source_entity_id": source_entity_id, "scene_id": scene_id,
        "prompt": prompt, "negative_prompt": negative_prompt,
        "evidence_ids": evidence_ids, "visual_spec_version": visual_spec_version,
        "expected_character_ids": expected_character_ids or [],
        "expected_costume_ids": expected_costume_ids or [],
        "expected_scene_ids": expected_scene_ids or [],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _request_id(project_id: str, asset_type: VisualAssetType, entity_id: str, scene_id: str | None) -> str:
    key = f"{project_id}|{asset_type.value}|{entity_id}|{scene_id or ''}"
    return "VREQ_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20].upper()


def _prompt_for_character(bible) -> str:
    fields = {
        "character_id": bible.character_id, "canonical_name": bible.canonical_name,
        "age_description": bible.age_description, "role": bible.role,
        "face_identity": bible.face_identity, "body_description": bible.body_description,
        "hair": bible.hair, "grooming": bible.grooming,
        "baseline_wardrobe": bible.baseline_wardrobe, "accessories": bible.accessories,
        "cultural_markers": bible.cultural_markers,
        "personality_visual_cues": bible.personality_visual_cues,
        "expression_baseline": bible.expression_baseline,
        "continuity_notes": bible.continuity_notes,
    }
    return "Character visual bible (use only listed values; null means unknown):\n" + json.dumps(fields, ensure_ascii=False, sort_keys=True, indent=2)


def _prompt_for_costume(bible) -> str:
    fields = bible.model_dump(mode="json")
    fields.pop("warnings", None)
    fields.pop("continuity_notes", None)
    return "Costume visual bible (use only listed values; null/empty means unspecified):\n" + json.dumps(fields, ensure_ascii=False, sort_keys=True, indent=2)


def create_visual_generation_batch(
    visual_pack: VisualProductionPack,
    project_state: ProjectState,
    adapted_screenplay: AdaptedScreenplay,
    adaptation_plan: AdaptationPlan,
    *, provider: str = "mock",
    cultural_evidence: list[CulturalEvidence] | None = None,
) -> VisualGenerationBatch:
    """Plan requests without invoking a provider; every request starts pending."""
    for artifact in (adapted_screenplay, adaptation_plan):
        if artifact.project_id != project_state.project_id:
            raise ValueError(f"{type(artifact).__name__} project_id does not match ProjectState")
    if visual_pack.project_id != project_state.project_id:
        raise ValueError("VisualProductionPack project_id does not match ProjectState")
    if visual_pack.culture != adaptation_plan.culture or visual_pack.region != adaptation_plan.region:
        raise ValueError("VisualProductionPack context does not match the persisted AdaptationPlan")
    if adapted_screenplay.plan_id != adaptation_plan.plan_id or adapted_screenplay.plan_version != adaptation_plan.version:
        raise ValueError("AdaptedScreenplay does not match the persisted AdaptationPlan version")
    approved_change_ids = {change.change_id for change in adaptation_plan.changes if change.status.value == "approved"}
    if not set(adapted_screenplay.applied_change_ids).issubset(approved_change_ids):
        raise ValueError("AdaptedScreenplay contains changes not approved by the supplied AdaptationPlan")

    skipped: list[str] = []
    if not visual_pack.validation_result.valid:
        skipped.append("VisualProductionPack validation is not valid; no requests were created. Validate/fix Phase 7 specifications first.")
        return _batch(visual_pack, [], skipped)
    if cultural_evidence is not None:
        from app.services.visual_continuity_validator import validate_visual_pack
        recheck = validate_visual_pack(project_state, visual_pack, adapted_screenplay, adaptation_plan, cultural_evidence)
        if not recheck.valid:
            skipped.append("Current evidence/specification validation failed; no generation requests were created.")
            skipped.extend(recheck.errors)
            skipped.extend(recheck.missing_references)
            skipped.extend(recheck.unsupported_cultural_details)
            return _batch(visual_pack, [], list(dict.fromkeys(skipped)))

    state_characters = {item.character_id: item for item in project_state.characters}
    state_scenes = {item.scene_id: item for item in project_state.scenes}
    state_props = {item.element_id: item for item in project_state.production_elements}
    location_by_scene: dict[str, str] = {}
    for location in project_state.locations:
        for scene_id in location.scenes:
            location_by_scene.setdefault(scene_id, location.canonical_name)
    requests: list[VisualGenerationRequest] = []

    def add(asset_type: VisualAssetType, entity_id: str, scene_id: str | None,
            prompt: str, negative_prompt: str, evidence_ids: list[str], *,
            expected_character_ids: list[str] | None = None,
            expected_costume_ids: list[str] | None = None,
            expected_scene_ids: list[str] | None = None) -> None:
        req_id = _request_id(project_state.project_id, asset_type, entity_id, scene_id)
        req_hash = deterministic_prompt_hash(
            project_id=project_state.project_id, asset_type=asset_type,
            source_entity_id=entity_id, scene_id=scene_id, prompt=prompt,
            negative_prompt=negative_prompt, evidence_ids=evidence_ids,
            visual_spec_version=visual_pack.version,
            expected_character_ids=expected_character_ids,
            expected_costume_ids=expected_costume_ids,
            expected_scene_ids=expected_scene_ids,
        )
        requests.append(VisualGenerationRequest(
            request_id=req_id, project_id=project_state.project_id, asset_type=asset_type,
            source_entity_id=entity_id, scene_id=scene_id, prompt=prompt,
            negative_prompt=negative_prompt, evidence_ids=evidence_ids.copy(),
            expected_character_ids=expected_character_ids or [],
            expected_costume_ids=expected_costume_ids or [],
            expected_scene_ids=expected_scene_ids or [],
            visual_spec_version=visual_pack.version, prompt_hash=req_hash,
            status=VisualGenerationStatus.PENDING, provider=provider,
            created_at=visual_pack.created_at,
        ))

    seen_character_ids: set[str] = set()
    for bible in visual_pack.character_bibles:
        canonical = state_characters.get(bible.character_id)
        if canonical is None or canonical.canonical_name != bible.canonical_name:
            skipped.append(f"Character spec {bible.character_id} is not canonical; no request created.")
            continue
        if bible.character_id in seen_character_ids:
            skipped.append(f"Duplicate character spec {bible.character_id} skipped.")
            continue
        seen_character_ids.add(bible.character_id)
        if bible.cultural_markers and not bible.evidence_ids:
            skipped.append(f"Character spec {bible.character_id} contains unsupported cultural markers; no request created.")
            continue
        add(VisualAssetType.CHARACTER, bible.character_id, None,
            _prompt_for_character(bible), "Preserve canonical character identity; do not invent cultural markers, text, or watermarks.", bible.evidence_ids,
            expected_character_ids=[bible.character_id], expected_scene_ids=list(canonical.scene_ids))

    costume_ids: set[str] = set()
    for bible in visual_pack.costume_bibles:
        if bible.costume_id in costume_ids:
            skipped.append(f"Duplicate costume spec {bible.costume_id} skipped.")
            continue
        costume_ids.add(bible.costume_id)
        if bible.character_id not in state_characters or any(scene_id not in state_scenes for scene_id in bible.scene_ids):
            skipped.append(f"Costume spec {bible.costume_id} has invalid canonical references; no request created.")
            continue
        has_details = bool(bible.garments or bible.fabric or bible.colors or bible.patterns or bible.jewellery
                           or bible.footwear or bible.headwear or bible.grooming_relationship or bible.cultural_details)
        if has_details and not bible.evidence_ids:
            skipped.append(f"Costume spec {bible.costume_id} contains unsupported details; no request created.")
            continue
        add(VisualAssetType.COSTUME, bible.costume_id, bible.scene_ids[0] if len(bible.scene_ids) == 1 else None,
            _prompt_for_costume(bible), "No unsupported garments, colors, materials, patterns, cultural markers, text, or watermarks.", bible.evidence_ids,
            expected_character_ids=[bible.character_id], expected_costume_ids=[bible.costume_id], expected_scene_ids=list(bible.scene_ids))

    keyframes = {frame.scene_id: frame for frame in visual_pack.scene_keyframes}
    ordered_keyframes_valid = list(keyframes) == [scene.scene_id for scene in project_state.scenes] and len(keyframes) == len(visual_pack.scene_keyframes)
    if not ordered_keyframes_valid:
        skipped.append("Keyframe list is missing, duplicated, or out of canonical scene order; invalid keyframes are skipped.")
    for scene in project_state.scenes if ordered_keyframes_valid else []:
        frame = keyframes.get(scene.scene_id)
        if frame is None:
            continue
        if (frame.scene_number != scene.scene_number or frame.character_visual_refs != scene.character_ids
                or frame.characters_present != scene.character_ids or frame.location != (scene.location or location_by_scene.get(scene.scene_id))
                or frame.time_of_day != scene.time_of_day or frame.weather != scene.weather or frame.mood != scene.mood):
            skipped.append(f"Keyframe {scene.scene_id} does not match canonical scene references; no request created.")
            continue
        if any(costume_id not in costume_ids for costume_id in frame.costume_visual_refs):
            skipped.append(f"Keyframe {scene.scene_id} references an invalid costume; no request created.")
            continue
        expected_props = [state_props[prop_id].name for prop_id in scene.production_element_ids if prop_id in state_props]
        if frame.props != expected_props:
            skipped.append(f"Keyframe {scene.scene_id} props do not match canonical production elements; no request created.")
            continue
        if frame.cultural_details and not frame.evidence_ids:
            skipped.append(f"Keyframe {scene.scene_id} contains unsupported cultural details; no request created.")
            continue
        # The Phase 7 generation specification is passed verbatim to the provider.
        add(VisualAssetType.SCENE_KEYFRAME, scene.scene_id, scene.scene_id,
            frame.generation_prompt, frame.negative_prompt, frame.evidence_ids,
            expected_character_ids=list(frame.character_visual_refs),
            expected_costume_ids=list(frame.costume_visual_refs), expected_scene_ids=[frame.scene_id])

    return _batch(visual_pack, requests, skipped)


def _batch(pack: VisualProductionPack, requests: list[VisualGenerationRequest], warnings: list[str]) -> VisualGenerationBatch:
    batch_source = "|".join([pack.project_id, str(pack.version), *(f"{r.request_id}:{r.prompt_hash}" for r in requests)])
    batch_id = "VBATCH_" + hashlib.sha256(batch_source.encode("utf-8")).hexdigest()[:20].upper()
    return VisualGenerationBatch(
        batch_id=batch_id, project_id=pack.project_id, requests=requests, artifacts=[],
        status=VisualBatchStatus.PENDING, created_at=pack.created_at,
        updated_at=pack.updated_at, version=1, warnings=warnings,
    )


def reconcile_generation_batch(previous: VisualGenerationBatch | None,
                               current: VisualGenerationBatch) -> VisualGenerationBatch:
    """Retain unchanged approvals; invalidate approval and artifacts when a spec hash changes."""
    if previous is None or previous.project_id != current.project_id:
        return current
    previous_by_id = {item.request_id: item for item in previous.requests}
    requests: list[VisualGenerationRequest] = []
    changed_ids: set[str] = set()
    for fresh in current.requests:
        old = previous_by_id.get(fresh.request_id)
        if old is None:
            requests.append(fresh)
        elif old.prompt_hash == fresh.prompt_hash and old.provider == fresh.provider:
            requests.append(fresh.model_copy(update={"status": old.status, "created_at": old.created_at, "warnings": old.warnings.copy()}))
        else:
            changed_ids.add(fresh.request_id)
            requests.append(fresh.model_copy(update={
                "status": VisualGenerationStatus.NEEDS_REVIEW,
                "warnings": [*fresh.warnings, "Prompt/specification changed; previous approval and artifact are stale. Review and approve again."],
            }))
    warnings = list(current.warnings)
    if changed_ids:
        warnings.append(f"Prompt integrity invalidated prior decisions for {len(changed_ids)} request(s).")
    kept_artifacts = [item for item in previous.artifacts if item.request_id not in changed_ids]
    return current.model_copy(update={
        "requests": requests, "artifacts": kept_artifacts,
        "continuity_result": previous.continuity_result,
        "warnings": warnings,
        "version": previous.version + 1,
    })
