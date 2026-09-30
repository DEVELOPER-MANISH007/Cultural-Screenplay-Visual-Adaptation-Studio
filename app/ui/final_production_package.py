"""Phase 9 final validation and explicit production-package export UI."""
from __future__ import annotations

import json
import re
from pathlib import Path

import streamlit as st

from app.models.screenplay import ScreenplayDocument
from app.services.adaptation_store import AdaptationStore
from app.services.adapted_screenplay_store import AdaptedScreenplayStore
from app.services.cultural_store import CulturalStore
from app.services.final_validator import validate_final_project
from app.services.production_exporter import export_package, load_manifest
from app.services.project_store import ProjectStore
from app.services.visual_artifact_store import VisualArtifactStore
from app.services.visual_pack_store import VisualPackStore


def render_final_production_package(data_root: str | Path | None = None) -> None:
    root = Path(data_root) if data_root else Path(__file__).resolve().parents[2] / "data"
    st.header("9. Final Production Package")
    state = st.session_state.get("project_state")
    current_doc = st.session_state.get("screenplay_document")
    default_id = state.project_id if state else ""
    project_id = st.text_input("Project ID", value=default_id, key="phase9_project_id").strip()
    if st.button("Load Project Artifacts", key="phase9_load_artifacts") and project_id:
        try:
            state = ProjectStore(root).load_project(project_id)
            plan = AdaptationStore(root).load_plan(project_id)
            adapted = AdaptedScreenplayStore(root).load_adapted_screenplay(project_id)
            pack = VisualPackStore(root).load_pack(project_id)
            try:
                batch = VisualArtifactStore(root).load_batch(project_id)
            except FileNotFoundError:
                batch = None
            region_name = re.split(r"[/,]", state.region or "", maxsplit=1)[0].strip()
            pack_id = f"{_slug(state.culture or '')}_{_slug(region_name)}"
            store = CulturalStore(root / "culture" / pack_id,
                                  culture=state.culture or "", region=state.region or "").load()
            st.session_state["phase9_artifacts"] = (state, plan, adapted, pack, batch, store)
            st.success("Persisted project artifacts loaded.")
        except (OSError, ValueError, KeyError) as exc:
            st.session_state.pop("phase9_artifacts", None)
        st.error(f"Could not load required persisted artifacts: {exc}")
    artifacts = st.session_state.get("phase9_artifacts")
    if not artifacts:
        st.info("Load persisted Phase 3–8 artifacts for the selected project. Original Phase 1 screenplay is taken from the current session when available.")
        return
    state, plan, adapted, pack, batch, culture_store = artifacts
    doc: ScreenplayDocument | str | None = current_doc
    if doc is None and adapted.original_screenplay_text:
        # Keep the raw text as a read-only validation input when only the persisted
        # Phase 6 snapshot is available; the validator still checks exact preservation.
        doc = adapted.original_screenplay_text
        st.warning("Phase 1 document is not in this session; using the immutable original-text snapshot in the persisted adapted screenplay.")
    evidence = culture_store.list_evidence()
    sources = culture_store.list_sources()
    st.subheader("Project summary")
    st.write({"title": state.title, "project_id": state.project_id, "culture": state.culture,
              "dialect": state.dialect, "region": state.region, "setting": state.setting, "script": state.script})
    statuses = {
        "Original screenplay": bool(doc), "Project memory": state is not None, "Cultural evidence": bool(evidence),
        "Adaptation plan": plan is not None, "Adapted screenplay": adapted is not None,
        "Character bibles": len(pack.character_bibles), "Costume bibles": len(pack.costume_bibles),
        "Scene keyframes": len(pack.scene_keyframes), "Generated visuals": len(batch.artifacts) if batch else "pending",
        "Continuity report": "generated on validation", "AI usage log": "generated on package build",
        "Limitations": "generated on package build",
    }
    st.subheader("Artifact status")
    st.json(statuses)
    if batch and any(item.image_metadata.get("mock_placeholder") for item in batch.artifacts):
        st.caption("Generated visual artifacts include explicitly labeled mock placeholders.")
    validation = st.session_state.get("phase9_validation")
    if st.button("Run Final Validation", key="phase9_validate"):
        validation = validate_final_project(project_state=state, source_screenplay=doc,
            adaptation_plan=plan, adapted_screenplay=adapted, visual_pack=pack, generation_batch=batch,
            cultural_evidence=evidence, cultural_sources=sources)
        st.session_state["phase9_validation"] = validation
        st.session_state.pop("phase9_export_result", None)
    if validation:
        st.subheader("Final Validation")
        st.write("Structural validation:", "passed" if validation.valid else "failed")
        st.write("Traceability:", "complete" if not validation.continuity_report.evidence_traceability_issues and not validation.continuity_report.adaptation_traceability_issues else "issues found")
        st.write("Errors")
        st.write(validation.errors or ["None"])
        st.write("Warnings")
        st.write(validation.warnings or ["None"])
        st.write("Unresolved items")
        st.write(validation.unresolved_items or ["None"])
    if st.button("Generate Production Package", key="phase9_generate"):
        if not validation or not validation.valid:
            st.error("Run a successful final validation before generating the package.")
        else:
            try:
                from app.services.production_exporter import build_package
                built = build_package(project_state=state, adaptation_plan=plan, adapted_screenplay=adapted,
                    visual_pack=pack, generation_batch=batch, evidence=evidence, sources=sources,
                    validation=validation, data_root=root)
                st.session_state["phase9_built_package"] = built
                st.success(f"Production package {built[0].package_id} is ready. No files exported yet.")
            except ValueError as exc:
                st.error(str(exc))
    built = st.session_state.get("phase9_built_package")
    if built:
        st.json(built[0].model_dump(mode="json"))
    if st.button("Export Production Package", key="phase9_export"):
        if not validation or not validation.valid:
            st.error("Export blocked: run successful final validation first.")
        else:
            try:
                result = export_package(project_state=state, adaptation_plan=plan, adapted_screenplay=adapted,
                    visual_pack=pack, generation_batch=batch, evidence=evidence, sources=sources,
                    validation=validation, data_root=root, make_zip=True)
                st.session_state["phase9_export_result"] = result
                st.success("Production package and ZIP exported.")
            except (OSError, ValueError) as exc:
                st.error(f"Export failed: {exc}")
    exported = st.session_state.get("phase9_export_result")
    if exported:
        st.write({"directory": str(exported["export_dir"]), "zip": str(exported["zip_path"]),
                  "files": exported["exported_file_count"], "warnings": exported["warning_count"],
                  "unresolved": exported["unresolved_count"]})
    export_root = root / "projects" / project_id / "exports"
    previous = sorted(path for path in export_root.iterdir() if path.is_dir()) if export_root.is_dir() else []
    if previous:
        selection = st.selectbox("Previous export", previous, format_func=lambda p: p.name, key="phase9_previous_export")
        if st.button("Load Previous Export", key="phase9_load_export"):
            try:
                st.session_state["phase9_previous_manifest"] = load_manifest(selection)
                st.success("Previous export loaded and all manifest checksums verified.")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                st.error(f"Previous export could not be verified: {exc}")
    if st.session_state.get("phase9_previous_manifest"):
        st.json(st.session_state["phase9_previous_manifest"])


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
