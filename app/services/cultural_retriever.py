"""Deterministic cultural evidence retrieval; semantic backends can implement this contract later."""
from __future__ import annotations

from app.models.cultural_evidence import CulturalEvidenceStatus, CulturalRetrievalResult, CulturalSourceType
from app.services.cultural_store import CulturalStore


class CulturalRetriever:
    """Keyword/category retriever returning structured, provenance-preserving matches."""

    def __init__(self, store: CulturalStore):
        self.store = store

    def search_evidence(
        self, *, culture: str, region: str | None = None, category: str | None = None,
        query: str = "", source_type: CulturalSourceType | str | None = None,
        min_confidence: float = 0.0, status: CulturalEvidenceStatus | str | None = None,
    ) -> CulturalRetrievalResult:
        return self.store.search_evidence(
            culture=culture, region=region, category=category, query=query,
            source_type=source_type, min_confidence=min_confidence, status=status,
        )
