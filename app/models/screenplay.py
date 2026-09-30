"""Screenplay document model (Phase 1: ingestion output)."""

from __future__ import annotations

from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """Where the screenplay text came from."""

    TXT = "txt"
    DOCX = "docx"
    PDF = "pdf"
    PASTED_TEXT = "pasted_text"


class ExtractionStatus(str, Enum):
    """Outcome of text extraction."""

    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"


class ScreenplayDocument(BaseModel):
    """Raw screenplay text plus extraction metadata.

    This is the hand-off object for later phases: they should consume
    ``raw_text`` and never need to know how it was extracted.

    If ``extraction_status`` is ``failed``, ``extraction_warnings`` holds the
    failure message(s) and ``raw_text`` is empty.
    """

    document_id: str = Field(default_factory=lambda: uuid4().hex)
    filename: str | None = None
    source_type: SourceType
    raw_text: str = ""
    character_count: int = Field(default=0, ge=0)
    word_count: int = Field(default=0, ge=0)
    page_count: int | None = Field(default=None, ge=0)
    extraction_warnings: list[str] = Field(default_factory=list)
    extraction_status: ExtractionStatus = ExtractionStatus.SUCCESS
