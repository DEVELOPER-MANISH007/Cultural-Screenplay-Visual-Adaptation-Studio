import json

import pytest
from pydantic import ValidationError

from app.models.cultural_evidence import (
    CulturalEvidence, CulturalEvidenceStatus, CulturalSource, CulturalSourceType,
    LanguageEvidence,
)
from app.services.cultural_pack import seed_marwari_marwar_pack
from app.services.cultural_research import CuratedResearchProvider, research_with_provider
from app.services.cultural_store import CulturalStore, CulturalStoreError


def source(source_id="SRC_TEST", *, title="Test Source", url="https://example.org/source"):
    return CulturalSource(source_id=source_id, title=title, url=url, publisher="Test Institution",
                          source_type=CulturalSourceType.INSTITUTIONAL, region="Marwar",
                          culture="Marwari", reliability_notes="A test institutional source.",
                          retrieved_at="2026-09-29T10:00:00+00:00")


def evidence(source_obj, evidence_id="EVID_TEST", *, claim="A supported test claim.", category="clothing",
             confidence=0.8, scope="Marwar-specific", status=CulturalEvidenceStatus.VERIFIED,
             conflict_group=None, culture="Marwari", region="Marwar"):
    return CulturalEvidence(evidence_id=evidence_id, source_id=source_obj.source_id, culture=culture,
                            dialect=None, region=region, category=category, claim=claim,
                            evidence_summary="A source summary supporting this narrow claim.",
                            source_title=source_obj.title, source_url=source_obj.url,
                            source_type=source_obj.source_type, retrieved_at=source_obj.retrieved_at,
                            confidence=confidence, scope=scope, notes=None, status=status,
                            conflict_group=conflict_group)


def test_cultural_source_and_evidence_models_validate_provenance_and_bounds():
    src = source()
    item = evidence(src)
    assert item.status == CulturalEvidenceStatus.VERIFIED
    assert item.source_id == src.source_id
    with pytest.raises(ValidationError):
        CulturalSource(source_id="x", title="bad", url="not-a-url", publisher="x",
                       source_type="other", reliability_notes="n", retrieved_at="today")
    with pytest.raises(ValidationError):
        evidence(src, confidence=1.1)
    with pytest.raises(ValidationError):
        CulturalEvidence(evidence_id="bad", source_id="s", culture="Marwari", category="", claim="",
                         evidence_summary="", source_title="", source_url="not url", source_type="bad",
                         retrieved_at="bad", confidence=-1, status="bad")


def test_language_phrase_can_be_marked_insufficient_without_inventing_a_phrase():
    item = LanguageEvidence(language_evidence_id="LANG_001", culture="Marwari", dialect="Marwari",
                            phrase=None, meaning=None, context=None, source_id=None, confidence=0.0,
                            regional_scope="Marwar / Jodhpur", status="insufficient_evidence",
                            notes="No sourced phrase available.")
    assert item.phrase is None and item.status == CulturalEvidenceStatus.INSUFFICIENT_EVIDENCE


def test_evidence_requires_existing_source_and_preserves_source_provenance(tmp_path):
    store = CulturalStore(tmp_path)
    src = source()
    with pytest.raises(CulturalStoreError, match="unknown source"):
        store.add_evidence(evidence(src))
    store.add_source(src)
    item = store.add_evidence(evidence(src))
    assert item.source_id == "SRC_TEST"
    assert item.source_title == "Test Source"
    assert str(item.source_url) == str(src.url)


def test_store_round_trip_sources_evidence_and_language_records(tmp_path):
    store = CulturalStore(tmp_path)
    src = source()
    store.add_source(src)
    store.add_evidence(evidence(src))
    store.add_language_evidence(LanguageEvidence(language_evidence_id="LANG_1", culture="Marwari", dialect="Marwari",
        phrase=None, meaning=None, context=None, source_id=src.source_id, confidence=0.2,
        regional_scope="Rajasthan-general", status="insufficient_evidence", notes="No phrase evidence."))
    store.save()
    assert json.loads((tmp_path / "sources.json").read_text())[0]["source_id"] == "SRC_TEST"
    restored = CulturalStore(tmp_path).load()
    assert restored.get_source("SRC_TEST") == src
    assert restored.get_evidence("EVID_TEST") == store.get_evidence("EVID_TEST")
    assert restored.language_evidence["LANG_1"].phrase is None


def test_duplicate_source_and_evidence_are_idempotent_but_conflicting_ids_reject(tmp_path):
    store = CulturalStore(tmp_path)
    src = source()
    store.add_source(src)
    assert store.add_source(src) == src
    item = evidence(src)
    assert store.add_evidence(item) == item
    assert store.add_evidence(item) == item
    assert len(store.evidence) == 1
    with pytest.raises(CulturalStoreError):
        store.add_source(source(title="different title"))
    with pytest.raises(CulturalStoreError):
        store.add_evidence(evidence(src, claim="A different claim."))


