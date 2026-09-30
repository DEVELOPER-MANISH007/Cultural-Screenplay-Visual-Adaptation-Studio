from __future__ import annotations
import sys, zipfile
from pathlib import Path
sys.path.append(str(Path(__file__).parent))
from phase9_fixtures import complete_fixture
from app.services.final_validator import validate_final_project
from app.services.production_exporter import export_package


def run_export(items, *, make_zip=True):
    state, plan, adapted, pack, batch, evidence, sources, source, root = items
    result = validate_final_project(project_state=state, source_screenplay=source, adaptation_plan=plan,
        adapted_screenplay=adapted, visual_pack=pack, generation_batch=batch,
        cultural_evidence=evidence, cultural_sources=sources)
    return export_package(project_state=state, adaptation_plan=plan, adapted_screenplay=adapted,
        visual_pack=pack, generation_batch=batch, evidence=evidence, sources=sources,
        validation=result, data_root=root, make_zip=make_zip)


def test_export_directory_manifest_and_actual_checksums(tmp_path):
    items = complete_fixture(tmp_path); result = run_export(items)
    folder = result["export_dir"]
    assert (folder / "01_adapted_screenplay.json").is_file()
    assert (folder / "02_adapted_screenplay.txt").read_text(encoding="utf-8") == items[2].adapted_screenplay_text
    assert (folder / "visuals").is_dir()
    for entry in result["manifest"]["files"]:
        import hashlib
        assert hashlib.sha256((folder / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]


def test_zip_round_trip_and_exact_export_tree(tmp_path):
    result = run_export(complete_fixture(tmp_path))
    with zipfile.ZipFile(result["zip_path"]) as archive:
        names = archive.namelist()
        assert any(name.endswith("12_manifest.json") for name in names)
        assert any("visuals/" in name for name in names)
        assert all(".venv" not in name and ".git" not in name for name in names)


def test_export_does_not_modify_source_artifact_files(tmp_path):
    items = complete_fixture(tmp_path)
    root = items[-1] / "projects" / items[0].project_id
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    run_export(items)
    after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file() and "exports/" not in p.relative_to(root).as_posix()}
    assert before == after


def test_export_is_blocked_on_structural_error(tmp_path):
    items = complete_fixture(tmp_path)
    state, plan, adapted, pack, batch, evidence, sources, source, root = items
    bad = validate_final_project(project_state=state, source_screenplay=source, adaptation_plan=plan,
        adapted_screenplay=None, visual_pack=pack, generation_batch=batch,
        cultural_evidence=evidence, cultural_sources=sources)
    import pytest
    with pytest.raises(ValueError, match="blocked"):
        export_package(project_state=state, adaptation_plan=plan, adapted_screenplay=adapted,
            visual_pack=pack, generation_batch=batch, evidence=evidence, sources=sources,
            validation=bad, data_root=root)


def test_exports_include_warnings_and_deterministic_file_names(tmp_path):
    result = run_export(complete_fixture(tmp_path), make_zip=False)
    assert result["warning_count"] > 0
    assert [x["path"] for x in result["manifest"]["files"]][:3] == sorted([x["path"] for x in result["manifest"]["files"]])[:3]
    assert "09_continuity_report.json" in [p.name for p in result["export_dir"].iterdir()]
