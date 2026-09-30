"""Approval-gated visual generation orchestration with structured failure handling."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.models.project_state import ProjectState
from app.models.visual_generation import (
    GeneratedVisualArtifact, VisualBatchStatus, VisualGenerationBatch,
    VisualGenerationRequest, VisualGenerationStatus,
)
from app.models.visual_pack import VisualProductionPack
from app.services.generated_visual_validator import validate_generated_visuals
from app.services.image_generation_provider import ImageGenerationProvider
from app.services.visual_artifact_store import VisualArtifactStore
from app.services.visual_generation_planner import deterministic_prompt_hash


class VisualGenerationService:
    def __init__(self, provider: ImageGenerationProvider, artifact_store: VisualArtifactStore):
        self.provider = provider
        self.artifact_store = artifact_store

    def generate_approved(
        self,
        batch: VisualGenerationBatch,
        current_requests: list[VisualGenerationRequest],
        visual_pack: VisualProductionPack,
        project_state: ProjectState,
    ) -> VisualGenerationBatch:
        """Execute only still-approved requests; update requests/artifacts with safe failures."""
        if batch.project_id != project_state.project_id:
            raise ValueError("batch project_id does not match ProjectState")
        fresh_by_id = {item.request_id: item for item in current_requests}
        requests = list(batch.requests)
        artifacts = list(batch.artifacts)
        artifacts_by_request = {item.request_id: item for item in artifacts}
        for index, request in enumerate(requests):
            if request.status != VisualGenerationStatus.APPROVED:
                continue
            fresh = fresh_by_id.get(request.request_id)
            if fresh is None:
                requests[index] = request.model_copy(update={
                    "status": VisualGenerationStatus.NEEDS_REVIEW,
                    "warnings": [*request.warnings, "Approved request no longer exists in the current visual specification; approval invalidated."],
                })
                continue
            if request.provider != fresh.provider or request.provider != self.provider.name:
                requests[index] = fresh.model_copy(update={
                    "status": VisualGenerationStatus.NEEDS_REVIEW,
                    "warnings": [*fresh.warnings, "Provider selection changed after approval; previous approval invalidated. Review and approve for the selected provider."],
                })
                continue
            recomputed_hash = deterministic_prompt_hash(
                project_id=request.project_id, asset_type=request.asset_type,
                source_entity_id=request.source_entity_id, scene_id=request.scene_id,
                prompt=request.prompt, negative_prompt=request.negative_prompt,
                evidence_ids=request.evidence_ids, visual_spec_version=request.visual_spec_version,
                expected_character_ids=request.expected_character_ids,
                expected_costume_ids=request.expected_costume_ids,
                expected_scene_ids=request.expected_scene_ids,
            )
            if request.prompt_hash != recomputed_hash or request.prompt_hash != fresh.prompt_hash:
                requests[index] = fresh.model_copy(update={
                    "status": VisualGenerationStatus.NEEDS_REVIEW,
                    "warnings": [*fresh.warnings, "Prompt or visual specification changed after approval; previous approval was invalidated. Review and approve again."],
                })
                continue
            previous_artifact = artifacts_by_request.get(request.request_id)
            if previous_artifact is not None and previous_artifact.status == VisualGenerationStatus.GENERATED:
                # Idempotent retry: don't invoke a provider twice for a request with a saved artifact.
                requests[index] = request.model_copy(update={"status": VisualGenerationStatus.GENERATED})
                continue
            if previous_artifact is not None:
                artifacts = [item for item in artifacts if item.request_id != request.request_id]
            try:
                artifact = self.provider.generate(request)
                if (artifact.request_id != request.request_id or artifact.project_id != request.project_id
                        or artifact.prompt_hash != request.prompt_hash or artifact.source_entity_id != request.source_entity_id
                        or artifact.asset_type != request.asset_type):
                    raise ValueError("provider returned an artifact that does not match the approved request")
                artifact = artifact.model_copy(update={
                    "image_metadata": {
                        **artifact.image_metadata,
                        "source_entity_id": request.source_entity_id,
                        "scene_id": request.scene_id,
                        "evidence_ids": list(request.evidence_ids),
                        "visual_spec_version": request.visual_spec_version,
                        "expected_character_ids": list(request.expected_character_ids),
                        "expected_costume_ids": list(request.expected_costume_ids),
                        "expected_scene_ids": list(request.expected_scene_ids),
                        "approved_prompt_hash": request.prompt_hash,
                    },
                })
                artifact = self.artifact_store.save_artifact(artifact)
                artifacts.append(artifact)
                artifacts_by_request[request.request_id] = artifact
                requests[index] = request.model_copy(update={"status": VisualGenerationStatus.GENERATED})
            except Exception as exc:  # provider/storage failures become data, never UI-fatal exceptions
                failed = _failure_artifact(request, self.provider.name, exc)
                artifacts.append(failed)
                artifacts_by_request[request.request_id] = failed
                requests[index] = request.model_copy(update={
                    "status": VisualGenerationStatus.FAILED,
                    "warnings": [*request.warnings, f"Generation failed: {type(exc).__name__}: {exc}"],
                })

        candidate = batch.model_copy(update={
            "requests": requests, "artifacts": artifacts,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": VisualBatchStatus.IN_PROGRESS,
        })
        result = validate_generated_visuals(candidate, visual_pack, project_state, current_requests=current_requests)
        if result.errors:
            for index, artifact in enumerate(artifacts):
                if artifact.status == VisualGenerationStatus.GENERATED:
                    artifacts[index] = artifact.model_copy(update={
                        "status": VisualGenerationStatus.NEEDS_REVIEW,
                        "continuity_status": "needs_review",
                        "warnings": [*artifact.warnings, "Continuity validation requires review; no visual similarity was inferred."],
                    })
                    for request_index, request in enumerate(requests):
                        if request.request_id == artifact.request_id:
                            requests[request_index] = request.model_copy(update={"status": VisualGenerationStatus.NEEDS_REVIEW})
                            break
        else:
            for index, artifact in enumerate(artifacts):
                if artifact.status == VisualGenerationStatus.GENERATED:
                    artifacts[index] = artifact.model_copy(update={"continuity_status": "valid"})
        result = validate_generated_visuals(
            candidate.model_copy(update={"requests": requests, "artifacts": artifacts}),
            visual_pack, project_state, current_requests=current_requests,
        )
        statuses = [item.status for item in artifacts]
        if not artifacts and not any(item.status == VisualGenerationStatus.APPROVED for item in requests):
            batch_status = VisualBatchStatus.PENDING
        elif any(status in {VisualGenerationStatus.FAILED, VisualGenerationStatus.NEEDS_REVIEW} for status in statuses):
            batch_status = VisualBatchStatus.PARTIAL if any(status == VisualGenerationStatus.GENERATED for status in statuses) else VisualBatchStatus.FAILED
        elif any(item.status in {VisualGenerationStatus.PENDING, VisualGenerationStatus.APPROVED, VisualGenerationStatus.NEEDS_REVIEW} for item in requests):
            batch_status = VisualBatchStatus.PARTIAL
        elif statuses and all(status == VisualGenerationStatus.GENERATED for status in statuses):
            batch_status = VisualBatchStatus.COMPLETED
        else:
            batch_status = VisualBatchStatus.PENDING
        return candidate.model_copy(update={
            "requests": requests, "artifacts": artifacts, "status": batch_status,
            "continuity_result": result,
            "warnings": list(dict.fromkeys([*batch.warnings, *result.warnings, *result.errors])),
        })


def set_request_review_status(batch: VisualGenerationBatch, request_id: str,
                              status: VisualGenerationStatus) -> VisualGenerationBatch:
    """Apply a human decision; approval is refused when the saved prompt hash is stale."""
    if status not in {VisualGenerationStatus.APPROVED, VisualGenerationStatus.REJECTED, VisualGenerationStatus.NEEDS_REVIEW}:
        raise ValueError("review status must be approved, rejected, or needs_review")
    requests = list(batch.requests)
    for index, request in enumerate(requests):
        if request.request_id != request_id:
            continue
        if request.status == VisualGenerationStatus.GENERATED and status == VisualGenerationStatus.APPROVED:
            raise ValueError("generated requests cannot be approved again")
        expected_hash = deterministic_prompt_hash(
            project_id=request.project_id, asset_type=request.asset_type,
            source_entity_id=request.source_entity_id, scene_id=request.scene_id,
            prompt=request.prompt, negative_prompt=request.negative_prompt,
            evidence_ids=request.evidence_ids, visual_spec_version=request.visual_spec_version,
            expected_character_ids=request.expected_character_ids,
            expected_costume_ids=request.expected_costume_ids,
            expected_scene_ids=request.expected_scene_ids,
        )
        if status == VisualGenerationStatus.APPROVED and request.prompt_hash != expected_hash:
            requests[index] = request.model_copy(update={
                "status": VisualGenerationStatus.NEEDS_REVIEW,
                "warnings": [*request.warnings, "Prompt integrity check failed; approval refused. Regenerate requests and review the current spec."],
            })
        else:
            requests[index] = request.model_copy(update={"status": status})
        return batch.model_copy(update={
            "requests": requests, "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    raise KeyError(f"generation request not found: {request_id}")


def _failure_artifact(request: VisualGenerationRequest, provider_name: str, exc: Exception) -> GeneratedVisualArtifact:
    artifact_id = "ART_FAIL_" + hashlib.sha256(f"{request.request_id}|{request.prompt_hash}".encode("utf-8")).hexdigest()[:16].upper()
    return GeneratedVisualArtifact(
        artifact_id=artifact_id, request_id=request.request_id, project_id=request.project_id,
        asset_type=request.asset_type, source_entity_id=request.source_entity_id, scene_id=request.scene_id,
        provider=provider_name, model_name=provider_name, status=VisualGenerationStatus.FAILED,
        image_path=None, image_metadata={"error_type": type(exc).__name__}, prompt_hash=request.prompt_hash,
        created_at=datetime.now(timezone.utc).isoformat(), continuity_status="failed",
        warnings=[f"{type(exc).__name__}: {exc}"],
    )
