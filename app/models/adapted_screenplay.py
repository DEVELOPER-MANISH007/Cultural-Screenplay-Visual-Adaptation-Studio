"""Models for a separate adapted screenplay and lightweight validation results."""
from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.models.extraction import ExtractionModel


class AdaptedScene(ExtractionModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    scene_id: str = Field(min_length=1)
    scene_number: int = Field(ge=1)
    original_heading: str
    adapted_heading: str
    original_text: str
    adapted_text: str
    applied_change_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_trace_ids(self):
        if len(self.applied_change_ids) != len(set(self.applied_change_ids)):
            raise ValueError("applied_change_ids must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        return self


class AdaptedScreenplay(ExtractionModel):
    # Preserve raw screenplay text byte-for-character at the Unicode string level.
    model_config = ConfigDict(str_strip_whitespace=False)

    adaptation_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    source_screenplay_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    culture: str = Field(min_length=1)
    dialect: str | None = None
    region: str = Field(min_length=1)
    setting: str = Field(min_length=1)
    scenes: list[AdaptedScene] = Field(default_factory=list)
    applied_change_ids: list[str] = Field(default_factory=list)
    blocked_change_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    original_screenplay_text: str = ""
    adapted_screenplay_text: str = ""
    warnings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)

    @field_validator("created_at", "updated_at")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamps must be ISO 8601") from exc
        return value

    @model_validator(mode="after")
    def unique_change_and_evidence_ids(self):
        if len(self.applied_change_ids) != len(set(self.applied_change_ids)):
            raise ValueError("applied_change_ids must be unique")
        if len(self.blocked_change_ids) != len(set(self.blocked_change_ids)):
            raise ValueError("blocked_change_ids must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        return self


class AdaptationValidationResult(ExtractionModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_scene_count: int = Field(ge=0)
    applied_change_count: int = Field(ge=0)
