"""Human-approved Phase 8 visual generation UI; no automatic generation on planning."""
from __future__ import annotations

import streamlit as st

from app.models.visual_generation import VisualGenerationStatus
from app.services.adaptation_store import AdaptationStore
from app.services.adapted_screenplay_store import AdaptedScreenplayStore
from app.services.generated_visual_validator import validate_generated_visuals
from app.services.image_generation_provider import available_image_generation_providers, get_image_generation_provider
from app.services.visual_artifact_store import VisualArtifactStore
from app.services.visual_generation_planner import create_visual_generation_batch, reconcile_generation_batch
from app.services.visual_generation_service import VisualGenerationService, set_request_review_status
from app.services.visual_pack_store import VisualPackStore
from app.ui.cultural_research import _store_for_context


def render_visual_generation() -> None:
    st.header("8. Visual Generation")
    st.caption("Only persisted, human-approved requests are sent to a provider. The default provider creates labeled placeholders, not cinematic images.")
    state = st.session_state.get("project_state")
    if state is None:
        st.info("Load the Phase 3 project state before generating visual requests.")
        return
    st.write({"Project": state.title, "Project ID": state.project_id,
              "Culture": state.culture, "Dialect": state.dialect, "Region": state.region,
              "Setting": state.setting, "Script": state.script})

    pack_store = VisualPackStore()
    artifact_store = VisualArtifactStore()
    plan_store = AdaptationStore()
    adapted_store = AdaptedScreenplayStore()
    batch = st.session_state.get("visual_generation_batch")
    if batch is None:
        try:
            batch = artifact_store.load_batch(state.project_id)
            st.session_state["visual_generation_batch"] = batch
        except FileNotFoundError:
            pass
        except Exception as exc:
            st.error(f"Could not load visual generation requests: {exc}")

    provider_names = available_image_generation_providers()
    provider_name = st.selectbox("Image provider", provider_names, key="visual_generation_provider")
    action_cols = st.columns(5)
    with action_cols[0]:
        if st.button("Generate Requests", key="generate_visual_requests", disabled=not pack_store.pack_exists(state.project_id)):
            try:
                pack = pack_store.load_pack(state.project_id)
                plan = plan_store.load_plan(state.project_id)
                adapted = adapted_store.load_adapted_screenplay(state.project_id)
                evidence_store = _store_for_context(plan.culture, plan.region)
                evidence_store.load()
                fresh = create_visual_generation_batch(pack, state, adapted, plan, provider=provider_name,
                                                       cultural_evidence=list(evidence_store.evidence.values()))
                prior = batch
                if prior is None:
                    try:
                        prior = artifact_store.load_batch(state.project_id)
                    except FileNotFoundError:
                        pass
                planned = reconcile_generation_batch(prior, fresh)
                batch = artifact_store.save_batch(planned)
                st.session_state["visual_generation_batch"] = batch
                st.success(f"Created {len(batch.requests)} pending requests. No provider was called.")
            except Exception as exc:
                st.error(f"Could not create generation requests: {exc}")
    with action_cols[1]:
        if st.button("Generate Approved Visuals", key="generate_approved_visuals", disabled=batch is None):
            try:
                # Use the persistent approval state, not an unsaved Streamlit copy.
                persisted_batch = artifact_store.load_batch(state.project_id)
                pack = pack_store.load_pack(state.project_id)
                plan = plan_store.load_plan(state.project_id)
                adapted = adapted_store.load_adapted_screenplay(state.project_id)
                evidence_store = _store_for_context(plan.culture, plan.region)
                evidence_store.load()
                fresh = create_visual_generation_batch(pack, state, adapted, plan, provider=provider_name,
                                                       cultural_evidence=list(evidence_store.evidence.values()))
                provider = get_image_generation_provider(provider_name)
                updated = VisualGenerationService(provider, artifact_store).generate_approved(
                    persisted_batch, fresh.requests, pack, state,
                )
                batch = artifact_store.save_batch(updated)
                st.session_state["visual_generation_batch"] = batch
                st.success(f"Generation run completed with {len(batch.artifacts)} artifact record(s). Review failures and continuity results below.")
            except Exception as exc:
                st.error(f"Could not run approved generation requests: {exc}")
    with action_cols[2]:
        if st.button("Validate Generated Visuals", key="validate_generated_visuals", disabled=batch is None or not pack_store.pack_exists(state.project_id)):
            try:
                batch = artifact_store.load_batch(state.project_id)
                pack = pack_store.load_pack(state.project_id)
                plan = plan_store.load_plan(state.project_id)
                adapted = adapted_store.load_adapted_screenplay(state.project_id)
                evidence_store = _store_for_context(plan.culture, plan.region)
                evidence_store.load()
                fresh = create_visual_generation_batch(pack, state, adapted, plan, provider=provider_name,
                                                       cultural_evidence=list(evidence_store.evidence.values()))
                result = validate_generated_visuals(batch, pack, state, current_requests=fresh.requests)
                batch = batch.model_copy(update={"continuity_result": result})
                batch = artifact_store.save_batch(batch)
                st.session_state["visual_generation_batch"] = batch
                st.success("Generated visual metadata/spec validation completed.")
            except Exception as exc:
                st.error(f"Could not validate generated visuals: {exc}")
    with action_cols[3]:
        if st.button("Save Artifacts", key="save_visual_artifacts", disabled=batch is None):
            try:
                batch = artifact_store.save_batch(batch)
                st.session_state["visual_generation_batch"] = batch
                st.success(f"Saved request decisions and artifact metadata for project {state.project_id}.")
            except Exception as exc:
                st.error(f"Could not save artifacts: {exc}")
    with action_cols[4]:
        if st.button("Load Artifacts", key="load_visual_artifacts", disabled=not artifact_store.batch_exists(state.project_id)):
            try:
                batch = artifact_store.load_batch(state.project_id)
                st.session_state["visual_generation_batch"] = batch
                st.success(f"Loaded {len(batch.requests)} requests and {len(batch.artifacts)} artifacts.")
            except Exception as exc:
                st.error(f"Could not load artifacts: {exc}")

    batch = st.session_state.get("visual_generation_batch")
    if batch is None:
        st.info("Load the saved Phase 7 Visual Production Pack, then create requests to begin.")
        return
    statuses = [item.status for item in batch.requests]
    st.subheader("Generation summary")
    st.write({
        "Character requests": sum(item.asset_type.value == "character" for item in batch.requests),
        "Costume requests": sum(item.asset_type.value == "costume" for item in batch.requests),
        "Scene requests": sum(item.asset_type.value == "scene_keyframe" for item in batch.requests),
        "Pending": sum(item == VisualGenerationStatus.PENDING for item in statuses),
        "Approved": sum(item == VisualGenerationStatus.APPROVED for item in statuses),
        "Generated": sum(item == VisualGenerationStatus.GENERATED for item in statuses),
        "Failed": sum(item == VisualGenerationStatus.FAILED for item in statuses),
        "Needs review": sum(item == VisualGenerationStatus.NEEDS_REVIEW for item in statuses),
        "Rejected": sum(item == VisualGenerationStatus.REJECTED for item in statuses),
        "Batch status": batch.status.value, "Batch version": batch.version,
    })
    for warning in batch.warnings:
        st.warning(warning)

    st.subheader("Generation requests and approval")
    for request in batch.requests:
        with st.expander(f"{request.asset_type.value} · {request.source_entity_id} · {request.status.value}"):
            st.write({"Request ID": request.request_id, "Asset type": request.asset_type.value,
                      "Source entity": request.source_entity_id, "Scene": request.scene_id,
                      "Provider": request.provider, "Status": request.status.value,
                      "Evidence IDs": request.evidence_ids, "Prompt hash": request.prompt_hash,
                      "Visual spec version": request.visual_spec_version})
            st.markdown("**Prompt preview**")
            st.code(request.prompt[:1200] + ("…" if len(request.prompt) > 1200 else ""))
            if request.warnings:
                for warning in request.warnings:
                    st.warning(warning)
            if request.status != VisualGenerationStatus.GENERATED:
                decision_cols = st.columns(3)
                decisions = [
                    (VisualGenerationStatus.APPROVED, "Approve"),
                    (VisualGenerationStatus.REJECTED, "Reject"),
                    (VisualGenerationStatus.NEEDS_REVIEW, "Needs Review"),
                ]
                for column, (decision, label) in zip(decision_cols, decisions):
                    with column:
                        if st.button(label, key=f"review_{request.request_id}_{decision.value}"):
                            try:
                                changed = set_request_review_status(batch, request.request_id, decision)
                                batch = artifact_store.save_batch(changed)
                                st.session_state["visual_generation_batch"] = batch
                                st.success(f"Saved {decision.value} decision for {request.request_id}.")
                            except Exception as exc:
                                st.error(f"Could not save request decision: {exc}")
    st.caption("Approval decisions are written to visual_artifacts.json immediately. Pending, rejected, and needs-review requests are never sent to a provider.")

    result = batch.continuity_result
    st.subheader("Continuity validation")
    st.write({"Valid": result.valid, "Errors": len(result.errors), "Warnings": len(result.warnings),
              "Checked artifacts": result.checked_artifact_count,
              "Failed artifacts": result.failed_artifact_count})
    for error in result.errors:
        st.error(error)
    for warning in result.warnings:
        st.warning(warning)

    st.subheader("Generated visual gallery")
    if not batch.artifacts:
        st.info("No artifacts yet. Approve individual requests, then choose Generate Approved Visuals.")
    for artifact in batch.artifacts:
        with st.expander(f"{artifact.asset_type.value} · {artifact.source_entity_id} · {artifact.status.value}"):
            st.write({"Artifact ID": artifact.artifact_id, "Request ID": artifact.request_id,
                      "Provider": artifact.provider, "Model": artifact.model_name,
                      "Prompt hash": artifact.prompt_hash, "Continuity": artifact.continuity_status,
                      "Warnings": artifact.warnings})
            if artifact.image_metadata.get("mock_placeholder"):
                st.warning("MOCK-GENERATED PLACEHOLDER — NOT A REAL GENERATED IMAGE. No identity or image similarity analysis was performed.")
            if artifact.image_path:
                try:
                    visual_bytes = artifact_store.read_media(state.project_id, artifact)
                    if artifact.image_path.casefold().endswith(".svg"):
                        st.image(visual_bytes.decode("utf-8"))
                    else:
                        st.image(visual_bytes)
                except Exception as exc:
                    st.error(f"Could not display stored visual artifact: {exc}")
