"""Phase 4 cultural research UI; this panel never edits screenplay content."""
from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from app.config import get_settings
from app.models.cultural_evidence import CulturalEvidence, CulturalSourceType
from app.services.cultural_pack import seed_marwari_marwar_pack
from app.services.cultural_research import CuratedResearchProvider, research_with_provider
from app.services.cultural_store import CulturalStore, SOURCE_PRIORITY


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _store_for_context(culture: str, region: str) -> CulturalStore:
    region_name = re.split(r"[/,]", region, maxsplit=1)[0].strip()
    pack_id = f"{_slug(culture)}_{_slug(region_name)}"
    root = Path(__file__).resolve().parents[2] / "data" / "culture" / pack_id
    return CulturalStore(root=root, culture=culture, region=region)


def _render_evidence_card(item: CulturalEvidence) -> None:
    st.markdown(f"**Claim:** {item.claim}")
    st.caption(f"Category: {item.category} · Scope: {item.scope or 'unspecified'} · Status: {item.status.value} · Confidence: {item.confidence:.2f}")
    st.markdown(f"**Evidence summary:** {item.evidence_summary}")
    if item.notes:
        st.caption(f"Notes: {item.notes}")
    st.markdown(f"**Source:** [{item.source_title}]({item.source_url}) · `{item.source_id}`")


def render_cultural_research() -> None:
    st.header("4. Cultural Research")
    settings = get_settings()
    st.caption("Evidence-backed research only. This panel does not rewrite the screenplay.")
    context_col1, context_col2 = st.columns(2)
    with context_col1:
        culture = st.text_input("Culture", value=settings.research_culture, key="research_culture")
        region = st.text_input("Region", value=settings.research_region, key="research_region")
        setting = st.text_input("Setting", value=settings.research_setting, key="research_setting")
    with context_col2:
        dialect = st.text_input("Dialect", value=settings.research_dialect, key="research_dialect")
        script = st.text_input("Script", value=settings.research_script, key="research_script")
        st.info("Model inference is not cultural evidence. General Rajasthan records remain labeled as Rajasthan-general.")
    st.write({"Selected Cultural Context": {"Culture": culture, "Dialect": dialect or "Not specified",
                                             "Region": region, "Setting": setting, "Script": script}})
    store = _store_for_context(culture, region)
    try:
        store.load()
    except Exception as exc:
        st.error(f"Could not load the cultural evidence pack: {exc}")
        return

    if st.button("Research Cultural Context", key="research_cultural_context"):
        provider = CuratedResearchProvider(store)
        result = research_with_provider(provider, culture=culture, region=region)
        st.session_state["cultural_research_result"] = result
        st.session_state["cultural_research_pack_id"] = store.root.name
        st.session_state["cultural_research_ran"] = True
    if not st.session_state.get("cultural_research_ran"):
        st.info("Click Research Cultural Context to load the reviewed local source pack. The current provider works offline and does not perform a live web search.")
        return

    st.success(f"Loaded {len(store.sources)} sources and {len(store.evidence)} curated evidence records from the local pack.")
    filters1, filters2, filters3, filters4 = st.columns(4)
    categories = ["All categories"] + sorted({item.category for item in store.evidence.values()})
    with filters1:
        category_choice = st.selectbox("Category", categories, key="research_category_filter")
    with filters2:
        source_types = ["All source types"] + [item.value for item in CulturalSourceType]
        source_type_choice = st.selectbox("Source type", source_types, key="research_source_type_filter")
    with filters3:
        confidence_floor = st.slider("Minimum confidence", min_value=0.0, max_value=1.0, value=0.0, step=0.05, key="research_confidence_filter")
    with filters4:
        region_choices = ["All scopes", region, "Rajasthan-general"]
        region_choice = st.selectbox("Region / scope", list(dict.fromkeys(region_choices)), key="research_region_filter")
    query = st.text_input("Search cultural evidence", placeholder="bandhej textiles, folk music, Jodhpur architecture, greeting, food", key="research_query")
    result = store.search_evidence(
        culture=culture, region=None if region_choice == "All scopes" else (region if region_choice == region else None),
        category=None if category_choice == "All categories" else category_choice,
        query=query, source_type=None if source_type_choice == "All source types" else source_type_choice,
        min_confidence=confidence_floor,
    )
    if region_choice == "Rajasthan-general":
        result.matched_evidence = [item for item in result.matched_evidence if item.scope == "Rajasthan-general"]
        result.total_matches = len(result.matched_evidence)
    st.subheader("Categories")
    all_categories = ["regional_context", "language", "clothing", "grooming", "jewellery", "food", "architecture", "interiors",
                      "gestures", "greetings", "kinship", "honorifics", "social_behavior", "rituals", "festivals",
                      "music", "dance", "transport", "landscape", "props", "textiles", "occupations", "soundscape"]
    counts = {name: sum(item.category == name for item in store.evidence.values()) for name in all_categories}
    st.write({name: (f"{count} evidence record(s)" if count else "Unknown / insufficient evidence") for name, count in counts.items()})

    st.subheader("Sources")
    for source in store.list_sources():
        with st.expander(f"{source.title} · priority tier {SOURCE_PRIORITY[source.source_type]}"):
            st.markdown(f"[{source.url}]({source.url})")
            st.write({"Publisher": source.publisher, "Type": source.source_type.value,
                      "Region": source.region, "Culture": source.culture,
                      "Reliability notes": source.reliability_notes, "Retrieved at": source.retrieved_at})

    st.subheader(f"Evidence ({result.total_matches} matches)")
    if result.warnings:
        with st.expander("Warnings", expanded=True):
            for warning in result.warnings:
                st.warning(warning)
    for item in result.matched_evidence:
        with st.container(border=True):
            _render_evidence_card(item)

    with st.expander("Language evidence"):
        if store.language_evidence:
            for item in store.language_evidence.values():
                st.markdown(f"**Status:** {item.status.value} · confidence {item.confidence:.2f}")
                st.markdown(f"**Phrase:** {item.phrase or 'Unknown'} · **Meaning:** {item.meaning or 'Unknown'}")
                st.write(item.notes)
                if item.source_id:
                    source = store.get_source(item.source_id)
                    st.markdown(f"**Source:** [{source.title}]({source.url})")
        else:
            st.info("No source-backed language phrases are stored.")
