"""Explicit known limitations and unresolved items for a packaged project."""
from pydantic import Field
from app.models.extraction import ExtractionModel


class LimitationItem(ExtractionModel):
    limitation_id: str
    title: str
    detail: str
    status: str = "unresolved"
    related_phase: str | None = None


class LimitationsReport(ExtractionModel):
    project_id: str
    items: list[LimitationItem] = Field(default_factory=list)
    generated_at: str
