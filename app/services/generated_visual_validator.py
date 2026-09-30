"""Validate generated artifacts against approved requests and Phase 7 specs."""
from __future__ import annotations

from app.models.project_state import ProjectState
from app.models.visual_generation import (
    VisualAssetType, VisualGenerationBatch,
    VisualGenerationRequest, VisualGenerationStatus, VisualContinuityValidationResult,
)
from app.models.visual_pack import VisualProductionPack
from app.services.visual_generation_planner import (
    _prompt_for_character, _prompt_for_costume, deterministic_prompt_hash,
)


def validate_generated_visuals(
    batch: VisualGenerationBatch,
    visual_pack: VisualProductionPack,
    project_state: ProjectState,
    *,
    current_requests: list[VisualGenerationRequest] | None = None,
) -> VisualContinuityValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    failed = sum(item.status.value == "failed" for item in batch.artifacts)
    if batch.project_id != project_state.project_id or visual_pack.project_id != project_state.project_id:
        errors.append("Generation batch, visual pack, and ProjectState must share the same project_id.")
    request_ids = [item.request_id for item in batch.requests]
    if len(request_ids) != len(set(request_ids)):
        errors.append("Generation batch contains duplicate request IDs.")
    artifact_ids = [item.artifact_id for item in batch.artifacts]
    if len(artifact_ids) != len(set(artifact_ids)):
        errors.append("Generation batch contains duplicate artifact IDs.")
    request_by_id = {item.request_id: item for item in batch.requests}
    fresh_by_id = {item.request_id: item for item in current_requests or []}
    characters = {item.character_id: item for item in project_state.characters}
    scenes = {item.scene_id: item for item in project_state.scenes}
    bibles = {item.character_id: item for item in visual_pack.character_bibles}
    costumes = {item.costume_id: item for item in visual_pack.costume_bibles}
    keyframes = {item.scene_id: item for item in visual_pack.scene_keyframes}
    scene_order: list[int] = []

    for artifact in batch.artifacts:
        request = request_by_id.get(artifact.request_id)
        if request is None:
            errors.append(f"Artifact {artifact.artifact_id} points to missing request {artifact.request_id}.")
            continue
        if artifact.project_id != batch.project_id or request.project_id != batch.project_id:
            errors.append(f"Artifact/request project ID mismatch for {artifact.artifact_id}.")
        if artifact.status.value not in {"generated", "failed", "needs_review"}:
            errors.append(f"Artifact {artifact.artifact_id} has invalid final status {artifact.status.value}.")
        if artifact.source_entity_id != request.source_entity_id or artifact.scene_id != request.scene_id or artifact.asset_type != request.asset_type:
            errors.append(f"Artifact {artifact.artifact_id} does not match its request identity.")
        if artifact.prompt_hash != request.prompt_hash:
            errors.append(f"Artifact {artifact.artifact_id} prompt hash differs from its request.")
        if artifact.provider != request.provider:
            errors.append(f"Artifact {artifact.artifact_id} provider differs from the approved request.")
        if request.status not in {VisualGenerationStatus.GENERATED, VisualGenerationStatus.FAILED, VisualGenerationStatus.NEEDS_REVIEW}:
            errors.append(f"Artifact {artifact.artifact_id} was created from a request that was not approved/generated.")
        expected_hash = deterministic_prompt_hash(
            project_id=request.project_id, asset_type=request.asset_type,
            source_entity_id=request.source_entity_id, scene_id=request.scene_id,
            prompt=request.prompt, negative_prompt=request.negative_prompt,
            evidence_ids=request.evidence_ids, visual_spec_version=request.visual_spec_version,
            expected_character_ids=request.expected_character_ids,
            expected_costume_ids=request.expected_costume_ids,
            expected_scene_ids=request.expected_scene_ids,
        )
        if request.prompt_hash != expected_hash:
            errors.append(f"Request {request.request_id} prompt/spec hash is invalid.")
        fresh = fresh_by_id.get(request.request_id)
        if fresh and fresh.prompt_hash != request.prompt_hash:
            errors.append(f"Artifact {artifact.artifact_id} was generated from a stale visual specification.")
        if artifact.status.value == "failed":
            continue

        metadata = artifact.image_metadata
        if metadata.get("source_entity_id", artifact.source_entity_id) != artifact.source_entity_id:
            errors.append(f"Artifact {artifact.artifact_id} metadata source entity is inconsistent.")
        if metadata.get("visual_spec_version", request.visual_spec_version) != request.visual_spec_version:
            errors.append(f"Artifact {artifact.artifact_id} visual specification version is inconsistent.")
        if metadata.get("evidence_ids", request.evidence_ids) != request.evidence_ids:
            errors.append(f"Artifact {artifact.artifact_id} metadata lost evidence references.")
        for field_name in ("expected_character_ids", "expected_costume_ids", "expected_scene_ids"):
            if metadata.get(field_name, getattr(request, field_name)) != getattr(request, field_name):
                errors.append(f"Artifact {artifact.artifact_id} metadata has inconsistent {field_name}.")
        if metadata.get("unexpected_identity_change") or metadata.get("identity_change"):
            errors.append(f"Artifact {artifact.artifact_id} reports unexpected identity change metadata.")

        if artifact.asset_type == VisualAssetType.CHARACTER:
            bible = bibles.get(artifact.source_entity_id)
            if bible is None or artifact.source_entity_id not in characters:
                errors.append(f"Artifact {artifact.artifact_id} references an invalid character entity.")
            else:
                canonical = characters[artifact.source_entity_id]
                if request.prompt != _prompt_for_character(bible):
                    errors.append(f"Artifact {artifact.artifact_id} character prompt differs from its visual bible.")
                if request.expected_character_ids != [canonical.character_id] or request.expected_scene_ids != canonical.scene_ids:
                    errors.append(f"Artifact {artifact.artifact_id} expected character/scene references differ from ProjectState.")
        elif artifact.asset_type == VisualAssetType.COSTUME:
            bible = costumes.get(artifact.source_entity_id)
            if bible is None:
                errors.append(f"Artifact {artifact.artifact_id} references an invalid costume entity.")
            else:
                if request.scene_id not in (bible.scene_ids if len(bible.scene_ids) == 1 else [None]):
                    errors.append(f"Artifact {artifact.artifact_id} costume scene reference is inconsistent.")
                if request.prompt != _prompt_for_costume(bible):
                    errors.append(f"Artifact {artifact.artifact_id} costume prompt differs from its visual bible.")
                if (request.expected_character_ids != [bible.character_id]
                        or request.expected_costume_ids != [bible.costume_id]
                        or request.expected_scene_ids != bible.scene_ids):
                    errors.append(f"Artifact {artifact.artifact_id} expected costume references differ from VisualProductionPack.")
        elif artifact.asset_type == VisualAssetType.SCENE_KEYFRAME:
            frame = keyframes.get(artifact.source_entity_id)
            scene = scenes.get(artifact.source_entity_id)
            if frame is None or scene is None or artifact.scene_id != scene.scene_id:
                errors.append(f"Artifact {artifact.artifact_id} references an invalid scene entity.")
            else:
                if request.prompt != frame.generation_prompt or request.negative_prompt != frame.negative_prompt:
                    errors.append(f"Artifact {artifact.artifact_id} scene prompt differs from the approved keyframe specification.")
                if request.evidence_ids != frame.evidence_ids:
                    errors.append(f"Artifact {artifact.artifact_id} scene evidence references differ from keyframe.")
                if (request.expected_character_ids != frame.character_visual_refs
                        or request.expected_costume_ids != frame.costume_visual_refs
                        or request.expected_scene_ids != [frame.scene_id]):
                    errors.append(f"Artifact {artifact.artifact_id} expected scene references differ from keyframe.")
                scene_order.append(scene.scene_number)
        if metadata.get("mock_placeholder"):
            if not metadata.get("not_a_real_image") or "placeholder" not in (metadata.get("label", "").casefold()):
                errors.append(f"Mock artifact {artifact.artifact_id} is not clearly labeled as a placeholder.")
            warnings.append("Mock artifact metadata checks do not verify facial identity or pixel-level visual similarity.")

    if scene_order != sorted(scene_order):
        errors.append("Generated scene artifacts do not preserve canonical scene order.")
    warnings = list(dict.fromkeys(warnings))
    errors = list(dict.fromkeys(errors))
    return VisualContinuityValidationResult(
        valid=not errors and failed == 0, errors=errors, warnings=warnings,
        checked_artifact_count=len(batch.artifacts), failed_artifact_count=failed,
    )
