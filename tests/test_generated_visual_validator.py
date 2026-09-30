from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from test_visual_generation import _SpyProvider, setup_generation

from app.models.visual_generation import VisualAssetType, VisualGenerationStatus as Status
from app.services.generated_visual_validator import validate_generated_visuals
from app.services.visual_artifact_store import VisualArtifactStore
from app.services.visual_generation_planner import create_visual_generation_batch
from app.services.visual_generation_service import VisualGenerationService, set_request_review_status


def generated_batch(tmp_path, *, scenes=1):
    state, plan, adapted, pack, evidence, batch = setup_generation(tmp_path)
    chosen = [item for item in batch.requests if item.asset_type == VisualAssetType.SCENE_KEYFRAME][:scenes]
    for request in [next(item for item in batch.requests if item.asset_type == VisualAssetType.CHARACTER), *chosen]:
        batch = set_request_review_status(batch, request.request_id, Status.APPROVED)
    provider = _SpyProvider()
    fresh = create_visual_generation_batch(pack, state, adapted, plan, cultural_evidence=evidence)
    result = VisualGenerationService(provider, VisualArtifactStore(tmp_path / "data")).generate_approved(batch, fresh.requests, pack, state)
    return state, pack, fresh, result


def test_generated_placeholder_passes_metadata_continuity_checks(tmp_path):
    state, pack, fresh, batch = generated_batch(tmp_path)
    result = validate_generated_visuals(batch, pack, state, current_requests=fresh.requests)
    assert result.valid
    assert result.checked_artifact_count == 2
    assert result.failed_artifact_count == 0
    assert any("do not verify facial identity" in warning for warning in result.warnings)


def test_invalid_source_entity_and_prompt_hash_are_detected(tmp_path):
    state, pack, fresh, batch = generated_batch(tmp_path)
    artifact = batch.artifacts[0].model_copy(update={"source_entity_id": "CHAR_MISSING", "prompt_hash": "wrong"})
    changed = batch.model_copy(update={"artifacts": [artifact, *batch.artifacts[1:]]})
    result = validate_generated_visuals(changed, pack, state, current_requests=fresh.requests)
    assert any("does not match its request identity" in error for error in result.errors)
    assert any("prompt hash differs" in error for error in result.errors)


def test_identity_change_metadata_is_flagged_without_claiming_pixel_analysis(tmp_path):
    state, pack, fresh, batch = generated_batch(tmp_path)
    artifact = batch.artifacts[0].model_copy(update={
        "image_metadata": {**batch.artifacts[0].image_metadata, "unexpected_identity_change": True},
    })
    changed = batch.model_copy(update={"artifacts": [artifact, *batch.artifacts[1:]]})
    result = validate_generated_visuals(changed, pack, state, current_requests=fresh.requests)
    assert any("unexpected identity change" in error for error in result.errors)
    assert not result.valid


def test_scene_artifact_order_is_validated(tmp_path):
    state, pack, fresh, batch = generated_batch(tmp_path, scenes=2)
    scene_artifacts = [item for item in batch.artifacts if item.asset_type == VisualAssetType.SCENE_KEYFRAME]
    first_non_scene = next(item for item in batch.artifacts if item.asset_type == VisualAssetType.CHARACTER)
    changed = batch.model_copy(update={"artifacts": [first_non_scene, *reversed(scene_artifacts)]})
    result = validate_generated_visuals(changed, pack, state, current_requests=fresh.requests)
    assert any("do not preserve canonical scene order" in error for error in result.errors)
