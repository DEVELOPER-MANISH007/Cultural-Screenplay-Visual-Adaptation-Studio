"""Persistent request, batch and artifact models for Phase 8 visual generation."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from app.models.extraction import ExtractionModel


class VisualAssetType(str, Enum):
    CHARACTER = "character"
    COSTUME = "costume"
    SCENE_KEYFRAME = "scene_keyframe"


class VisualGenerationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    GENERATED = "generated"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class VisualBatchStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"


class VisualGenerationRequest(ExtractionModel):
    request_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    asset_type: VisualAssetType
    source_entity_id: str = Field(min_length=1)
    scene_id: str | None = None
    prompt: str = Field(min_length=1)
    negative_prompt: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    expected_character_ids: list[str] = Field(default_factory=list)
    expected_costume_ids: list[str] = Field(default_factory=list)
    expected_scene_ids: list[str] = Field(default_factory=list)
    visual_spec_version: int = Field(ge=1)
    prompt_hash: str = Field(min_length=1)
    status: VisualGenerationStatus = VisualGenerationStatus.PENDING
    provider: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("created_at")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("created_at must be ISO 8601") from exc
        return value


class GeneratedVisualArtifact(ExtractionModel):
    artifact_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    asset_type: VisualAssetType
    source_entity_id: str = Field(min_length=1)
    scene_id: str | None = None
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    status: VisualGenerationStatus
    image_path: str | None = None
    image_metadata: dict[str, Any] = Field(default_factory=dict)
    prompt_hash: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    continuity_status: str = "pending"
    warnings: list[str] = Field(default_factory=list)

    @field_validator("created_at")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("created_at must be ISO 8601") from exc
        return value


class VisualContinuityValidationResult(ExtractionModel):
    valid: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_artifact_count: int = Field(default=0, ge=0)
    failed_artifact_count: int = Field(default=0, ge=0)


class VisualGenerationBatch(ExtractionModel):
    batch_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    requests: list[VisualGenerationRequest] = Field(default_factory=list)
    artifacts: list[GeneratedVisualArtifact] = Field(default_factory=list)
    status: VisualBatchStatus = VisualBatchStatus.PENDING
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    warnings: list[str] = Field(default_factory=list)
    continuity_result: VisualContinuityValidationResult = Field(default_factory=VisualContinuityValidationResult)

    @field_validator("created_at", "updated_at")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamps must be ISO 8601") from exc
        return value
