from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent))
from test_visual_generation import setup_generation

from app.models.visual_generation import VisualAssetType, VisualGenerationStatus as Status
from app.services.adaptation_store import AdaptationStore
from app.services.adapted_screenplay_store import AdaptedScreenplayStore
from app.services.image_generation_provider import MockImageGenerationProvider
from app.services.project_store import ProjectStore
from app.services.visual_artifact_store import VisualArtifactLoadError, VisualArtifactStore
from app.services.visual_generation_service import set_request_review_status


def test_mock_media_and_batch_save_load_round_trip_persists_approval_and_metadata(tmp_path):
    state, plan, adapted, pack, _, batch = setup_generation(tmp_path)
    request = next(item for item in batch.requests if item.asset_type == VisualAssetType.CHARACTER)
    batch = set_request_review_status(batch, request.request_id, Status.APPROVED)
    request = next(item for item in batch.requests if item.request_id == request.request_id)
    artifact = MockImageGenerationProvider().generate(request)
    store = VisualArtifactStore(tmp_path / "data")
    artifact = store.save_artifact(artifact)
    batch = batch.model_copy(update={"artifacts": [artifact]})
    saved = store.save_batch(batch)
    loaded = VisualArtifactStore(tmp_path / "data").load_batch(state.project_id)
    assert loaded.model_dump(mode="json") == saved.model_dump(mode="json")
    assert next(item for item in loaded.requests if item.request_id == request.request_id).status == Status.APPROVED
    restored = loaded.artifacts[0]
    assert restored.image_path == f"visuals/{restored.artifact_id}.svg"
    content = store.read_media(state.project_id, restored).decode("utf-8")
    assert "MOCK PLACEHOLDER" in content and "NOT A REAL GENERATED IMAGE" in content


def test_batch_version_and_stable_ids_on_update(tmp_path):
    state, _, _, _, _, batch = setup_generation(tmp_path)
    store = VisualArtifactStore(tmp_path / "data")
    first = store.save_batch(batch)
    updated = set_request_review_status(first, first.requests[0].request_id, Status.APPROVED)
    second = store.save_batch(updated)
    assert second.version == first.version + 1
    assert second.created_at == first.created_at
    assert [item.request_id for item in second.requests] == [item.request_id for item in first.requests]
    assert store.load_batch(state.project_id).requests[0].status == Status.APPROVED


def test_missing_invalid_json_and_malformed_project_id(tmp_path):
    store = VisualArtifactStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.load_batch("MISSING")
    invalid = tmp_path / "projects" / "BROKEN" / "visual_artifacts.json"
    invalid.parent.mkdir(parents=True); invalid.write_text("nope", encoding="utf-8")
    with pytest.raises(VisualArtifactLoadError):
        store.load_batch("BROKEN")
    with pytest.raises(ValueError):
        store.load_batch("../escape")


def test_media_path_traversal_is_rejected(tmp_path):
    state, _, _, _, _, batch = setup_generation(tmp_path)
    artifact = MockImageGenerationProvider().generate(batch.requests[0].model_copy(update={"status": Status.APPROVED}))
    from app.models.visual_generation import GeneratedVisualArtifact
    malicious = artifact.model_copy(update={"image_path": "visuals/../../project.json"})
    with pytest.raises(ValueError, match="outside"):
        VisualArtifactStore(tmp_path / "data").read_media(state.project_id, malicious)


def test_store_can_persist_provider_png_bytes(tmp_path):
    state, _, _, _, _, batch = setup_generation(tmp_path)
    request = batch.requests[0].model_copy(update={"status": Status.APPROVED})
    from app.services.image_generation_provider import MockImageGenerationProvider
    artifact = MockImageGenerationProvider().generate(request)
    png_header = b"\x89PNG\r\n\x1a\n"
    artifact = artifact.model_copy(update={"image_metadata": {
        **artifact.image_metadata, "representation": "png", "_media_content": png_header + b"phase8-provider-bytes",
    }})
    store = VisualArtifactStore(tmp_path / "data")
    artifact = store.save_artifact(artifact)
    assert artifact.image_path.endswith(".png")
    assert store.read_media(state.project_id, artifact) == png_header + b"phase8-provider-bytes"


def test_artifact_persistence_does_not_overwrite_phase3_5_or_6_files(tmp_path):
    state, plan, adapted, _, _, batch = setup_generation(tmp_path)
    data_root = tmp_path / "data"
    project_store = ProjectStore(data_root); plan_store = AdaptationStore(data_root)
    adapted_store = AdaptedScreenplayStore(data_root)
    project_store.save_project(state); plan_store.save_plan(plan); adapted_store.save_adapted_screenplay(adapted)
    before = (
        project_store.load_project(state.project_id).model_dump(mode="json"),
        plan_store.load_plan(state.project_id).model_dump(mode="json"),
        adapted_store.load_adapted_screenplay(state.project_id).model_dump(mode="json"),
    )
    store = VisualArtifactStore(data_root)
    store.save_batch(batch)
    assert project_store.load_project(state.project_id).model_dump(mode="json") == before[0]
    assert plan_store.load_plan(state.project_id).model_dump(mode="json") == before[1]
    assert adapted_store.load_adapted_screenplay(state.project_id).model_dump(mode="json") == before[2]
