"""Validated JSON persistence for cultural source and evidence records."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from app.models.cultural_evidence import (
    CulturalEvidence, CulturalEvidenceStatus, CulturalSource, CulturalSourceType,
    LanguageEvidence,
)


SOURCE_PRIORITY = {
    CulturalSourceType.GOVERNMENT: 1,
    CulturalSourceType.INSTITUTIONAL: 1,
    CulturalSourceType.MUSEUM: 2,
    CulturalSourceType.ACADEMIC: 3,
    CulturalSourceType.REPUTABLE_REFERENCE: 4,
    CulturalSourceType.OTHER: 5,
}


class CulturalStoreError(ValueError):
    pass


class CulturalStore:
    def __init__(self, root: str | Path | None = None, *, culture: str = "Marwari", region: str = "Marwar / Jodhpur"):
        if root is None:
            root = Path(__file__).resolve().parents[2] / "data" / "culture" / "marwari_marwar"
        self.root = Path(root)
        self.sources_path = self.root / "sources.json"
        self.evidence_path = self.root / "evidence.json"
        self.language_path = self.root / "language_evidence.json"
        self.culture = culture
        self.region = region
        self.sources: dict[str, CulturalSource] = {}
        self.evidence: dict[str, CulturalEvidence] = {}
        self.language_evidence: dict[str, LanguageEvidence] = {}
        self.warnings: list[str] = []

    def add_source(self, source: CulturalSource) -> CulturalSource:
        current = self.sources.get(source.source_id)
        if current is not None:
            if current == source:
                return current
            raise CulturalStoreError(f"source ID already exists with different content: {source.source_id}")
        for other in self.sources.values():
            if str(other.url) == str(source.url) and other != source:
                raise CulturalStoreError(f"source URL already stored under {other.source_id}; preserve the existing source record")
        self.sources[source.source_id] = source
        return source

    def add_evidence(self, evidence: CulturalEvidence) -> CulturalEvidence:
        if evidence.source_id not in self.sources:
            raise CulturalStoreError(f"evidence {evidence.evidence_id} references unknown source {evidence.source_id}")
        current = self.evidence.get(evidence.evidence_id)
        if current is not None:
            if current == evidence:
                return current
            raise CulturalStoreError(f"evidence ID already exists with different content: {evidence.evidence_id}")
        duplicate = next((item for item in self.evidence.values() if
                          item.source_id == evidence.source_id and item.culture.casefold() == evidence.culture.casefold()
                          and (item.region or "").casefold() == (evidence.region or "").casefold()
                          and item.category.casefold() == evidence.category.casefold()
                          and item.claim.casefold() == evidence.claim.casefold()), None)
        if duplicate is not None:
            self.warnings.append(f"Duplicate evidence ignored: {evidence.evidence_id} duplicates {duplicate.evidence_id} from the same source.")
            return duplicate
        self.evidence[evidence.evidence_id] = evidence
        self._refresh_conflict_warnings()
        return evidence

    def add_language_evidence(self, item: LanguageEvidence) -> LanguageEvidence:
        if item.source_id and item.source_id not in self.sources:
            raise CulturalStoreError(f"language evidence references unknown source {item.source_id}")
        current = self.language_evidence.get(item.language_evidence_id)
        if current is not None and current != item:
            raise CulturalStoreError(f"language evidence ID already exists: {item.language_evidence_id}")
        self.language_evidence[item.language_evidence_id] = item
        return item

    def get_source(self, source_id: str) -> CulturalSource:
        return self.sources[source_id]

    def get_evidence(self, evidence_id: str) -> CulturalEvidence:
        return self.evidence[evidence_id]

    def list_evidence(self, *, category: str | None = None) -> list[CulturalEvidence]:
        values = list(self.evidence.values())
        if category:
            values = [item for item in values if item.category.casefold() == category.casefold()]
        return sorted(values, key=lambda item: item.evidence_id)

    def list_sources(self) -> list[CulturalSource]:
        return sorted(self.sources.values(), key=lambda source: (SOURCE_PRIORITY[source.source_type], source.title.casefold(), source.source_id))

    def search_evidence(self, *, culture: str | None = None, region: str | None = None,
                        category: str | None = None, query: str = "", source_type: CulturalSourceType | str | None = None,
                        min_confidence: float = 0.0, status: CulturalEvidenceStatus | str | None = None):
        from app.models.cultural_evidence import CulturalRetrievalResult
        matches = []
        tokens = [token.casefold() for token in query.split() if token.strip()]
        for evidence in self.evidence.values():
            if culture and evidence.culture.casefold() != culture.casefold() and not (
                culture.casefold() == "marwari"
                and evidence.culture.casefold() == "rajasthan"
                and evidence.scope == "Rajasthan-general"
            ):
                continue
            if region and evidence.region and evidence.region.casefold() != region.casefold():
                continue
            if region and evidence.region is None and evidence.scope != "Rajasthan-general":
                continue
            if category and evidence.category.casefold() != category.casefold():
                continue
            if evidence.confidence < min_confidence:
                continue
            if status and evidence.status.value != (status.value if isinstance(status, CulturalEvidenceStatus) else status):
                continue
            source = self.sources[evidence.source_id]
            if source_type and source.source_type.value != (source_type.value if isinstance(source_type, CulturalSourceType) else source_type):
                continue
            corpus = " ".join((evidence.claim, evidence.evidence_summary, evidence.category,
                               evidence.scope or "", evidence.notes or "")).casefold()
            if tokens and not all(token in corpus for token in tokens):
                continue
            matches.append(evidence)
        matches.sort(key=lambda item: (-item.confidence, SOURCE_PRIORITY[self.sources[item.source_id].source_type], item.evidence_id))
        warnings = list(self._refresh_conflict_warnings())
        if not matches:
            warnings.append("No supported evidence matched this query; treat the topic as unknown until evidence is added.")
        if any(item.scope == "Rajasthan-general" for item in matches):
            warnings.append("Some matches are Rajasthan-general and do not establish a Marwar-specific claim.")
        return CulturalRetrievalResult(query=query, matched_evidence=matches, total_matches=len(matches), warnings=list(dict.fromkeys(warnings)))

    def _refresh_conflict_warnings(self) -> list[str]:
        grouped: dict[str, list[CulturalEvidence]] = {}
        for item in self.evidence.values():
            if item.conflict_group:
                grouped.setdefault(item.conflict_group, []).append(item)
        warnings = []
        for group in grouped.values():
            if len({item.claim for item in group}) > 1:
                warning = "Cultural evidence conflict: " + "; ".join(
                    f"{item.evidence_id} ({item.source_title}) claims {item.claim!r}" for item in sorted(group, key=lambda x: x.evidence_id)
                )
                warnings.append(warning)
        self.warnings = warnings
        return warnings

    def save(self) -> None:
        for item in self.evidence.values():
            if item.source_id not in self.sources:
                raise CulturalStoreError(f"cannot save evidence with missing source: {item.evidence_id}")
        self.root.mkdir(parents=True, exist_ok=True)
        self._write(self.sources_path, [item.model_dump(mode="json") for item in self.list_sources()])
        self._write(self.evidence_path, [item.model_dump(mode="json") for item in self.list_evidence()])
        self._write(self.language_path, [item.model_dump(mode="json") for item in sorted(self.language_evidence.values(), key=lambda x: x.language_evidence_id)])

    def load(self) -> "CulturalStore":
        try:
            sources = [CulturalSource.model_validate(x) for x in self._read(self.sources_path)]
            evidence = [CulturalEvidence.model_validate(x) for x in self._read(self.evidence_path)]
            language = [LanguageEvidence.model_validate(x) for x in self._read(self.language_path)]
        except (ValueError, TypeError, OSError) as exc:
            raise CulturalStoreError(f"could not load cultural pack at {self.root}: {exc}") from exc
        source_ids = [item.source_id for item in sources]
        evidence_ids = [item.evidence_id for item in evidence]
        if len(source_ids) != len(set(source_ids)) or len(evidence_ids) != len(set(evidence_ids)):
            raise CulturalStoreError("cultural pack contains duplicate IDs")
        known = set(source_ids)
        if any(item.source_id not in known for item in evidence):
            raise CulturalStoreError("cultural evidence references a missing source")
        if any(item.source_id and item.source_id not in known for item in language):
            raise CulturalStoreError("language evidence references a missing source")
        self.sources = {item.source_id: item for item in sources}
        self.evidence = {item.evidence_id: item for item in evidence}
        self.language_evidence = {item.language_evidence_id: item for item in language}
        self._refresh_conflict_warnings()
        return self

    @staticmethod
    def _read(path: Path) -> list[dict]:
        if not path.exists():
            return []
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise CulturalStoreError(f"expected a JSON array in {path}")
        return value

    @staticmethod
    def _write(path: Path, items: list[dict]) -> None:
        text = json.dumps(items, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent,
                                             prefix=".cultural-", suffix=".tmp", delete=False) as handle:
                temp_name = handle.name
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
            raise
