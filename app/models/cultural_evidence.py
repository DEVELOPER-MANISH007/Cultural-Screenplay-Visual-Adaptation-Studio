"""Provenance-first cultural knowledge models."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, HttpUrl, field_validator

from app.models.extraction import ExtractionModel


class CulturalEvidenceStatus(str, Enum):
    VERIFIED = "verified"
    PARTIALLY_SUPPORTED = "partially_supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class CulturalSourceType(str, Enum):
    GOVERNMENT = "government"
    MUSEUM = "museum"
    ACADEMIC = "academic"
    INSTITUTIONAL = "institutional"
    REPUTABLE_REFERENCE = "reputable_reference"
    OTHER = "other"


class CulturalSource(ExtractionModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: HttpUrl
    publisher: str = Field(min_length=1)
    source_type: CulturalSourceType
    region: str | None = None
    culture: str | None = None
    reliability_notes: str = Field(min_length=1)
    retrieved_at: str = Field(min_length=1)

    @field_validator("retrieved_at")
    @classmethod
    def valid_retrieved_at(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("retrieved_at must be ISO 8601") from exc
        return value


class CulturalEvidence(ExtractionModel):
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    culture: str = Field(min_length=1)
    dialect: str | None = None
    region: str | None = None
    category: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    evidence_summary: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_url: HttpUrl
    source_type: CulturalSourceType
    retrieved_at: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    scope: str | None = None
    notes: str | None = None
    status: CulturalEvidenceStatus
    conflict_group: str | None = None

    @field_validator("retrieved_at")
    @classmethod
    def valid_retrieved_at(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("retrieved_at must be ISO 8601") from exc
        return value


class LanguageEvidence(ExtractionModel):
    language_evidence_id: str = Field(min_length=1)
    culture: str = Field(min_length=1)
    dialect: str = Field(min_length=1)
    phrase: str | None = None
    meaning: str | None = None
    context: str | None = None
    source_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    regional_scope: str | None = None
    status: CulturalEvidenceStatus
    notes: str | None = None


class CulturalRetrievalResult(ExtractionModel):
    query: str
    matched_evidence: list[CulturalEvidence] = Field(default_factory=list)
    total_matches: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
