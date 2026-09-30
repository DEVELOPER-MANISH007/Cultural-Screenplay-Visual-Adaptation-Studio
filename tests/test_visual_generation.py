from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent))
from test_screenplay_adapter import RAW, evidence_pack, make_change, make_plan, sample_state

from app.models.adaptation import AdaptationCategory
from app.models.visual_generation import VisualAssetType, VisualGenerationStatus as Status
from app.services.image_generation_provider import MockImageGenerationProvider
from app.services.screenplay_adapter import adapt_screenplay
from app.services.visual_artifact_store import VisualArtifactStore
from app.services.visual_generation_planner import (
    create_visual_generation_batch, deterministic_prompt_hash, reconcile_generation_batch,
)
from app.services.visual_generation_service import VisualGenerationService, set_request_review_status
from app.services.visual_pack_generator import MockVisualPackGenerator
from app.services.visual_pack_store import VisualPackStore


def setup_generation(tmp_path):
    state = sample_state()
    _, evidence = evidence_pack(tmp_path / "culture")
    plan = make_plan([make_change("COSTUME_APPROVED", status="approved", category=AdaptationCategory.COSTUME,
                                 target_type="character", target_id="CHAR_001", evidence_ids=["EVID_005"])])
    adapted = adapt_screenplay(state, plan, evidence, RAW)
    pack = MockVisualPackGenerator().generate(state, adapted, plan, evidence)
    batch = create_visual_generation_batch(pack, state, adapted, plan, cultural_evidence=evidence)
    return state, plan, adapted, pack, evidence, batch


def test_request_planning_stable_ids_asset_coverage_order_and_evidence(tmp_path):
    state, plan, adapted, pack, evidence, batch = setup_generation(tmp_path)
    repeat = create_visual_generation_batch(pack, state, adapted, plan, cultural_evidence=evidence)
    assert [r.request_id for r in batch.requests] == [r.request_id for r in repeat.requests]
    assert all(r.status == Status.PENDING for r in batch.requests)
    assert sum(r.asset_type == VisualAssetType.CHARACTER for r in batch.requests) == 2
    assert sum(r.asset_type == VisualAssetType.COSTUME for r in batch.requests) == 1
    scene_requests = [r for r in batch.requests if r.asset_type == VisualAssetType.SCENE_KEYFRAME]
    assert [r.scene_id for r in scene_requests] == [scene.scene_id for scene in state.scenes]
    costume_request = next(r for r in batch.requests if r.asset_type == VisualAssetType.COSTUME)
    assert costume_request.source_entity_id == pack.costume_bibles[0].costume_id
    assert costume_request.evidence_ids == ["EVID_005"]
    assert scene_requests[1].prompt == pack.scene_keyframes[1].generation_prompt


def test_deterministic_prompt_hash_and_prompt_integrity_invalidation(tmp_path):
    state, plan, adapted, pack, evidence, batch = setup_generation(tmp_path)
    target = next(r for r in batch.requests if r.asset_type == VisualAssetType.SCENE_KEYFRAME)
    approved = set_request_review_status(batch, target.request_id, Status.APPROVED)
    frame = pack.scene_keyframes[0].model_copy(update={"negative_prompt": pack.scene_keyframes[0].negative_prompt + "\nNo artificial lens flare."})
    changed_pack = pack.model_copy(update={"scene_keyframes": [frame, *pack.scene_keyframes[1:]]})
    fresh = create_visual_generation_batch(changed_pack, state, adapted, plan, cultural_evidence=evidence)
    old = target
    assert deterministic_prompt_hash(project_id=old.project_id, asset_type=old.asset_type,
        source_entity_id=old.source_entity_id, scene_id=old.scene_id, prompt=old.prompt,
        negative_prompt=old.negative_prompt, evidence_ids=old.evidence_ids,
        visual_spec_version=old.visual_spec_version,
        expected_character_ids=old.expected_character_ids,
        expected_costume_ids=old.expected_costume_ids,
        expected_scene_ids=old.expected_scene_ids) == old.prompt_hash
    assert next(r for r in approved.requests if r.request_id == target.request_id).status == Status.APPROVED
    assert old.prompt_hash != next(r for r in fresh.requests if r.request_id == old.request_id).prompt_hash
    reconciled = reconcile_generation_batch(approved, fresh)
    stale = next(r for r in reconciled.requests if r.request_id == old.request_id)
    assert stale.status == Status.NEEDS_REVIEW
    assert any("changed" in warning for warning in stale.warnings)


@pytest.mark.parametrize("status", [Status.PENDING, Status.REJECTED, Status.NEEDS_REVIEW])
def test_nonapproved_requests_never_reach_provider(tmp_path, status):
    state, plan, adapted, pack, evidence, batch = setup_generation(tmp_path / f"case_{status.value}")
    request = batch.requests[0]
    if status != Status.PENDING:
        batch = set_request_review_status(batch, request.request_id, status)
    fresh = create_visual_generation_batch(pack, state, adapted, plan, cultural_evidence=evidence)
    provider = _SpyProvider()
    result = VisualGenerationService(provider, VisualArtifactStore(tmp_path / f"data_{status.value}")).generate_approved(batch, fresh.requests, pack, state)
    assert provider.calls == 0
    assert not [a for a in result.artifacts if a.request_id == request.request_id]


