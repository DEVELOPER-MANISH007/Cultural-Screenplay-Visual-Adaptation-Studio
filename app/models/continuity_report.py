"""Structural continuity and traceability results for final packaging."""
from pydantic import Field

from app.models.extraction import ExtractionModel


class ContinuityReport(ExtractionModel):
    report_id: str
    project_id: str
    status: str
    checked_scenes: int = Field(ge=0)
    checked_characters: int = Field(ge=0)
    checked_costumes: int = Field(ge=0)
    checked_props: int = Field(ge=0)
    checked_visual_artifacts: int = Field(ge=0)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    evidence_traceability_issues: list[str] = Field(default_factory=list)
    adaptation_traceability_issues: list[str] = Field(default_factory=list)
    generated_at: str


class FinalValidationResult(ExtractionModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_items: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    continuity_report: ContinuityReport | None = None
