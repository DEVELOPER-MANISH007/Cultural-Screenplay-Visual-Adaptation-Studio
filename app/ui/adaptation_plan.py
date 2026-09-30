"""Phase 5 review UI with durable plan and decision persistence."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from app.models.adaptation import (
    AdaptationChangeStatus, AdaptationPlan, AdaptationPlanStatus,
)
from app.services.adaptation_planner import MockAdaptationPlanner
from app.services.adaptation_store import AdaptationStore
from app.ui.cultural_research import _store_for_context

REVIEW_VALUES = ["pending", "approved", "rejected", "needs_revision"]


def _context(state, plan: AdaptationPlan | None = None) -> dict[str, str | None]:
    return {
        "culture": (state.culture if state else None) or (plan.culture if plan else None) or st.session_state.get("research_culture") or "Unspecified",
        "dialect": (state.dialect if state else None) or (plan.dialect if plan else None) or st.session_state.get("research_dialect") or None,
        "region": (state.region if state else None) or (plan.region if plan else None) or st.session_state.get("research_region") or "Unspecified",
        "setting": (state.setting if state else None) or (plan.setting if plan else None) or st.session_state.get("research_setting") or "Unspecified",
        "script": (state.script if state else None) or (plan.script if plan else None) or st.session_state.get("research_script") or None,
    }


def _review_key(plan: AdaptationPlan, change_id: str) -> str:
    return f"review_{plan.plan_id}_{change_id}"


def _clear_review_widgets(plan: AdaptationPlan) -> None:
    for change in plan.changes:
        st.session_state.pop(_review_key(plan, change.change_id), None)
    st.session_state.pop(f"plan_status_{plan.plan_id}", None)


def render_adaptation_plan() -> None:
    st.header("5. Cultural Adaptation Plan")
    st.caption("Creates a separate, evidence-linked plan for human review. Approval only records a decision; screenplay text is never rewritten here.")
    state = st.session_state.get("project_state")
    extraction = st.session_state.get("screenplay_extraction")
    document = st.session_state.get("screenplay_document")
    store = AdaptationStore()
    plan: AdaptationPlan | None = st.session_state.get("adaptation_plan")
    active_project_id = state.project_id if state is not None else None
    if active_project_id and (plan is None or plan.project_id != active_project_id) and store.plan_exists(active_project_id):
        plan = store.load_plan(active_project_id)
        st.session_state["adaptation_plan"] = plan
    if state is None:
        st.info("Load Phase 3 Project Memory to generate a new plan. A previously saved plan can still be loaded by project ID.")
        load_id = st.text_input("Project ID for saved adaptation plan", key="adaptation_load_project_id")
    else:
        load_id = state.project_id
        context = _context(state, plan)
        st.write({"Selected Context": {k.title(): (v or "Not specified") for k, v in context.items() if k != "script"}})
        if context.get("script"):
            st.caption(f"Script: {context['script']}")

    load_col, generate_col, save_col = st.columns(3)
    with load_col:
        if st.button("Load Saved Plan", key="load_saved_adaptation_plan"):
            try:
                loaded = store.load_plan(load_id.strip())
                _clear_review_widgets(loaded)
                st.session_state["adaptation_plan"] = loaded
                plan = loaded
                st.success(f"Loaded saved plan version {loaded.version} for project {loaded.project_id}.")
            except (FileNotFoundError, ValueError) as exc:
                st.error(f"Could not load saved plan: {exc}")
    with generate_col:
        can_generate = state is not None
        if st.button("Generate Adaptation Plan", key="generate_adaptation_plan", disabled=not can_generate):
            try:
                if store.plan_exists(state.project_id):
                    plan = store.load_plan(state.project_id)
                    _clear_review_widgets(plan)
                    st.session_state["adaptation_plan"] = plan
                    st.info("A saved plan already exists; it was loaded to preserve human review decisions.")
                else:
                    evidence_store = _store_for_context(context["culture"] or "Unspecified", context["region"] or "Unspecified")
                    evidence_store.load()
                    planner = MockAdaptationPlanner()
                    plan = planner.create_adaptation_plan(
                        state, list(evidence_store.evidence.values()), extraction=extraction,
                        language_evidence=list(evidence_store.language_evidence.values()),
                        raw_text=document.raw_text if document else None, **context,
                    )
                    st.session_state["adaptation_plan"] = plan
                    st.success(f"Generated plan {plan.plan_id} in pending review. No screenplay text was changed.")
            except Exception as exc:
                st.error(f"Could not generate adaptation plan: {exc}")
                return
    if plan is None:
        if state is None:
            return
        context = _context(state)
        st.info("Generate a plan to review screenplay-linked proposals and unresolved evidence needs.")
        return
    notice = st.session_state.pop("adaptation_plan_notice", None)
    if notice:
        st.success(notice)

    context = _context(state, plan)
    if state is None:
        st.write({"Saved Plan Context": {k.title(): (v or "Not specified") for k, v in context.items() if k != "script"}})
    evidence_store = _store_for_context(context["culture"] or "Unspecified", context["region"] or "Unspecified")
    try:
        evidence_store.load()
    except Exception as exc:
        st.error(f"Could not load cultural evidence for traceability: {exc}")
        evidence_store = None
    persisted = store.plan_exists(plan.project_id)
    st.caption(f"Plan version {plan.version} · { 'Saved' if persisted else 'Not yet saved' }")
    with save_col:
        if st.button("Save Adaptation Plan", key="save_adaptation_plan", disabled=persisted):
            try:
                plan = store.save_plan(plan)
                st.session_state["adaptation_plan"] = plan
                st.success(f"Saved adaptation plan version {plan.version}.")
                persisted = True
            except Exception as exc:
                st.error(f"Could not save adaptation plan: {exc}")

    if state is not None and extraction is None:
        st.warning("The saved plan is available, but no current Phase 2 extraction is loaded. Review data remains linked by its stored canonical IDs.")
    st.subheader("Plan Summary")
    pending = sum(c.status in {AdaptationChangeStatus.PENDING, AdaptationChangeStatus.NEEDS_REVIEW, AdaptationChangeStatus.INSUFFICIENT_EVIDENCE} for c in plan.changes)
    approved = sum(c.status == AdaptationChangeStatus.APPROVED for c in plan.changes)
    rejected = sum(c.status == AdaptationChangeStatus.REJECTED for c in plan.changes)
    needs_revision = sum(c.status == AdaptationChangeStatus.NEEDS_REVISION for c in plan.changes)
    insufficient = sum(not c.evidence_ids and c.confidence == 0.0 for c in plan.changes)
    evidence_backed = sum(bool(c.evidence_ids) and c.status not in {AdaptationChangeStatus.INSUFFICIENT_EVIDENCE} for c in plan.changes)
    st.write({"Plan ID": plan.plan_id, "Version": plan.version, "Plan status": plan.status.value,
              "Total changes": len(plan.changes), "Evidence-backed": evidence_backed, "Pending": pending,
              "Approved": approved, "Rejected": rejected, "Needs revision": needs_revision,
              "Insufficient evidence": insufficient, "Warnings": len(plan.global_warnings)})

    plan_status_key = f"plan_status_{plan.plan_id}"
    st.selectbox("Plan review status", [s.value for s in AdaptationPlanStatus],
                 index=[s.value for s in AdaptationPlanStatus].index(plan.status.value), key=plan_status_key)
    for warning in plan.global_warnings:
        st.warning(warning)
    if plan.unresolved_questions:
        with st.expander("Unresolved questions", expanded=True):
            for question in plan.unresolved_questions:
                st.write(f"- {question}")

    scene_ids = [s.scene_id for s in state.scenes] if state is not None else list(dict.fromkeys(c.scene_id for c in plan.changes))
    scenes = ["All scenes"] + scene_ids
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        scene_filter = st.selectbox("Scene", scenes, key="adapt_scene_filter")
    with f2:
        categories = ["All categories"] + sorted({change.category.value for change in plan.changes})
        category_filter = st.selectbox("Category", categories, key="adapt_category_filter")
    with f3:
        statuses = ["All statuses"] + REVIEW_VALUES
        change_status_filter = st.selectbox("Change status", statuses, key="adapt_status_filter")
    with f4:
        min_confidence = st.slider("Minimum confidence", 0.0, 1.0, 0.0, 0.05, key="adapt_confidence_filter")
    visible = [c for c in plan.changes
               if (scene_filter == "All scenes" or c.scene_id == scene_filter)
               and (category_filter == "All categories" or c.category.value == category_filter)
               and (change_status_filter == "All statuses" or _review_value(c.status) == change_status_filter)
               and c.confidence >= min_confidence]
    scene_map = {s.scene_id: s for s in state.scenes} if state is not None else {}
    evidence_map = evidence_store.evidence if evidence_store is not None else {}
    st.subheader(f"Adaptation Changes ({len(visible)} shown)")
    for change in visible:
        scene = scene_map.get(change.scene_id)
        title = f"{change.change_id} · {change.scene_id} · {change.category.value} · {change.status.value}"
        with st.expander(title):
            st.markdown(f"**Scene:** {change.scene_id}" + (f" — {scene.heading}" if scene else ""))
            st.markdown(f"**Target:** `{change.target_type}` · `{change.target_id}`")
            st.markdown(f"**Original:** {change.original_element}")
            st.markdown(f"**Proposed change:** {change.proposed_change}")
            st.markdown(f"**Rationale:** {change.rationale}")
            st.markdown(f"**Evidence:** {', '.join(change.evidence_ids) if change.evidence_ids else 'None — insufficient evidence'}")
            st.markdown(f"**Confidence:** {change.confidence:.2f}")
            if change.warnings:
                for warning in change.warnings:
                    st.warning(warning)
            if change.evidence_ids:
                st.markdown(f"**Evidence traceability · {change.change_id}**")
                with st.container(border=True):
                    for evidence_id in change.evidence_ids:
                        item = evidence_map.get(evidence_id)
                        if item is None:
                            st.error(f"Evidence ID {evidence_id} is missing from the loaded pack.")
                            continue
                        st.markdown(f"**{item.evidence_id}:** {item.claim}")
                        st.markdown(f"Source: [{item.source_title}]({item.source_url})")
                        st.write({"Scope": item.scope, "Confidence": item.confidence, "Status": item.status.value, "Source URL": str(item.source_url)})
            review_key = _review_key(plan, change.change_id)
            default_review = _review_value(change.status)
            st.selectbox("Human review decision", REVIEW_VALUES, index=REVIEW_VALUES.index(default_review),
                         format_func=lambda value: value.replace("_", " ").title(), key=review_key)
    st.caption("Review selections remain unsaved until you click Save Review Decisions.")
    decision_col, json_col = st.columns(2)
    with decision_col:
        if st.button("Save Review Decisions", key="save_review_decisions", disabled=not persisted):
            decisions = []
            for change in plan.changes:
                selected = st.session_state.get(_review_key(plan, change.change_id), _review_value(change.status))
                decisions.append(change.model_copy(update={"status": AdaptationChangeStatus(selected)}))
            selected_plan_status = st.session_state.get(plan_status_key, plan.status.value)
            revised = plan.model_copy(update={"changes": decisions, "status": AdaptationPlanStatus(selected_plan_status)})
            try:
                saved = store.update_plan(revised)
                st.session_state["adaptation_plan"] = saved
                st.session_state["adaptation_plan_notice"] = f"Saved review decisions in plan version {saved.version}."
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save review decisions: {exc}")
    with json_col:
        with st.expander("Machine-readable AdaptationPlan JSON"):
            st.json(plan.model_dump(mode="json"))


def _review_value(status: AdaptationChangeStatus) -> str:
    if status.value in REVIEW_VALUES:
        return status.value
    return "pending"
