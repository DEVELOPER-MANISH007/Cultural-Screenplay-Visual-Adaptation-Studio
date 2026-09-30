from __future__ import annotations
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))
from phase9_fixtures import complete_fixture
from app.models.production_package import ProductionPackage
from app.services.final_validator import validate_final_project
from app.services.production_exporter import build_package, export_package, load_manifest


def test_package_references_traceable_artifacts_and_evidence(tmp_path):
    state, plan, adapted, pack, batch, evidence, sources, source, root = complete_fixture(tmp_path)
    validation = validate_final_project(project_state=state, source_screenplay=source, adaptation_plan=plan,
        adapted_screenplay=adapted, visual_pack=pack, generation_batch=batch,
        cultural_evidence=evidence, cultural_sources=sources)
    package, _, _, sections = build_package(project_state=state, adaptation_plan=plan,
        adapted_screenplay=adapted, visual_pack=pack, generation_batch=batch,
        evidence=evidence, sources=sources, validation=validation, data_root=root)
    assert isinstance(package, ProductionPackage)
    assert package.adapted_screenplay_reference == adapted.adaptation_id
    assert "EVID_005" in package.cultural_evidence_summary["evidence_ids"]
    assert "12_manifest.json" not in sections


def test_export_and_manifest_are_repeatably_structured(tmp_path):
    state, plan, adapted, pack, batch, evidence, sources, source, root = complete_fixture(tmp_path)
    validation = validate_final_project(project_state=state, source_screenplay=source, adaptation_plan=plan,
        adapted_screenplay=adapted, visual_pack=pack, generation_batch=batch,
        cultural_evidence=evidence, cultural_sources=sources)
    result = export_package(project_state=state, adaptation_plan=plan, adapted_screenplay=adapted,
        visual_pack=pack, generation_batch=batch, evidence=evidence, sources=sources,
        validation=validation, data_root=root, make_zip=False)
    loaded = load_manifest(result["export_dir"])
    assert loaded["package_id"] == result["package"].package_id
    assert len(loaded["files"]) >= 11
