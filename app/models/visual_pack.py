"""Structured, evidence-traceable visual production specifications (Phase 7)."""
from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from app.models.extraction import ExtractionModel


class CharacterVisualBible(ExtractionModel):
    character_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    age_description: str | None = None
    role: str | None = None
    face_identity: str | None = None
    body_description: str | None = None
    hair: str | None = None
    grooming: str | None = None
    baseline_wardrobe: str | None = None
    accessories: list[str] = Field(default_factory=list)
    cultural_markers: list[str] = Field(default_factory=list)
    personality_visual_cues: list[str] = Field(default_factory=list)
    expression_baseline: str | None = None
    continuity_notes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    applied_change_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CostumeVisualBible(ExtractionModel):
    costume_id: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    variant_name: str = Field(min_length=1)
    scene_ids: list[str] = Field(default_factory=list)
    garments: list[str] = Field(default_factory=list)
    fabric: str | None = None
    colors: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    jewellery: list[str] = Field(default_factory=list)
    footwear: str | None = None
    headwear: str | None = None
    grooming_relationship: str | None = None
    cultural_details: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    applied_change_ids: list[str] = Field(default_factory=list)
    continuity_notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SceneVisualKeyframe(ExtractionModel):
    scene_id: str = Field(min_length=1)
    scene_number: int = Field(ge=1)
    location: str | None = None
    time_of_day: str | None = None
    weather: str | None = None
    mood: str | None = None
    characters_present: list[str] = Field(default_factory=list)
    character_visual_refs: list[str] = Field(default_factory=list)
    costume_visual_refs: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    architecture: str | None = None
    environment: str | None = None
    lighting: str | None = None
    composition: str | None = None
    camera_framing: str | None = None
    atmosphere: str | None = None
    cultural_details: list[str] = Field(default_factory=list)
    generation_prompt: str = ""
    negative_prompt: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    applied_change_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class VisualValidationResult(ExtractionModel):
    valid: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_references: list[str] = Field(default_factory=list)
    unsupported_cultural_details: list[str] = Field(default_factory=list)
    character_count: int = Field(default=0, ge=0)
    costume_count: int = Field(default=0, ge=0)
    scene_keyframe_count: int = Field(default=0, ge=0)
    evidence_linked_claim_count: int = Field(default=0, ge=0)


class VisualProductionPack(ExtractionModel):
    project_id: str = Field(min_length=1)
    culture: str = Field(min_length=1)
    dialect: str | None = None
    region: str = Field(min_length=1)
    setting: str = Field(min_length=1)
    script: str | None = None
    character_bibles: list[CharacterVisualBible] = Field(default_factory=list)
    costume_bibles: list[CostumeVisualBible] = Field(default_factory=list)
    scene_keyframes: list[SceneVisualKeyframe] = Field(default_factory=list)
    continuity_warnings: list[str] = Field(default_factory=list)
    validation_result: VisualValidationResult = Field(default_factory=VisualValidationResult)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)

    @field_validator("created_at", "updated_at")
    @classmethod
    def valid_iso_timestamp(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamps must be ISO 8601") from exc
        return value
