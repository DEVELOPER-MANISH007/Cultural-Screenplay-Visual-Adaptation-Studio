"""Research-provider boundary; curated local records are the offline implementation."""
from __future__ import annotations

from typing import Protocol

from app.models.cultural_evidence import CulturalEvidence, CulturalRetrievalResult, CulturalSource
from app.services.cultural_store import CulturalStore


class CulturalResearchProvider(Protocol):
    def search(self, query: str) -> list[CulturalSource]: ...
    def fetch(self, source: CulturalSource) -> CulturalSource: ...
    def extract_evidence(self, source: CulturalSource, query: str) -> list[CulturalEvidence]: ...


class CuratedResearchProvider:
    """Offline/manual research adapter; reads only reviewed source/evidence records."""

    def __init__(self, store: CulturalStore):
        self.store = store

    def search(self, query: str) -> list[CulturalSource]:
        tokens = [x.casefold() for x in query.split() if x]
        matched_ids = set()
        for item in self.store.evidence.values():
            corpus = f"{item.claim} {item.evidence_summary} {item.category} {item.scope or ''}".casefold()
            if not tokens or all(token in corpus for token in tokens):
                matched_ids.add(item.source_id)
        return [source for source in self.store.list_sources() if not matched_ids or source.source_id in matched_ids]

    def fetch(self, source: CulturalSource) -> CulturalSource:
        """Return the locally stored source metadata; never fetches remote content."""
        return self.store.get_source(source.source_id)

    def extract_evidence(self, source: CulturalSource, query: str) -> list[CulturalEvidence]:
        result = self.store.search_evidence(query=query)
        return [item for item in result.matched_evidence if item.source_id == source.source_id]


def research_with_provider(provider: CulturalResearchProvider, *, culture: str, region: str,
                           category: str | None = None, query: str = "") -> CulturalRetrievalResult:
    """Compose search/fetch/extract and turn unavailable providers into explicit warnings."""
    try:
        sources = provider.search(query)
        evidence = []
        for source in sources:
            stored_source = provider.fetch(source)
            evidence.extend(provider.extract_evidence(stored_source, query))
        unique = {item.evidence_id: item for item in evidence}
        selected = [item for item in unique.values()
                    if item.culture.casefold() == culture.casefold()
                    or (culture.casefold() == "marwari" and item.culture.casefold() == "rajasthan"
                        and item.scope == "Rajasthan-general")]
        if category:
            selected = [item for item in selected if item.category.casefold() == category.casefold()]
        warnings = []
        if any(item.scope == "Rajasthan-general" for item in selected):
            warnings.append("Some matches are Rajasthan-general and do not establish a Marwar-specific claim.")
        if not selected:
            warnings.append("No supported evidence matched; treat this topic as unknown until evidence is added.")
        return CulturalRetrievalResult(query=query, matched_evidence=selected, total_matches=len(selected), warnings=warnings)
    except Exception as exc:  # A missing network/provider never makes the UI unavailable.
        return CulturalRetrievalResult(query=query, matched_evidence=[], total_matches=0,
                                       warnings=[f"Research provider unavailable ({type(exc).__name__}); existing stored evidence remains available."])
