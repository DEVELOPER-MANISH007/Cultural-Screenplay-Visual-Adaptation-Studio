"""Streamlit UI for Phase 1: screenplay input, extraction preview and validation.

UI only: all extraction and validation logic lives in ``app.services``.
Nothing here sends text to any AI service.
"""

from __future__ import annotations

import streamlit as st

from app.models.screenplay import ExtractionStatus, ScreenplayDocument
from app.services.ingestion import extract_text
from app.services.validators import (
    UnsupportedFileTypeError,
    ValidationResult,
    validate_screenplay,
)

ACCEPTED_EXTENSIONS = ["txt", "docx", "pdf"]
FAILED_PREFIX = "Extraction failed: "


def _render_information(document: ScreenplayDocument) -> None:
    st.subheader("Screenplay Information")
    info = {
        "Filename": document.filename or "N/A (pasted text)",
        "Source type": document.source_type.value,
        "Word count": str(document.word_count),
        "Character count": str(document.character_count),
        "Page count": "N/A" if document.page_count is None else str(document.page_count),
        "Extraction status": document.extraction_status.value,
    }
    st.table({"Field": list(info.keys()), "Value": list(info.values())})

    show = st.error if document.extraction_status == ExtractionStatus.FAILED else st.warning
    for message in document.extraction_warnings:
        show(message)


def _render_validation(result: ValidationResult, document: ScreenplayDocument) -> None:
    """Show validation results, skipping messages already shown as extraction notes."""
    already_shown = set(document.extraction_warnings)
    for error in result.errors:
        if error.removeprefix(FAILED_PREFIX) not in already_shown:
            st.error(error)
    for warning in result.warnings:
        if warning not in already_shown:
            st.warning(warning)

    if not result.is_valid:
        st.error("Screenplay is not valid. Please fix the issues above before continuing.")
    elif result.warnings:
        st.success("Screenplay is valid, with warnings. Please review them above.")
    else:
        st.success("Screenplay is valid.")
    st.caption("Nothing has been sent to any AI service.")


def _render_document(document: ScreenplayDocument, key: str) -> None:
    st.session_state["screenplay_document"] = document
    _render_information(document)

    with st.expander("Extracted Screenplay", expanded=True):
        if document.raw_text:
            st.text_area(
                "Extracted text",
                value=document.raw_text,
                height=400,
                disabled=True,
                label_visibility="collapsed",
            )
        else:
            st.info("No text was extracted.")

    if st.button("Validate Screenplay", key=f"validate_{key}"):
        _render_validation(validate_screenplay(document), document)


def _render_upload_tab() -> None:
    uploaded = st.file_uploader(
        "Upload a screenplay (.txt, .docx or .pdf)",
        type=ACCEPTED_EXTENSIONS,
        key="screenplay_upload",
    )
    if uploaded is None:
        st.info("Choose a file to extract its text.")
        return
    try:
        document = extract_text(uploaded.getvalue(), uploaded.name)
    except UnsupportedFileTypeError as exc:
        st.error(str(exc))
        return
    _render_document(document, "upload")


def _render_paste_tab() -> None:
    text = st.text_area("Paste screenplay text", height=250, key="screenplay_paste")
    if not text:
        st.info("Paste your screenplay above to see the extracted text.")
        return
    _render_document(extract_text(text), "paste")


def render_screenplay_input() -> None:
    """Render section '1. Screenplay Input'."""
    st.header("1. Screenplay Input")
    st.caption("Inspect the extracted text before any later processing.")
    upload_tab, paste_tab = st.tabs(["Upload File", "Paste Text"])
    with upload_tab:
        _render_upload_tab()
    with paste_tab:
        _render_paste_tab()


def render_extraction() -> None:
    """Render Phase 2 extraction separately from the original screenplay text."""
    st.header("2. AI Screenplay Extraction")
    st.caption("Create a separate structured representation. The original text is unchanged.")
    document = st.session_state.get("screenplay_document")
    if document is None or not document.raw_text.strip():
        st.info("Provide screenplay text in Phase 1 before extraction.")
        return
    provider_name = st.selectbox("Extraction provider", ["MockLLMProvider"], key="extraction_provider")
    if st.button("Extract Screenplay Structure"):
        from app.services.extractor import extract_screenplay
        from app.services.llm_provider import MockLLMProvider
        try:
            result = extract_screenplay(document, MockLLMProvider())
        except Exception as exc:
            st.error(f"Extraction failed: {exc}")
            return
        st.session_state["screenplay_extraction"] = result
    result = st.session_state.get("screenplay_extraction")
    if result is None:
        return
    st.subheader("Extraction Summary")
    st.write({"Scenes": len(result.scenes), "Characters": len(result.characters),
              "Locations": len(result.locations), "Production elements": len(result.production_elements),
              "Continuity records": len(result.continuity_states)})
    for warning in result.extraction_warnings:
        st.warning(warning)
    for label, records in [("Scenes", result.scenes), ("Characters", result.characters),
                           ("Locations", result.locations), ("Production Elements", result.production_elements),
                           ("Continuity", result.continuity_states)]:
        with st.expander(label):
            st.dataframe([item.model_dump(mode="json") for item in records], use_container_width=True)
    with st.expander("Complete extraction JSON"):
        st.json(result.model_dump(mode="json"))
