from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent))
from test_visual_generation import setup_generation

from app.models.visual_generation import VisualAssetType, VisualGenerationStatus as Status
from app.services.image_generation_provider import (
    MockImageGenerationProvider, available_image_generation_providers,
    get_image_generation_provider, register_image_generation_provider,
)


def test_mock_provider_creates_deterministic_labeled_placeholder_not_real_image(tmp_path):
    _, _, _, _, _, batch = setup_generation(tmp_path)
    request = next(item for item in batch.requests if item.asset_type == VisualAssetType.CHARACTER).model_copy(update={"status": Status.APPROVED})
    provider = MockImageGenerationProvider()
    first = provider.generate(request)
    second = provider.generate(request)
    assert first.artifact_id == second.artifact_id
    assert first.prompt_hash == request.prompt_hash
    assert first.status == Status.GENERATED
    assert first.image_metadata["mock_placeholder"] is True
    assert first.image_metadata["not_a_real_image"] is True
    assert "NOT A REAL GENERATED IMAGE" in first.image_metadata["_media_content"]
    assert first.model_name == "mock-placeholder-v1"


def test_mock_provider_rejects_pending_requests(tmp_path):
    _, _, _, _, _, batch = setup_generation(tmp_path)
    with pytest.raises(ValueError, match="only approved"):
        MockImageGenerationProvider().generate(batch.requests[0])


def test_provider_factory_returns_mock_and_rejects_unconfigured_name():
    assert isinstance(get_image_generation_provider("mock"), MockImageGenerationProvider)
    with pytest.raises(ValueError, match="not configured"):
        get_image_generation_provider("imaginary-provider")


def test_provider_registry_accepts_future_provider_without_changing_orchestrator():
    class FutureProvider:
        name = "test_future_provider"
        def generate(self, request): raise NotImplementedError
    register_image_generation_provider("test_future_provider", FutureProvider)
    assert "test_future_provider" in available_image_generation_providers()
    assert isinstance(get_image_generation_provider("test_future_provider"), FutureProvider)
