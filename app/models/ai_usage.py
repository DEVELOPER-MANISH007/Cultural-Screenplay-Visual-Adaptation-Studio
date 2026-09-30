"""Auditable record of processing modes used in a production package."""
from pydantic import Field
from app.models.extraction import ExtractionModel


class AIUsageRecord(ExtractionModel):
    phase: str
    operation: str
    provider: str
    model: str | None = None
    mode: str
    input_reference: str | None = None
    output_reference: str | None = None
    timestamp: str
    network_used: bool | None
    notes: str | None = None


class AIUsageLog(ExtractionModel):
    project_id: str
    records: list[AIUsageRecord] = Field(default_factory=list)
    generated_at: str
