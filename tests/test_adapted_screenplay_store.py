from __future__ import annotations

import json

import pytest

from app.models.adapted_screenplay import AdaptedScene, AdaptedScreenplay
from app.services.adapted_screenplay_store import AdaptedScreenplayLoadError, AdaptedScreenplayStore


def screenplay():
    return AdaptedScreenplay(
        adaptation_id="ADAPT_TEST", project_id="PERSIST_PROJECT", source_screenplay_id="SCRIPT_1",
        plan_id="PLAN_1", plan_version=3, culture="Marwari", dialect="Marwari",
        region="Marwar / Jodhpur", setting="Rural", scenes=[AdaptedScene(
            scene_id="SCENE_001", scene_number=1, original_heading="INT. ROOM - DAY",
            adapted_heading="INT. ROOM - DAY", original_text="INT. ROOM - DAY\nRavi enters.\n",
            adapted_text="INT. ROOM - DAY\nRavi enters.\n[MOCK APPLIED CHANGE_001]",
            applied_change_ids=["CHANGE_001"], evidence_ids=["EVID_005"],
        )], applied_change_ids=["CHANGE_001"], blocked_change_ids=["CHANGE_002"], evidence_ids=["EVID_005"],
        original_screenplay_text="INT. ROOM - DAY\nRavi enters.\n",
        adapted_screenplay_text="INT. ROOM - DAY\nRavi enters.\n[MOCK APPLIED CHANGE_001]",
        warnings=["Mock output"], assumptions=["A bounded assumption"],
        created_at="2026-09-29T10:00:00+00:00", updated_at="2026-09-29T10:00:00+00:00",
    )


def test_adapted_screenplay_save_and_reload(tmp_path):
    store = AdaptedScreenplayStore(tmp_path)
    value = screenplay()
    assert not store.exists(value.project_id)
    saved = store.save_adapted_screenplay(value)
    assert store.exists(value.project_id)
    assert store.load_adapted_screenplay(value.project_id) == saved
    assert saved.plan_version == 3


def test_missing_output_and_invalid_json(tmp_path):
    store = AdaptedScreenplayStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.load_adapted_screenplay("missing")
    path = tmp_path / "projects" / "BROKEN" / "adapted_screenplay.json"
    path.parent.mkdir(parents=True)
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(AdaptedScreenplayLoadError):
        store.load_adapted_screenplay("BROKEN")


def test_save_persists_scene_change_evidence_and_original_text(tmp_path):
    store = AdaptedScreenplayStore(tmp_path)
    source = screenplay()
    store.save_adapted_screenplay(source)
    raw = json.loads((tmp_path / "projects" / source.project_id / "adapted_screenplay.json").read_text(encoding="utf-8"))
    assert raw["plan_version"] == 3
    assert raw["applied_change_ids"] == ["CHANGE_001"]
    assert raw["evidence_ids"] == ["EVID_005"]
    assert raw["original_screenplay_text"] == source.original_screenplay_text
    assert raw["scenes"][0]["scene_id"] == "SCENE_001"


def test_adapted_output_is_separate_from_project_json(tmp_path):
    store = AdaptedScreenplayStore(tmp_path)
    project_file = tmp_path / "projects" / "PERSIST_PROJECT" / "project.json"
    project_file.parent.mkdir(parents=True)
    original_project_bytes = b'{"source": "untouched"}\n'
    project_file.write_bytes(original_project_bytes)
    store.save_adapted_screenplay(screenplay())
    assert project_file.read_bytes() == original_project_bytes
    assert (project_file.parent / "adapted_screenplay.json").exists()


def test_unsafe_project_id_rejected(tmp_path):
    store = AdaptedScreenplayStore(tmp_path)
    with pytest.raises(ValueError):
        store.exists("../other")
