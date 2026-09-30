"""Reviewable adaptation-plan models; these records never rewrite screenplay content."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, field_validator, model_validator

from app.models.extraction import ExtractionModel


class AdaptationPlanStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class AdaptationChangeStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"
    NEEDS_REVIEW = "needs_review"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AdaptationCategory(str, Enum):
    DIALOGUE = "dialogue"
    DIALECT = "dialect"
    KINSHIP = "kinship"
    HONORIFIC = "honorific"
    HUMOUR = "humour"
    GREETING = "greeting"
    GESTURE = "gesture"
    POSTURE = "posture"
    EYE_CONTACT = "eye_contact"
    TOUCH = "touch"
    SEATING = "seating"
    FOOD = "food"
    COSTUME = "costume"
    GROOMING = "grooming"
    JEWELLERY = "jewellery"
    ARCHITECTURE = "architecture"
    INTERIOR = "interior"
    PROPS = "props"
    TRANSPORT = "transport"
    LANDSCAPE = "landscape"
    RITUAL = "ritual"
    SOUND = "sound"
    MUSIC = "music"
    CHARACTER = "character"
    RELATIONSHIP = "relationship"
    SOCIAL_BEHAVIOR = "social_behavior"
    PRODUCTION_DESIGN = "production_design"
    STORY_WORLD = "story_world"


class AdaptationChange(ExtractionModel):
    change_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    category: AdaptationCategory
    target_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    original_element: str = Field(min_length=1)
    proposed_change: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    status: AdaptationChangeStatus = AdaptationChangeStatus.PENDING
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_evidence_ids(self):
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        return self


class AdaptationPlan(ExtractionModel):
    plan_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    culture: str = Field(min_length=1)
    dialect: str | None = None
    region: str = Field(min_length=1)
    setting: str = Field(min_length=1)
    script: str | None = None
    status: AdaptationPlanStatus = AdaptationPlanStatus.PENDING_REVIEW
    version: int = Field(default=1, ge=1)
    changes: list[AdaptationChange] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    global_warnings: list[str] = Field(default_factory=list)
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
    def unique_change_ids(self):
        ids = [change.change_id for change in self.changes]
        if len(ids) != len(set(ids)):
            raise ValueError("change IDs must be unique")
        return self
