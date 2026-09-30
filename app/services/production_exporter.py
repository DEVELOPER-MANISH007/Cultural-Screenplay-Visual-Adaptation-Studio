"""Build and export a validated, traceable Phase 9 production package."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models.adaptation import AdaptationPlan
from app.models.adapted_screenplay import AdaptedScreenplay
from app.models.ai_usage import AIUsageLog, AIUsageRecord
from app.models.continuity_report import FinalValidationResult
from app.models.cultural_evidence import CulturalEvidence, CulturalSource
from app.models.limitations import LimitationItem, LimitationsReport
from app.models.production_package import ProductionPackage
from app.models.project_state import ProjectState
from app.models.visual_generation import VisualGenerationBatch
from app.models.visual_pack import VisualProductionPack
from app.services.visual_artifact_store import VisualArtifactStore


PACKAGE_FILES = [
    "01_adapted_screenplay.json", "02_adapted_screenplay.txt", "03_project_breakdown.json",
    "04_cultural_evidence.json", "05_character_bibles.json", "06_costume_bibles.json",
    "07_scene_keyframes.json", "08_visual_artifacts.json", "09_continuity_report.json",
    "10_ai_usage_log.json", "11_limitations.json",
]
EXCLUDED_PARTS = {".venv", "venv", "__pycache__", ".git", ".pytest_cache"}
EXCLUDED_NAMES = {".env", ".env.local", ".env.production", "secrets.json", "credentials.json"}


def build_package(*, project_state: ProjectState, adaptation_plan: AdaptationPlan,
                  adapted_screenplay: AdaptedScreenplay, visual_pack: VisualProductionPack,
                  generation_batch: VisualGenerationBatch | None,
                  evidence: list[CulturalEvidence], sources: list[CulturalSource],
                  validation: FinalValidationResult, data_root: str | Path | None = None,
                  source_screenplay_reference: str | None = None) -> tuple[ProductionPackage, AIUsageLog, LimitationsReport, dict[str, object]]:
    if not validation.valid:
        raise ValueError("Cannot build a production package: final validation has structural errors.")
    timestamp = datetime.now(timezone.utc).isoformat()
    signature = "|".join((project_state.project_id, str(project_state.version), adaptation_plan.plan_id,
                         str(adaptation_plan.version), adapted_screenplay.adaptation_id,
                         str(visual_pack.version), generation_batch.batch_id if generation_batch else "none",
                         str(generation_batch.version) if generation_batch else "0"))
    package_id = "PKG_" + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
    evidence_ids = {eid for change in adaptation_plan.changes for eid in change.evidence_ids}
    evidence_ids.update(adapted_screenplay.evidence_ids)
    for group in [visual_pack.character_bibles, visual_pack.costume_bibles, visual_pack.scene_keyframes]:
        evidence_ids.update(eid for item in group for eid in item.evidence_ids)
    if generation_batch:
        evidence_ids.update(eid for req in generation_batch.requests for eid in req.evidence_ids)
    used_evidence = [item for item in evidence if item.evidence_id in evidence_ids]
    used_source_ids = {item.source_id for item in used_evidence}
    used_sources = [item for item in sources if item.source_id in used_source_ids]
    report = validation.continuity_report
    limitations_list = [
        LimitationItem(limitation_id="LIM_MOCK_VISUAL", title="Mock visuals are placeholders",
                       detail="The development mock provider produces labeled placeholder media, not cinematic images.", related_phase="Phase 8"),
        LimitationItem(limitation_id="LIM_NO_CV", title="No computer-vision similarity verification",
                       detail="Visual checks validate structured metadata and references; they do not compare faces or image pixels.", related_phase="Phase 8"),
        LimitationItem(limitation_id="LIM_CURATED", title="Cultural evidence is locally curated",
                       detail="The cultural pack is a concise local evidence set, not exhaustive research; source scope and unresolved claims remain explicit.", related_phase="Phase 4"),
        LimitationItem(limitation_id="LIM_NO_LIVE_RESEARCH", title="No live research provider is configured",
                       detail="Research evidence is loaded from the local curated store; the application does not fetch sources during export.", related_phase="Phase 4"),
    ]
    if (project_state.dialect or "").casefold() == "marwari" or (project_state.culture or "").casefold() == "marwari":
        limitations_list.append(LimitationItem(limitation_id="LIM_DIALECT", title="Phrase-level Marwari evidence is limited",
            detail="Marwari dialogue has not been authored or inferred in this phase; phrase-level evidence must be added before dialect-specific dialogue use.", related_phase="Phase 4"))
    if report:
        limitations_list.extend(LimitationItem(limitation_id=f"UNRES_{i+1:03}", title="Unresolved project item",
                                              detail=item) for i, item in enumerate(report.unresolved_items))
    limitations = LimitationsReport(project_id=project_state.project_id, items=limitations_list, generated_at=timestamp)
    records = [
        AIUsageRecord(phase="1", operation="screenplay ingestion", provider="local ingestion service", mode="deterministic/offline", input_reference=project_state.source_filename, output_reference=project_state.screenplay_id, timestamp=timestamp, network_used=False, notes="The Phase 1 processing timestamp is not persisted; timestamp here is the audit-log assembly time."),
        AIUsageRecord(phase="2", operation="structured extraction", provider="MockLLMProvider", model=None, mode="mock/offline", input_reference=project_state.screenplay_id, output_reference=project_state.project_id, timestamp=timestamp, network_used=False, notes="Development mock; no external LLM call is claimed. This is an audit snapshot, not a historical call log."),
        AIUsageRecord(phase="3", operation="canonical project normalization", provider="local normalizer", model=None, mode="deterministic/offline", input_reference=project_state.screenplay_id, output_reference=project_state.project_id, timestamp=project_state.updated_at, network_used=False, notes="Timestamp is the persisted project-state update time."),
        AIUsageRecord(phase="4", operation="cultural evidence retrieval", provider="CuratedResearchProvider", model=None, mode="curated-local/offline", input_reference=",".join(sorted(item.source_id for item in used_sources)), output_reference=",".join(sorted(item.evidence_id for item in used_evidence)), timestamp=timestamp, network_used=False, notes="The configured provider reads local reviewed records and does not search or fetch the public web."),
        AIUsageRecord(phase="5", operation="adaptation planning", provider="deterministic mock planner", mode="mock/offline", input_reference=project_state.project_id, output_reference=adaptation_plan.plan_id, timestamp=adaptation_plan.created_at, network_used=False, notes="Timestamp copied from persisted plan metadata."),
        AIUsageRecord(phase="6", operation="screenplay adaptation", provider="deterministic adapter", mode="deterministic/offline", input_reference=adaptation_plan.plan_id, output_reference=adapted_screenplay.adaptation_id, timestamp=adapted_screenplay.created_at, network_used=False, notes="Timestamp copied from persisted adapted-screenplay metadata; development output uses the deterministic adapter."),
        AIUsageRecord(phase="7", operation="visual specification generation", provider="MockVisualPackGenerator", model=None, mode="mock/offline", input_reference=adapted_screenplay.adaptation_id, output_reference=f"{project_state.project_id}:visual-pack-v{visual_pack.version}", timestamp=visual_pack.created_at, network_used=False, notes="Structured prompts/specifications only; no image was generated in Phase 7."),
        AIUsageRecord(phase="8", operation="visual generation", provider=next((a.provider for a in generation_batch.artifacts), "MockVisualImageGenerationProvider") if generation_batch else "none", model=None, mode=("mock/offline" if generation_batch and generation_batch.artifacts and all(a.image_metadata.get("mock_placeholder") for a in generation_batch.artifacts) else "provider" if generation_batch and generation_batch.artifacts else "not_run"), input_reference=generation_batch.batch_id if generation_batch else None, output_reference=",".join(a.artifact_id for a in generation_batch.artifacts) if generation_batch else None, timestamp=min((a.created_at for a in generation_batch.artifacts), default=(generation_batch.created_at if generation_batch else timestamp)), network_used=(False if not generation_batch or not generation_batch.artifacts or all(a.image_metadata.get("mock_placeholder") for a in generation_batch.artifacts) else None), notes="Provider provenance comes from persisted artifacts; network use is unknown for non-mock providers unless the provider records it."),
    ]
    usage = AIUsageLog(project_id=project_state.project_id, records=records, generated_at=timestamp)
    project_dir = Path(data_root) / "projects" / project_state.project_id if data_root else Path("data") / "projects" / project_state.project_id
    artifact_refs = [a.artifact_id for a in generation_batch.artifacts] if generation_batch else []
    package = ProductionPackage(
        package_id=package_id, project_id=project_state.project_id, title=project_state.title,
        culture=project_state.culture or adapted_screenplay.culture, dialect=project_state.dialect,
        region=project_state.region or adapted_screenplay.region, setting=project_state.setting or adapted_screenplay.setting,
        script=project_state.script, source_screenplay_reference=source_screenplay_reference or project_state.screenplay_id,
        project_state_reference=str(project_dir / "project.json"),
        cultural_evidence_summary={"evidence_count": len(used_evidence), "source_count": len(used_sources), "evidence_ids": sorted(evidence_ids)},
        adaptation_summary={"plan_id": adaptation_plan.plan_id, "plan_version": adaptation_plan.version,
                            "approved_changes": sum(c.status.value == "approved" for c in adaptation_plan.changes),
                            "applied_changes": len(adapted_screenplay.applied_change_ids)},
        adapted_screenplay_reference=adapted_screenplay.adaptation_id,
        character_bible_references=[x.character_id for x in visual_pack.character_bibles],
        costume_bible_references=[x.costume_id for x in visual_pack.costume_bibles],
        scene_keyframe_references=[x.scene_id for x in visual_pack.scene_keyframes],
        generated_visual_references=artifact_refs,
        continuity_report_reference=report.report_id if report else "missing",
        ai_usage_reference=f"{project_state.project_id}:AI_USAGE", limitations_reference=f"{project_state.project_id}:LIMITATIONS",
        validation_status="passed_with_warnings" if validation.warnings else "passed", created_at=timestamp, updated_at=timestamp,
    )
    sections: dict[str, object] = {
        "01_adapted_screenplay.json": adapted_screenplay.model_dump(mode="json"),
        "02_adapted_screenplay.txt": adapted_screenplay.adapted_screenplay_text,
        "03_project_breakdown.json": {"package": package.model_dump(mode="json"), "project_state": project_state.model_dump(mode="json"), "adaptation_plan": adaptation_plan.model_dump(mode="json")},
        "04_cultural_evidence.json": {"evidence": [x.model_dump(mode="json") for x in used_evidence], "sources": [x.model_dump(mode="json") for x in used_sources]},
        "05_character_bibles.json": [x.model_dump(mode="json") for x in visual_pack.character_bibles],
        "06_costume_bibles.json": [x.model_dump(mode="json") for x in visual_pack.costume_bibles],
        "07_scene_keyframes.json": [x.model_dump(mode="json") for x in visual_pack.scene_keyframes],
        "08_visual_artifacts.json": {"batch": generation_batch.model_dump(mode="json") if generation_batch else None, "artifacts": [x.model_dump(mode="json") for x in generation_batch.artifacts] if generation_batch else []},
        "09_continuity_report.json": report.model_dump(mode="json") if report else {},
        "10_ai_usage_log.json": usage.model_dump(mode="json"),
        "11_limitations.json": limitations.model_dump(mode="json"),
    }
    return package, usage, limitations, sections


def export_package(*, project_state: ProjectState, adaptation_plan: AdaptationPlan,
                   adapted_screenplay: AdaptedScreenplay, visual_pack: VisualProductionPack,
                   generation_batch: VisualGenerationBatch | None, evidence: list[CulturalEvidence],
                   sources: list[CulturalSource], validation: FinalValidationResult,
                   data_root: str | Path | None = None, make_zip: bool = True,
                   source_screenplay_reference: str | None = None) -> dict[str, object]:
    if not validation.valid:
        raise ValueError("Export blocked because final validation has structural errors.")
    package, usage, limitations, sections = build_package(
        project_state=project_state, adaptation_plan=adaptation_plan, adapted_screenplay=adapted_screenplay,
        visual_pack=visual_pack, generation_batch=generation_batch, evidence=evidence, sources=sources,
        validation=validation, data_root=data_root, source_screenplay_reference=source_screenplay_reference,
    )
    root = Path(data_root) if data_root else Path("data")
    project_dir = root / "projects" / project_state.project_id
    export_dir = project_dir / "exports" / package.package_id
    export_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in sections.items():
        path = export_dir / name
        if name.endswith(".txt"):
            path.write_text(str(payload), encoding="utf-8", newline="\n")
        else:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    media_store = VisualArtifactStore(root)
    if generation_batch:
        visuals_dir = export_dir / "visuals"
        for artifact in generation_batch.artifacts:
            if artifact.image_path:
                try:
                    media = media_store.read_media(project_state.project_id, artifact)
                except (OSError, ValueError) as exc:
                    raise ValueError(f"Cannot export artifact {artifact.artifact_id}: {exc}") from exc
                filename = Path(artifact.image_path).name
                (visuals_dir / filename).parent.mkdir(parents=True, exist_ok=True)
                (visuals_dir / filename).write_bytes(media)
    expected_names = set(PACKAGE_FILES) | {"12_manifest.json"}
    if generation_batch:
        expected_names.update(f"visuals/{Path(a.image_path).name}" for a in generation_batch.artifacts if a.image_path)
    unexpected = [p.relative_to(export_dir).as_posix() for p in export_dir.rglob("*")
                  if p.is_file() and p.relative_to(export_dir).as_posix() not in expected_names]
    if unexpected:
        raise ValueError("Unexpected files exist in export destination and will not be bundled: " + ", ".join(sorted(unexpected)))
    files = []
    for path in sorted(p for p in export_dir.rglob("*") if p.is_file()):
        if path.name == "12_manifest.json":
            continue
        content = path.read_bytes()
        files.append({"path": path.relative_to(export_dir).as_posix(), "type": _file_type(path),
                      "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)})
    manifest = {"package_id": package.package_id, "project_id": package.project_id, "title": package.title,
                "created_at": datetime.now(timezone.utc).isoformat(), "validation_status": package.validation_status,
                "files": files}
    (export_dir / "12_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    zip_path = None
    if make_zip:
        zip_name = f"{_safe_name(package.title)}_production_package_{package.package_id}.zip"
        zip_path = project_dir / "exports" / zip_name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for entry in [*files, {"path": "12_manifest.json"}]:
                relative = Path(entry["path"])
                if relative.is_absolute() or ".." in relative.parts or _excluded(relative):
                    raise ValueError(f"Unsafe file path in production export: {entry['path']}")
                path = export_dir / relative
                archive.write(path, (Path(export_dir.name) / relative).as_posix())
    return {"package": package, "usage": usage, "limitations": limitations, "export_dir": export_dir,
            "zip_path": zip_path, "manifest": manifest, "exported_file_count": len(files) + 1,
            "warning_count": len(validation.warnings), "unresolved_count": len(validation.unresolved_items)}


def load_manifest(export_dir: str | Path) -> dict:
    folder = Path(export_dir)
    manifest = json.loads((folder / "12_manifest.json").read_text(encoding="utf-8"))
    for item in manifest.get("files", []):
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or _excluded(relative):
            raise ValueError(f"Unsafe path in manifest: {item['path']}")
        path = folder / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Manifest checksum verification failed for {item['path']}")
    return manifest


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "project"


def _file_type(path: Path) -> str:
    return {".json": "application/json", ".txt": "text/plain", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg"}.get(path.suffix.lower(), "application/octet-stream")


def _excluded(path: Path) -> bool:
    parts = [part.casefold() for part in path.parts]
    sensitive = any(any(marker in part for marker in ("secret", "credential", "api_key", "apikey", "token")) for part in parts)
    return sensitive or any(part in EXCLUDED_PARTS or part in EXCLUDED_NAMES for part in parts) or any(part.startswith(".env") for part in parts)
