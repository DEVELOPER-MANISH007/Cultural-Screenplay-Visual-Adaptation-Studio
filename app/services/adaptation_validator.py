"""Lightweight structural and source-preservation checks for Phase 6 output."""
from __future__ import annotations

from app.models.adapted_screenplay import AdaptationValidationResult, AdaptedScreenplay
from app.models.adaptation import AdaptationChangeStatus, AdaptationPlan
from app.models.project_state import ProjectState
from app.models.cultural_evidence import CulturalEvidence


def validate_adapted_screenplay(project_state: ProjectState, adapted: AdaptedScreenplay,
                                adaptation_plan: AdaptationPlan | None = None,
                                original_text: str | None = None,
                                cultural_evidence: list[CulturalEvidence] | None = None) -> AdaptationValidationResult:
    errors: list[str] = []
    warnings = list(adapted.warnings)
    expected = project_state.scenes
    actual = adapted.scenes
    if len(expected) != len(actual):
        errors.append(f"Scene count changed: expected {len(expected)}, got {len(actual)}.")
    if adapted.project_id != project_state.project_id:
        errors.append("Adapted screenplay project_id does not match ProjectState.")
    if adapted.source_screenplay_id != project_state.screenplay_id:
        errors.append("Adapted screenplay source_screenplay_id does not match ProjectState.")
    if original_text is not None and adapted.original_screenplay_text != original_text:
        errors.append("Persisted original screenplay text differs from the supplied source text.")
    expected_ids = [scene.scene_id for scene in expected]
    actual_ids = [scene.scene_id for scene in actual]
    if actual_ids != expected_ids:
        errors.append("Scene IDs or scene order changed.")
    for index, source_scene in enumerate(expected):
        if index >= len(actual):
            break
        adapted_scene = actual[index]
        if adapted_scene.scene_id != source_scene.scene_id:
            continue
        if adapted_scene.scene_number != source_scene.scene_number:
            errors.append(f"Scene number changed for {source_scene.scene_id}.")
        if not adapted_scene.original_text:
            errors.append(f"Original text could not be aligned for {source_scene.scene_id}.")
        approved_dialogue_change = bool(adaptation_plan and any(
            change.scene_id == source_scene.scene_id
            and change.status == AdaptationChangeStatus.APPROVED
            and change.category.value in {"dialogue", "dialect"}
            and change.change_id in adapted_scene.applied_change_ids
            for change in adaptation_plan.changes
        ))
        if adapted_scene.original_text and adapted_scene.original_text not in adapted_scene.adapted_text:
            if approved_dialogue_change:
                warnings.append(f"Approved dialogue change exists in {source_scene.scene_id}; lightweight checks cannot assess semantic preservation.")
            else:
                errors.append(f"Original scene text was not preserved in {source_scene.scene_id}.")
    scene_applied = [change_id for scene in actual for change_id in scene.applied_change_ids]
    if scene_applied != adapted.applied_change_ids:
        errors.append("Top-level applied_change_ids do not match the scene-level traceability records.")
    scene_evidence = list(dict.fromkeys(evidence_id for scene in actual for evidence_id in scene.evidence_ids))
    if scene_evidence != adapted.evidence_ids:
        errors.append("Top-level evidence_ids do not match the scene-level traceability records.")
    if adaptation_plan:
        approved_changes = {c.change_id: c for c in adaptation_plan.changes if c.status == AdaptationChangeStatus.APPROVED}
        applied_ids = set(adapted.applied_change_ids)
        if missing := applied_ids - set(approved_changes):
            errors.append(f"Unapproved or unknown changes were applied: {sorted(missing)}.")
        for scene in actual:
            for change_id in scene.applied_change_ids:
                change = approved_changes.get(change_id)
                if change and change.scene_id != scene.scene_id:
                    errors.append(f"Applied change {change_id} is attached to the wrong scene.")
                if change and not set(change.evidence_ids).issubset(scene.evidence_ids):
                    errors.append(f"Evidence traceability is incomplete for {change_id}.")
    if cultural_evidence is not None:
        known_evidence = {item.evidence_id for item in cultural_evidence}
        if missing_evidence := set(adapted.evidence_ids) - known_evidence:
            errors.append(f"Adapted screenplay references missing evidence IDs: {sorted(missing_evidence)}.")
    return AdaptationValidationResult(valid=not errors, errors=errors, warnings=list(dict.fromkeys(warnings)),
                                      checked_scene_count=min(len(expected), len(actual)),
                                      applied_change_count=len(adapted.applied_change_ids))
