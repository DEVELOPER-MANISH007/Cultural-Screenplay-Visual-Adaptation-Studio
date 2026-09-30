"""Provider boundary for visual generation; no provider is selected globally."""
from __future__ import annotations

import hashlib
import html
from typing import Protocol
from collections.abc import Callable

from app.models.visual_generation import GeneratedVisualArtifact, VisualGenerationRequest, VisualGenerationStatus


class ImageGenerationProvider(Protocol):
    """A provider converts one approved request into one artifact record."""

    name: str

    def generate(self, request: VisualGenerationRequest) -> GeneratedVisualArtifact:
        """Generate artifact metadata and optional inline media data for persistence."""
        ...


class MockImageGenerationProvider:
    """Offline deterministic SVG label card; explicitly not a generated cinematic image."""

    name = "mock"
    model_name = "mock-placeholder-v1"

    def generate(self, request: VisualGenerationRequest) -> GeneratedVisualArtifact:
        if request.status.value != "approved":
            raise ValueError("MockImageGenerationProvider accepts only approved requests")
        artifact_hash = hashlib.sha256(f"{request.request_id}|{request.prompt_hash}|{self.name}".encode("utf-8")).hexdigest()[:20].upper()
        label = html.escape(f"MOCK PLACEHOLDER · {request.asset_type.value.upper()}")
        entity = html.escape(request.source_entity_id)
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">'
            '<rect width="640" height="360" fill="#eee8dc"/>'
            '<rect x="18" y="18" width="604" height="324" rx="16" fill="#d8ccba" stroke="#4a4035" stroke-width="3"/>'
            f'<text x="320" y="155" text-anchor="middle" font-family="sans-serif" font-size="28" fill="#302820">{label}</text>'
            f'<text x="320" y="205" text-anchor="middle" font-family="sans-serif" font-size="22" fill="#302820">{entity}</text>'
            '<text x="320" y="265" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#5b5147">NOT A REAL GENERATED IMAGE</text>'
            '</svg>'
        )
        return GeneratedVisualArtifact(
            artifact_id=f"ART_{artifact_hash}", request_id=request.request_id,
            project_id=request.project_id, asset_type=request.asset_type,
            source_entity_id=request.source_entity_id, scene_id=request.scene_id,
            provider=self.name, model_name=self.model_name,
            status=VisualGenerationStatus.GENERATED, image_path=None,
            image_metadata={
                "mock_placeholder": True,
                "not_a_real_image": True,
                "representation": "svg",
                "_media_content": svg,
                "visual_spec_version": request.visual_spec_version,
                "evidence_ids": list(request.evidence_ids),
                "expected_character_ids": list(request.expected_character_ids),
                "expected_costume_ids": list(request.expected_costume_ids),
                "expected_scene_ids": list(request.expected_scene_ids),
                "identity_analysis": {"performed": False},
                "label": "MOCK PLACEHOLDER — NOT A REAL GENERATED IMAGE",
            },
            prompt_hash=request.prompt_hash,
            created_at=request.created_at, continuity_status="pending",
            warnings=["Mock provider created a labeled placeholder only; no image-generation model was called."],
        )


_PROVIDERS: dict[str, Callable[[], ImageGenerationProvider]] = {"mock": MockImageGenerationProvider}


def register_image_generation_provider(name: str, factory: Callable[[], ImageGenerationProvider]) -> None:
    """Register a future provider without changing the planner or orchestration service."""
    normalized = name.strip().casefold()
    if not normalized or not normalized.replace("_", "").replace("-", "").isalnum():
        raise ValueError("provider name must be a non-empty identifier")
    if normalized in _PROVIDERS:
        raise ValueError(f"image generation provider is already registered: {normalized}")
    _PROVIDERS[normalized] = factory


def available_image_generation_providers() -> list[str]:
    return sorted(_PROVIDERS)


def get_image_generation_provider(provider_name: str = "mock") -> ImageGenerationProvider:
    """Provider factory boundary for future integrations."""
    try:
        provider = _PROVIDERS[provider_name.casefold()]()
        if provider.name.casefold() != provider_name.casefold():
            raise ValueError("provider factory name does not match its registered name")
        return provider
    except KeyError as exc:
        raise ValueError(f"Image generation provider {provider_name!r} is not configured") from exc
