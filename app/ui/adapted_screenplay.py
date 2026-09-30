"""Phase 6 UI for separate, approval-gated screenplay output."""
from __future__ import annotations

import streamlit as st

from app.models.adaptation import AdaptationChangeStatus
from app.models.adapted_screenplay import AdaptedScreenplay
from app.services.adaptation_store import AdaptationStore
from app.services.adapted_screenplay_store import AdaptedScreenplayStore
from app.services.adaptation_validator import validate_adapted_screenplay
from app.services.cultural_store import CulturalStore
from app.services.screenplay_adapter import adapt_persisted_screenplay
from app.ui.cultural_research import _store_for_context


def render_adapted_screenplay() -> None:
    st.header("6. Adapted Screenplay")
    st.caption("Only human-approved, evidence-validated changes are eligible. Approval never changes the original screenplay.")
    state = st.session_state.get("project_state")
    document = st.session_state.get("screenplay_document")
    if state is None:
        st.info("Load the Phase 3 project state before generating or reviewing its adapted screenplay.")
        return
    plan_store = AdaptationStore()
    output_store = AdaptedScreenplayStore()
    persisted_plan = None
    if plan_store.plan_exists(state.project_id):
        try:
            # Always read the plan from disk; do not trust the Phase 5 session copy.
            persisted_plan = plan_store.load_plan(state.project_id)
        except Exception as exc:
            st.error(f"Could not load persisted adaptation plan: {exc}")
            return
    plan_col, _ = st.columns([1, 2])
    with plan_col:
        if st.button("Load Persisted Adaptation Plan", key="phase6_load_persisted_adaptation_plan"):
            try:
                persisted_plan = plan_store.load_plan(state.project_id)
                st.session_state["phase6_plan_loaded_at"] = persisted_plan.updated_at
                st.success(f"Loaded persisted plan {persisted_plan.plan_id}, version {persisted_plan.version}.")
            except Exception as exc:
                st.error(f"Could not load persisted plan: {exc}")
    if persisted_plan is None:
        st.warning("A saved Phase 5 adaptation plan is required. Generate and save it in Phase 5.1 first.")
        return
    st.write({"Plan ID": persisted_plan.plan_id, "Plan version": persisted_plan.version,
              "Plan status": persisted_plan.status.value})
    approved = [c for c in persisted_plan.changes if c.status == AdaptationChangeStatus.APPROVED]
    rejected = [c for c in persisted_plan.changes if c.status == AdaptationChangeStatus.REJECTED]
    pending = [c for c in persisted_plan.changes if c.status in {
        AdaptationChangeStatus.PENDING, AdaptationChangeStatus.NEEDS_REVIEW,
        AdaptationChangeStatus.INSUFFICIENT_EVIDENCE, AdaptationChangeStatus.NEEDS_REVISION,
    }]
    st.write({"Approved changes": len(approved), "Rejected changes": len(rejected),
              "Pending / needs revision": len(pending)})

    saved_output = None
    if output_store.exists(state.project_id):
        try:
            saved_output = output_store.load_adapted_screenplay(state.project_id)
        except Exception as exc:
            st.error(f"Could not load saved adapted screenplay: {exc}")
    raw_original = document.raw_text if document is not None else ""
    if not raw_original and saved_output is not None:
        raw_original = saved_output.original_screenplay_text
    if raw_original:
        st.text_area("Original screenplay", value=raw_original, height=180, disabled=True,
                     key="phase6_original_screenplay_preview")
    else:
        raw_original = st.text_area("Original screenplay text (required)", height=220,
                                    key="phase6_original_screenplay_input",
                                    help="Paste or upload the original screenplay in Phase 1. This text is stored in the separate adapted-screenplay record and project.json is left untouched.")
    if not raw_original.strip():
        st.warning("Provide the original screenplay text before generating the adaptation.")

    evidence_store = _store_for_context(persisted_plan.culture, persisted_plan.region)
    try:
        evidence_store.load()
    except Exception as exc:
        st.error(f"Could not load the cultural evidence pack: {exc}")
        return
    generated: AdaptedScreenplay | None = st.session_state.get("adapted_screenplay")
    generate_col, save_col, load_col = st.columns(3)
    with generate_col:
        if st.button("Generate Adapted Screenplay", key="generate_adapted_screenplay", disabled=not bool(raw_original.strip())):
            try:
                generated = adapt_persisted_screenplay(
                    state, list(evidence_store.evidence.values()), raw_original,
                    plan_store=plan_store,
                )
                st.session_state["adapted_screenplay"] = generated
                st.session_state["phase6_source_text"] = raw_original
            except Exception as exc:
                st.error(f"Could not generate adapted screenplay: {exc}")
                return
    with save_col:
        if st.button("Save Adapted Screenplay", key="save_adapted_screenplay", disabled=generated is None):
            try:
                generated = output_store.save_adapted_screenplay(generated)
                st.session_state["adapted_screenplay"] = generated
                st.success(f"Saved separately to data/projects/{state.project_id}/adapted_screenplay.json")
            except Exception as exc:
                st.error(f"Could not save adapted screenplay: {exc}")
    with load_col:
        if st.button("Load Saved Adapted Screenplay", key="load_saved_adapted_screenplay", disabled=not output_store.exists(state.project_id)):
            try:
                generated = output_store.load_adapted_screenplay(state.project_id)
                st.session_state["adapted_screenplay"] = generated
                st.success(f"Reloaded adapted screenplay using plan version {generated.plan_version}.")
            except Exception as exc:
                st.error(f"Could not reload adapted screenplay: {exc}")
    generated = st.session_state.get("adapted_screenplay")
    if generated is None:
        return
    if generated.plan_id != persisted_plan.plan_id or generated.plan_version != persisted_plan.version:
        st.warning("This saved output was generated from a different plan version. Regenerate before relying on its review state.")
    validation = validate_adapted_screenplay(state, generated, persisted_plan, original_text=generated.original_screenplay_text,
                                               cultural_evidence=list(evidence_store.evidence.values()) if evidence_store else [])
    st.subheader("Validation")
    st.write({"Status": "Valid" if validation.valid else "Invalid",
              "Scenes checked": validation.checked_scene_count,
              "Applied changes": validation.applied_change_count})
    for error in validation.errors:
        st.error(error)
    for warning in validation.warnings:
        st.warning(warning)
    applied = set(generated.applied_change_ids)
    blocked = set(generated.blocked_change_ids)
    st.subheader("Change Review Summary")
    st.write({"Approved changes": len(approved), "Applied": len(applied),
              "Blocked": len(blocked), "Pending": len(pending), "Rejected": len(rejected),
              "Blocked IDs": sorted(blocked)})
    if generated.assumptions:
        with st.expander("Assumptions"):
            for assumption in generated.assumptions:
                st.write(f"- {assumption}")
    if generated.warnings:
        with st.expander("Adaptation warnings", expanded=True):
            for warning in generated.warnings:
                st.warning(warning)
    st.subheader("Scene-by-scene comparison")
    evidence_map = evidence_store.evidence
    change_map = {c.change_id: c for c in persisted_plan.changes}
    for scene in generated.scenes:
        with st.expander(f"{scene.scene_id} · Scene {scene.scene_number} · {scene.adapted_heading}"):
            st.markdown("**ORIGINAL**")
            st.code(scene.original_text, language=None)
            st.markdown("**ADAPTED**")
            st.code(scene.adapted_text, language=None)
            st.markdown("**APPLIED CHANGES**")
            if scene.applied_change_ids:
                for change_id in scene.applied_change_ids:
                    change = change_map.get(change_id)
                    st.write(f"{change_id}: {change.proposed_change if change else 'Change missing from current plan'}")
            else:
                st.write("None")
            st.markdown("**EVIDENCE**")
            if scene.evidence_ids:
                for evidence_id in scene.evidence_ids:
                    item = evidence_map.get(evidence_id)
                    if item:
                        st.markdown(f"{evidence_id}: {item.claim} · Scope: {item.scope}")
                        st.markdown(f"Source: [{item.source_title}]({item.source_url})")
                    else:
                        st.error(f"Missing evidence record: {evidence_id}")
            else:
                st.write("None")
            for warning in scene.warnings:
                st.warning(warning)
    with st.expander("Adapted screenplay JSON"):
        st.json(generated.model_dump(mode="json"))