def test_exactly_approved_requests_are_generated_and_continuity_checked(tmp_path):
    state, plan, adapted, pack, evidence, batch = setup_generation(tmp_path)
    state_before = state.model_dump(mode="json")
    plan_before = plan.model_dump(mode="json")
    adapted_before = adapted.model_dump(mode="json")
    pack_before = pack.model_dump(mode="json")
    char_request = next(r for r in batch.requests if r.asset_type == VisualAssetType.CHARACTER)
    scene_request = next(r for r in batch.requests if r.asset_type == VisualAssetType.SCENE_KEYFRAME)
    batch = set_request_review_status(batch, char_request.request_id, Status.APPROVED)
    batch = set_request_review_status(batch, scene_request.request_id, Status.APPROVED)
    store = VisualArtifactStore(tmp_path / "data")
    provider = _SpyProvider()
    fresh = create_visual_generation_batch(pack, state, adapted, plan, cultural_evidence=evidence)
    result = VisualGenerationService(provider, store).generate_approved(batch, fresh.requests, pack, state)
    assert provider.calls == 2
    assert len(result.artifacts) == 2
    assert all(item.provider == "mock" and item.image_metadata["mock_placeholder"] for item in result.artifacts)
    assert result.continuity_result.valid
    assert result.continuity_result.checked_artifact_count == 2
    assert all(item.continuity_status == "valid" for item in result.artifacts)
    assert sum(r.status == Status.PENDING for r in result.requests) == len(batch.requests) - 2
    assert state.model_dump(mode="json") == state_before
    assert plan.model_dump(mode="json") == plan_before
    assert adapted.model_dump(mode="json") == adapted_before
    assert pack.model_dump(mode="json") == pack_before


def test_provider_failure_is_returned_as_structured_failed_artifact(tmp_path):
    state, plan, adapted, pack, evidence, batch = setup_generation(tmp_path)
    request = batch.requests[0]
    batch = set_request_review_status(batch, request.request_id, Status.APPROVED)
    class FailureProvider:
        name = "mock"
        def generate(self, request): raise RuntimeError("provider unavailable")
    fresh = create_visual_generation_batch(pack, state, adapted, plan, cultural_evidence=evidence)
    result = VisualGenerationService(FailureProvider(), VisualArtifactStore(tmp_path / "data")).generate_approved(
        batch, fresh.requests, pack, state,
    )
    assert len(result.artifacts) == 1
    assert result.artifacts[0].status == Status.FAILED
    assert "provider unavailable" in result.artifacts[0].warnings[0]
    assert result.continuity_result.failed_artifact_count == 1


def test_changed_prompt_after_approval_is_not_sent_to_provider(tmp_path):
    state, plan, adapted, pack, evidence, batch = setup_generation(tmp_path)
    request = next(r for r in batch.requests if r.asset_type == VisualAssetType.SCENE_KEYFRAME)
    batch = set_request_review_status(batch, request.request_id, Status.APPROVED)
    frames = list(pack.scene_keyframes)
    frames[0] = frames[0].model_copy(update={"negative_prompt": frames[0].negative_prompt + "\nchanged"})
    changed_pack = pack.model_copy(update={"scene_keyframes": frames})
    fresh = create_visual_generation_batch(changed_pack, state, adapted, plan, cultural_evidence=evidence)
    provider = _SpyProvider()
    result = VisualGenerationService(provider, VisualArtifactStore(tmp_path / "data")).generate_approved(batch, fresh.requests, changed_pack, state)
    current = next(r for r in result.requests if r.request_id == request.request_id)
    assert current.status == Status.NEEDS_REVIEW
    assert provider.calls == 0


def test_provider_change_invalidates_old_approval(tmp_path):
    state, plan, adapted, pack, evidence, batch = setup_generation(tmp_path)
    request = batch.requests[0]
    batch = set_request_review_status(batch, request.request_id, Status.APPROVED)
    fresh = create_visual_generation_batch(pack, state, adapted, plan, provider="future", cultural_evidence=evidence)
    provider = _FutureProvider()
    result = VisualGenerationService(provider, VisualArtifactStore(tmp_path / "data")).generate_approved(
        batch, fresh.requests, pack, state,
    )
    assert provider.calls == 0
    changed = next(r for r in result.requests if r.request_id == request.request_id)
    assert changed.status == Status.NEEDS_REVIEW
    assert any("Provider selection changed" in warning for warning in changed.warnings)


def test_invalid_canonical_character_source_is_skipped(tmp_path):
    state, plan, adapted, pack, evidence, _ = setup_generation(tmp_path)
    bible = pack.character_bibles[0].model_copy(update={"character_id": "CHAR_MISSING"})
    changed_pack = pack.model_copy(update={"character_bibles": [bible, *pack.character_bibles[1:]]})
    batch = create_visual_generation_batch(changed_pack, state, adapted, plan)
    assert not any(r.source_entity_id == "CHAR_MISSING" for r in batch.requests)
    assert any("not canonical" in warning for warning in batch.warnings)
    assert len([r for r in batch.requests if r.asset_type == VisualAssetType.CHARACTER]) == 1


def test_invalid_phase7_pack_produces_no_requests(tmp_path):
    state, plan, adapted, pack, _, _ = setup_generation(tmp_path)
    changed_pack = pack.model_copy(update={"validation_result": pack.validation_result.model_copy(update={"valid": False, "errors": ["bad spec"]})})
    batch = create_visual_generation_batch(changed_pack, state, adapted, plan)
    assert not batch.requests
    assert batch.warnings


class _SpyProvider(MockImageGenerationProvider):
    def __init__(self): self.calls = 0
    def generate(self, request):
        self.calls += 1
        return super().generate(request)


class _FutureProvider(_SpyProvider):
    name = "future"
