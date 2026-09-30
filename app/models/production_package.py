"""Stable references and summaries for an exported production package."""
from pydantic import Field
from app.models.extraction import ExtractionModel


class ProductionPackage(ExtractionModel):
    package_id: str
    project_id: str
    title: str
    culture: str
    dialect: str | None = None
    region: str
    setting: str
    script: str | None = None
    source_screenplay_reference: str
    project_state_reference: str
    cultural_evidence_summary: dict = Field(default_factory=dict)
    adaptation_summary: dict = Field(default_factory=dict)
    adapted_screenplay_reference: str
    character_bible_references: list[str] = Field(default_factory=list)
    costume_bible_references: list[str] = Field(default_factory=list)
    scene_keyframe_references: list[str] = Field(default_factory=list)
    generated_visual_references: list[str] = Field(default_factory=list)
    continuity_report_reference: str
    ai_usage_reference: str
    limitations_reference: str
    package_status: str = "ready"
    validation_status: str = "pending"
    created_at: str
    updated_at: str
    version: int = Field(default=1, ge=1)
