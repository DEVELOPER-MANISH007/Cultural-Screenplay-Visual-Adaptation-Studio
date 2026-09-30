"""End-to-end structural and provenance checks for Phase 9 packaging."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.models.adaptation import AdaptationPlan
from app.models.adapted_screenplay import AdaptedScreenplay
from app.models.continuity_report import ContinuityReport, FinalValidationResult
from app.models.cultural_evidence import CulturalEvidence, CulturalSource
from app.models.project_state import ProjectState
from app.models.visual_generation import VisualGenerationBatch
from app.models.visual_pack import VisualProductionPack
from app.services.generated_visual_validator import validate_generated_visuals
from app.services.visual_continuity_validator import validate_visual_pack


def validate_final_project(
    *, project_state: ProjectState | None, source_screenplay=None,
    adaptation_plan: AdaptationPlan | None, adapted_screenplay: AdaptedScreenplay | None,
    visual_pack: VisualProductionPack | None, generation_batch: VisualGenerationBatch | None,
    cultural_evidence: list[CulturalEvidence] | None = None,
    cultural_sources: list[CulturalSource] | None = None,
) -> FinalValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    unresolved: list[str] = []
    checked: list[str] = []
    evidence_issues: list[str] = []
    adaptation_issues: list[str] = []
    now = datetime.now(timezone.utc).isoformat()
    evidence = cultural_evidence or []
    sources = cultural_sources or []
    if project_state is None:
        errors.append("ProjectState is missing.")
    else:
        checked.append("ProjectState and canonical IDs")
        if not project_state.project_id or not project_state.screenplay_id:
            errors.append("ProjectState lacks a project or source screenplay ID.")
    if source_screenplay is None:
        errors.append("Original screenplay source is missing; provide its Phase 1 document or raw text.")
    else:
        checked.append("Original screenplay source")
    if project_state and source_screenplay is not None:
        doc_id = getattr(source_screenplay, "document_id", None)
        raw = getattr(source_screenplay, "raw_text", source_screenplay if isinstance(source_screenplay, str) else None)
        if doc_id and doc_id != project_state.screenplay_id:
            errors.append("Phase 1 screenplay ID does not match ProjectState.screenplay_id.")
        if raw is None:
            errors.append("Original screenplay source has no raw text.")
        elif adapted_screenplay and raw != adapted_screenplay.original_screenplay_text:
            errors.append("Adapted screenplay does not preserve the original screenplay text exactly.")

    evidence_by_id = {item.evidence_id: item for item in evidence}
    source_ids = {item.source_id for item in sources}
    if len(evidence_by_id) != len(evidence):
        errors.append("Cultural evidence contains duplicate evidence IDs.")
    if len(source_ids) != len(sources):
        errors.append("Cultural sources contain duplicate source IDs.")
    conflict_groups: dict[str, list[CulturalEvidence]] = {}
    for item in evidence:
        if item.source_id not in source_ids:
            evidence_issues.append(f"Evidence {item.evidence_id} has unresolved source {item.source_id}.")
            errors.append(evidence_issues[-1])
        evidence_status = getattr(item.status, "value", item.status)
        if evidence_status != "verified":
            unresolved.append(f"Evidence {item.evidence_id} is {evidence_status}: {item.claim}")
        if item.scope == "Rajasthan-general":
            warnings.append(f"Evidence {item.evidence_id} is Rajasthan-general, not Marwar-specific.")
        if item.conflict_group:
            conflict_groups.setdefault(item.conflict_group, []).append(item)
    for group in conflict_groups.values():
        if len({item.claim for item in group}) > 1:
            warnings.append("Cultural evidence conflict: " + "; ".join(
                f"{item.evidence_id} ({item.source_title}) claims {item.claim!r}"
                for item in sorted(group, key=lambda record: record.evidence_id)
            ))

    if adaptation_plan is None:
        errors.append("Persisted adaptation plan is missing.")
    else:
        checked.append("Adaptation plan and evidence links")
        if project_state and adaptation_plan.project_id != project_state.project_id:
            errors.append("Adaptation plan project ID does not match ProjectState.")
        for change in adaptation_plan.changes:
            if change.status.value == "approved":
                if not change.evidence_ids:
                    adaptation_issues.append(f"Approved change {change.change_id} has no evidence IDs.")
                for evidence_id in change.evidence_ids:
                    if evidence_id not in evidence_by_id:
                        adaptation_issues.append(f"Change {change.change_id} references missing evidence {evidence_id}.")
                    elif getattr(evidence_by_id[evidence_id].status, "value", evidence_by_id[evidence_id].status) == "insufficient_evidence":
                        adaptation_issues.append(f"Approved change {change.change_id} relies on insufficient evidence {evidence_id}.")
            if change.status.value in {"pending", "needs_review", "needs_revision", "insufficient_evidence"}:
                unresolved.append(f"Adaptation change {change.change_id} remains {change.status.value}.")
        errors.extend(adaptation_issues)
    if adapted_screenplay is None:
        errors.append("Persisted adapted screenplay is missing.")
    else:
        checked.append("Adapted screenplay scenes and approval traceability")
        if project_state and adapted_screenplay.project_id != project_state.project_id:
            errors.append("Adapted screenplay project ID does not match ProjectState.")
        if adaptation_plan and adapted_screenplay.plan_id != adaptation_plan.plan_id:
            errors.append("Adapted screenplay references a different adaptation plan.")
        if project_state:
            canonical_ids = [scene.scene_id for scene in project_state.scenes]
            adapted_ids = [scene.scene_id for scene in adapted_screenplay.scenes]
            if len(adapted_ids) != len(canonical_ids):
                errors.append("Adapted screenplay scene count differs from ProjectState.")
            if adapted_ids != canonical_ids:
                errors.append("Adapted screenplay scene order or IDs differ from ProjectState.")
        approved_ids = {change.change_id for change in adaptation_plan.changes if change.status.value == "approved"} if adaptation_plan else set()
        for change_id in adapted_screenplay.applied_change_ids:
            if change_id not in approved_ids:
                errors.append(f"Adapted screenplay applies non-approved or unknown change {change_id}.")
        if adapted_screenplay.evidence_ids:
            for evidence_id in adapted_screenplay.evidence_ids:
                if evidence_id not in evidence_by_id:
                    evidence_issues.append(f"Adapted screenplay references missing evidence {evidence_id}.")
            errors.extend(evidence_issues)
        unresolved.extend(adapted_screenplay.assumptions)
        warnings.extend(adapted_screenplay.warnings)
    if visual_pack is None:
        errors.append("Persisted VisualProductionPack is missing.")
    elif project_state and adapted_screenplay and adaptation_plan:
        checked.append("Visual bibles, keyframes, and evidence references")
        visual_result = validate_visual_pack(project_state, visual_pack, adapted_screenplay, adaptation_plan, evidence)
        errors.extend(visual_result.errors)
        errors.extend(visual_result.missing_references)
        warnings.extend(visual_result.warnings)
        unresolved.extend(visual_result.unsupported_cultural_details)
    if generation_batch is None:
        warnings.append("Visual generation batch is missing; generated visual artifacts are unavailable.")
        unresolved.append("No persisted visual generation batch is available.")
    elif project_state and visual_pack:
        checked.append("Generation approvals, request/artifact links, and prompt hashes")
        result = validate_generated_visuals(generation_batch, visual_pack, project_state)
        errors.extend(result.errors)
        warnings.extend(result.warnings)
        artifacts_by_request = {item.request_id: item for item in generation_batch.artifacts}
        for request in generation_batch.requests:
            request_status = getattr(request.status, "value", request.status)
            if request_status in {"pending", "rejected", "needs_review", "failed"} and request.request_id not in artifacts_by_request:
                unresolved.append(f"Visual request {request.request_id} is {request_status}.")
        if not any(item.image_metadata.get("mock_placeholder") for item in generation_batch.artifacts):
            warnings.append("No generated visual metadata identifies mock placeholders; verify provider provenance.")
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    unresolved = list(dict.fromkeys(unresolved))
    report = ContinuityReport(
        report_id=f"CONT_{uuid4().hex[:12]}", project_id=project_state.project_id if project_state else "unknown",
        status="passed" if not errors else "failed", checked_scenes=len(project_state.scenes) if project_state else 0,
        checked_characters=len(project_state.characters) if project_state else 0,
        checked_costumes=len(visual_pack.costume_bibles) if visual_pack else 0,
        checked_props=len(project_state.production_elements) if project_state else 0,
        checked_visual_artifacts=len(generation_batch.artifacts) if generation_batch else 0,
        errors=errors, warnings=warnings, unresolved_items=unresolved,
        evidence_traceability_issues=list(dict.fromkeys(evidence_issues)),
        adaptation_traceability_issues=list(dict.fromkeys(adaptation_issues)), generated_at=now,
    )
    return FinalValidationResult(valid=not errors, errors=errors, warnings=warnings,
                                 checked_items=checked, unresolved_items=unresolved, continuity_report=report)