def test_conflicting_claims_are_retained_and_warned(tmp_path):
    store = CulturalStore(tmp_path)
    a = source("SRC_A", title="Source A", url="https://example.org/a")
    b = source("SRC_B", title="Source B", url="https://example.org/b")
    store.add_source(a)
    store.add_source(b)
    store.add_evidence(evidence(a, "EVID_A", claim="The custom is described as occurring in spring.", conflict_group="custom-season"))
    store.add_evidence(evidence(b, "EVID_B", claim="The custom is described as occurring in autumn.", conflict_group="custom-season"))
    result = store.search_evidence(culture="Marwari")
    assert len(store.evidence) == 2
    assert "EVID_A" in result.warnings[0] and "EVID_B" in result.warnings[0]
    assert "Source A" in result.warnings[0] and "Source B" in result.warnings[0]


def test_deterministic_retrieval_filters_category_region_and_confidence(tmp_path):
    store = CulturalStore(tmp_path)
    src = source()
    store.add_source(src)
    store.add_evidence(evidence(src, "EVID_CLOTH", claim="Jodhpur bandhej textiles are listed.", category="clothing", confidence=0.8))
    store.add_evidence(evidence(src, "EVID_FOOD", claim="Statewide millet food information.", category="food", confidence=0.7,
                                culture="Rajasthan", region=None, scope="Rajasthan-general", status="partially_supported"))
    assert [x.evidence_id for x in store.search_evidence(culture="Marwari", region="Marwar", category="clothing").matched_evidence] == ["EVID_CLOTH"]
    broad = store.search_evidence(culture="Marwari", region="Marwar", category="food")
    assert broad.matched_evidence[0].evidence_id == "EVID_FOOD"
    assert any("Rajasthan-general" in warning for warning in broad.warnings)
    assert store.search_evidence(culture="Marwari", category="clothing", min_confidence=0.9).total_matches == 0
    assert store.search_evidence(query="bandhej", category="clothing").total_matches == 1
    assert store.search_evidence(source_type="academic").total_matches == 0


def test_unmatched_evidence_is_explicitly_unknown(tmp_path):
    result = CulturalStore(tmp_path).search_evidence(culture="Marwari", query="greeting phrase")
    assert result.total_matches == 0
    assert any("unknown" in warning for warning in result.warnings)


def test_research_abstraction_works_offline_and_handles_provider_failure(tmp_path):
    store = CulturalStore(tmp_path)
    seed_marwari_marwar_pack(store, save=True)
    offline = research_with_provider(CuratedResearchProvider(store), culture="Marwari", region="Marwar / Jodhpur")
    assert offline.total_matches >= 6
    assert all(item.source_id in store.sources for item in offline.matched_evidence)

    class UnavailableProvider:
        def search(self, query):
            raise ConnectionError("offline")
        def fetch(self, source):
            raise AssertionError("not reached")
        def extract_evidence(self, source, query):
            raise AssertionError("not reached")

    failed = research_with_provider(UnavailableProvider(), culture="Marwari", region="Marwar / Jodhpur")
    assert failed.total_matches == 0
    assert "provider unavailable" in failed.warnings[0]


def test_starter_pack_has_real_sources_and_precise_scopes(tmp_path):
    store = seed_marwari_marwar_pack(CulturalStore(tmp_path), save=True)
    assert len(store.sources) >= 5
    assert {item.category for item in store.evidence.values()} >= {"regional_context", "clothing", "textiles", "music", "dance", "landscape", "rituals"}
    generic = [item for item in store.evidence.values() if item.scope == "Rajasthan-general"]
    assert generic and all(item.culture == "Rajasthan" for item in generic)
    assert all(str(item.source_url).startswith("https://") for item in store.evidence.values())
    assert store.language_evidence["LANG_001"].status == CulturalEvidenceStatus.INSUFFICIENT_EVIDENCE


def test_conflicting_evidence_round_trips_without_overwrite(tmp_path):
    store = CulturalStore(tmp_path)
    for sid in ("SRC_A", "SRC_B"):
        store.add_source(source(sid, title=sid, url=f"https://example.org/{sid.lower()}"))
    store.add_evidence(evidence(store.get_source("SRC_A"), "EVID_A", claim="Claim A", conflict_group="g"))
    store.add_evidence(evidence(store.get_source("SRC_B"), "EVID_B", claim="Claim B", conflict_group="g"))
    store.save()
    restored = CulturalStore(tmp_path).load()
    assert set(restored.evidence) == {"EVID_A", "EVID_B"}
    assert any("Cultural evidence conflict" in warning for warning in restored.warnings)


def test_statewide_evidence_is_not_mislabelled_for_other_cultures(tmp_path):
    store = CulturalStore(tmp_path)
    src = source()
    store.add_source(src)
    store.add_evidence(evidence(src, culture="Rajasthan", region=None, scope="Rajasthan-general", status="partially_supported"))
    assert store.search_evidence(culture="Marwari").total_matches == 1
    assert store.search_evidence(culture="Punjabi").total_matches == 0


def test_cultural_retriever_returns_structured_results(tmp_path):
    from app.services.cultural_retriever import CulturalRetriever
    store = seed_marwari_marwar_pack(CulturalStore(tmp_path))
    result = CulturalRetriever(store).search_evidence(
        culture="Marwari", region="Marwar / Jodhpur", category="clothing", query="bandhej"
    )
    assert result.total_matches == 1
    assert result.matched_evidence[0].evidence_id == "EVID_005"
