"""Streamlit panel for Phase 7 structured visual production specifications."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from app.services.adaptation_store import AdaptationStore
from app.services.adapted_screenplay_store import AdaptedScreenplayStore
from app.services.cultural_store import CulturalStore
from app.services.visual_continuity_validator import validate_visual_pack
from app.services.visual_pack_generator import MockVisualPackGenerator
from app.services.visual_pack_store import VisualPackStore
from app.ui.cultural_research import _store_for_context


def render_visual_production_pack() -> None:
    st.header("7. Visual Production Pack")
    st.caption("Structured, evidence-traceable visual specifications. No images are generated in Phase 7.")
    state = st.session_state.get("project_state")
    if state is None:
        st.info("Load the Phase 3 project state before generating or validating a visual pack.")
        return

    st.subheader("Selected project context")
    st.write({"Project": state.title, "Project ID": state.project_id,
              "Culture": state.culture, "Dialect": state.dialect, "Region": state.region,
              "Setting": state.setting, "Script": state.script})
    plan_store = AdaptationStore()
    adapted_store = AdaptedScreenplayStore()
    pack_store = VisualPackStore()
    plan = None
    adapted = st.session_state.get("adapted_screenplay")
    load_errors: list[str] = []
    try:
        plan = plan_store.load_plan(state.project_id)
    except Exception as exc:
        load_errors.append(f"Saved Phase 5 plan unavailable: {exc}")
    if adapted is None:
        try:
            adapted = adapted_store.load_adapted_screenplay(state.project_id)
        except Exception as exc:
            load_errors.append(f"Saved Phase 6 adapted screenplay unavailable: {exc}")
    for message in load_errors:
        st.warning(message)

    current_pack = st.session_state.get("visual_production_pack")
    if current_pack is None:
        try:
            current_pack = pack_store.load_pack(state.project_id)
            st.session_state["visual_production_pack"] = current_pack
        except FileNotFoundError:
            pass
        except Exception as exc:
            st.error(f"Could not load saved visual pack: {exc}")

    controls = st.columns(4)
    with controls[0]:
        if st.button("Generate Visual Production Pack", key="generate_visual_pack", disabled=plan is None or adapted is None):
            try:
                evidence_store = _store_for_context(plan.culture, plan.region)
                evidence_store.load()
                generated = MockVisualPackGenerator().generate(
                    state, adapted, plan, list(evidence_store.evidence.values()),
                )
                st.session_state["visual_production_pack"] = generated
                current_pack = generated
                st.success("Structured visual production pack generated. No images were generated.")
            except Exception as exc:
                st.error(f"Could not generate visual pack: {exc}")
    with controls[1]:
        if st.button("Validate Visual Production Pack", key="validate_visual_pack", disabled=current_pack is None or plan is None or adapted is None):
            try:
                evidence_store = _store_for_context(plan.culture, plan.region)
                evidence_store.load()
                result = validate_visual_pack(state, current_pack, adapted, plan, list(evidence_store.evidence.values()))
                current_pack = current_pack.model_copy(update={"validation_result": result, "updated_at": datetime.now(timezone.utc).isoformat()})
                st.session_state["visual_production_pack"] = current_pack
                st.success("Visual pack validation completed.")
            except Exception as exc:
                st.error(f"Could not validate visual pack: {exc}")
    with controls[2]:
        if st.button("Save Visual Production Pack", key="save_visual_pack", disabled=current_pack is None):
            try:
                current_pack = pack_store.save_pack(current_pack)
                st.session_state["visual_production_pack"] = current_pack
                st.success(f"Saved separately to data/projects/{state.project_id}/visual_production_pack.json (version {current_pack.version}).")
            except Exception as exc:
                st.error(f"Could not save visual pack: {exc}")
    with controls[3]:
        if st.button("Load Saved Visual Production Pack", key="load_visual_pack", disabled=not pack_store.pack_exists(state.project_id)):
            try:
                current_pack = pack_store.load_pack(state.project_id)
                st.session_state["visual_production_pack"] = current_pack
                st.success(f"Loaded visual pack version {current_pack.version}.")
            except Exception as exc:
                st.error(f"Could not load visual pack: {exc}")

    current_pack = st.session_state.get("visual_production_pack")
    if current_pack is None:
        return
    result = current_pack.validation_result
    st.subheader("Validation summary")
    st.write({"Status": "Valid" if result.valid else "Needs review",
              "Errors": len(result.errors), "Warnings": len(result.warnings),
              "Missing references": len(result.missing_references),
              "Unsupported cultural details": len(result.unsupported_cultural_details),
              "Characters": len(current_pack.character_bibles),
              "Costume variants": len(current_pack.costume_bibles),
              "Scene keyframes": len(current_pack.scene_keyframes),
              "Evidence-linked claims": result.evidence_linked_claim_count,
              "Version": current_pack.version})
    for error in result.errors:
        st.error(error)
    for warning in result.warnings:
        st.warning(warning)
    for missing in result.missing_references:
        st.error(missing)
    for detail in result.unsupported_cultural_details:
        st.warning(detail)

    st.subheader("Character Bibles")
    for bible in current_pack.character_bibles:
        with st.expander(f"{bible.canonical_name} · {bible.character_id}"):
            st.json(bible.model_dump(mode="json"))
    st.subheader("Costume Bibles")
    if not current_pack.costume_bibles:
        st.info("No supported, approved costume variants are specified. No costume changes were invented.")
    for bible in current_pack.costume_bibles:
        with st.expander(f"{bible.variant_name} · {bible.costume_id}"):
            st.json(bible.model_dump(mode="json"))
    st.subheader("Scene Keyframes")
    for frame in current_pack.scene_keyframes:
        with st.expander(f"Scene {frame.scene_number} · {frame.scene_id} · {frame.location or 'Location unspecified'}"):
            st.write({"Location": frame.location, "Characters": frame.characters_present,
                      "Costumes": frame.costume_visual_refs, "Cultural details": frame.cultural_details,
                      "Evidence IDs": frame.evidence_ids, "Warnings": frame.warnings})
            st.markdown("**Generation specification**")
            st.code(frame.generation_prompt)
            st.markdown("**Negative prompt**")
            st.code(frame.negative_prompt)
