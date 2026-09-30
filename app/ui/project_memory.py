"""Phase 3 Project Memory UI. Persistence is delegated to ProjectStore."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.models.project_state import ProjectState
from app.services.normalizer import build_project_state
from app.services.project_store import ProjectStore


def _ensure_state() -> ProjectState | None:
    extraction = st.session_state.get("screenplay_extraction")
    document = st.session_state.get("screenplay_document")
    if extraction is None:
        return None
    state: ProjectState | None = st.session_state.get("project_state")
    if state is None or state.screenplay_id != extraction.screenplay_id:
        project = st.session_state.get("project")
        source_filename = document.filename if document is not None else None
        title = project.title if project is not None else (Path(source_filename).stem if source_filename else "Untitled Screenplay")
        state = build_project_state(
            extraction, title=title,
            project_id=project.project_id if project is not None else None,
            source_filename=source_filename,
            culture=project.culture or None if project is not None else None,
            dialect=project.dialect or None if project is not None else None,
            region=project.region or None if project is not None else None,
            setting=project.setting or None if project is not None else None,
            script=project.script or None if project is not None else None,
        )
        st.session_state["project_state"] = state
    return state


def _entity_rows(items, *, id_field: str, name_field: str, alias_field: str | None, scenes_field: str):
    rows = []
    for item in items:
        rows.append({
            "Canonical ID": getattr(item, id_field),
            "Canonical name": getattr(item, name_field),
            "Aliases": ", ".join(getattr(item, alias_field) or []) if alias_field else "",
            "Scene references": ", ".join(getattr(item, scenes_field) or []),
        })
    return rows


def render_project_memory() -> None:
    st.header("3. Project Memory")
    state = _ensure_state()
    store = ProjectStore()
    if state is None:
        st.info("Extract screenplay structure in Phase 2 to create project memory.")
        return

    st.subheader("Project State Summary")
    st.write({
        "Project ID": state.project_id,
        "Version": state.version,
        "State status": state.state_status.value,
        "Scenes": len(state.scenes),
        "Characters": len(state.characters),
        "Locations": len(state.locations),
        "Production elements": len(state.production_elements),
        "Last updated": state.updated_at,
    })

    save_col, load_col, view_col = st.columns(3)
    with save_col:
        if st.button("Save Project State"):
            try:
                state = store.save_project(state)
                st.session_state["project_state"] = state
                st.success(f"Project state saved (version {state.version}).")
            except Exception as exc:  # show persistence failures without discarding session data
                st.error(f"Could not save project state: {exc}")
    with load_col:
        project_id = st.text_input("Project ID to load", value=state.project_id, key="project_memory_load_id")
        if st.button("Load Project State"):
            try:
                state = store.load_project(project_id.strip())
                st.session_state["project_state"] = state
                st.success(f"Loaded project state version {state.version}.")
            except Exception as exc:
                st.error(f"Could not load project state: {exc}")
    with view_col:
        if st.button("View Canonical Entities", key="view_canonical_entities"):
            st.session_state["show_canonical_entities"] = True

    state = st.session_state.get("project_state", state)
    if state.normalization_warnings:
        with st.expander("Normalization Warnings", expanded=True):
            for warning in state.normalization_warnings:
                st.warning(warning)

    if st.session_state.get("show_canonical_entities"):
        with st.expander("Characters"):
            st.dataframe(_entity_rows(state.characters, id_field="character_id", name_field="canonical_name", alias_field="aliases", scenes_field="scene_ids"), use_container_width=True)
        with st.expander("Locations"):
            st.dataframe(_entity_rows(state.locations, id_field="location_id", name_field="canonical_name", alias_field="aliases", scenes_field="scenes"), use_container_width=True)
        with st.expander("Production Elements"):
            rows = _entity_rows(state.production_elements, id_field="element_id", name_field="name", alias_field=None, scenes_field="scenes")
            for row, element in zip(rows, state.production_elements):
                row["Category"] = element.category
            st.dataframe(rows, use_container_width=True)
        with st.expander("Continuity State"):
            st.dataframe([item.model_dump(mode="json") for item in state.continuity_states], use_container_width=True)
