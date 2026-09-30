from __future__ import annotations
import sys
from pathlib import Path
import pytest
sys.path.append(str(Path(__file__).parent))
from phase9_fixtures import complete_fixture
from test_production_export import run_export
from app.services.production_exporter import load_manifest


def test_manifest_checksum_reload_and_tamper_detection(tmp_path):
    result = run_export(complete_fixture(tmp_path), make_zip=False)
    manifest = load_manifest(result["export_dir"])
    assert manifest["validation_status"].startswith("passed")
    target = result["export_dir"] / manifest["files"][0]["path"]
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        load_manifest(result["export_dir"])


def test_secret_and_venv_files_are_not_in_zip(tmp_path):
    result = run_export(complete_fixture(tmp_path))
    with __import__("zipfile").ZipFile(result["zip_path"]) as archive:
        assert not any(".env" in name or ".venv" in name or "secret" in name.casefold() for name in archive.namelist())


def test_preexisting_secret_is_never_added_to_export_or_zip(tmp_path):
    items = complete_fixture(tmp_path)
    from test_production_export import run_export
    result = run_export(items, make_zip=False)
    (result["export_dir"] / ".env").write_text("API_KEY=private", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected files"):
        run_export(items)
