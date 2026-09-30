from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent))
from test_screenplay_adapter import RAW, evidence_pack, make_change, make_plan, sample_state

from app.models.adaptation import AdaptationCategory
from app.services.adaptation_store import AdaptationStore
from app.services.adapted_screenplay_store import AdaptedScreenplayStore
from app.services.project_store import ProjectStore
from app.services.screenplay_adapter import adapt_screenplay
from app.services.visual_pack_generator import MockVisualPackGenerator
from app.services.visual_pack_store import VisualPackLoadError, VisualPackStore


def make_pack(tmp_path):
    state = sample_state()
    _, evidence = evidence_pack(tmp_path / "culture")
    change = make_change("COSTUME_STORE", status="approved", category=AdaptationCategory.COSTUME,
                         target_type="character", target_id="CHAR_001", evidence_ids=["EVID_005"])
    plan = make_plan([change])
    adapted = adapt_screenplay(state, plan, evidence, RAW)
    pack = MockVisualPackGenerator().generate(state, adapted, plan, evidence)
    return state, plan, adapted, pack


def test_save_and_load_round_trip_preserves_evidence_ids_stable_ids_and_validation(tmp_path):
    state, plan, adapted, pack = make_pack(tmp_path)
    store = VisualPackStore(tmp_path / "data")
    saved = store.save_pack(pack)
    loaded = VisualPackStore(tmp_path / "data").load_pack(state.project_id)
    assert store.pack_exists(state.project_id)
    assert loaded.model_dump(mode="json") == saved.model_dump(mode="json")
    assert [b.character_id for b in loaded.character_bibles] == [c.character_id for c in state.characters]
    assert loaded.costume_bibles[0].costume_id == pack.costume_bibles[0].costume_id
    assert loaded.scene_keyframes[1].evidence_ids == ["EVID_005"]
    assert loaded.version == 1
    assert loaded.validation_result.valid


def test_missing_pack_and_invalid_json_are_reported(tmp_path):
    store = VisualPackStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.load_pack("MISSING")
    path = tmp_path / "projects" / "BROKEN" / "visual_production_pack.json"
    path.parent.mkdir(parents=True); path.write_text("{bad json", encoding="utf-8")
    with pytest.raises(VisualPackLoadError):
        store.load_pack("BROKEN")


def test_save_versions_updates_but_preserves_creation_time_and_ids(tmp_path):
    _, _, _, pack = make_pack(tmp_path)
    store = VisualPackStore(tmp_path / "data")
    first = store.save_pack(pack)
    second = store.save_pack(first.model_copy(update={"validation_result": first.validation_result.model_copy(update={"warnings": ["reviewed"]})}))
    assert first.version == 1 and second.version == 2
    assert second.created_at == first.created_at
    assert second.updated_at != first.updated_at
    assert [item.costume_id for item in second.costume_bibles] == [item.costume_id for item in first.costume_bibles]


def test_malformed_project_ids_are_rejected(tmp_path):
    store = VisualPackStore(tmp_path)
    with pytest.raises(ValueError):
        store.load_pack("../escape")
    _, _, _, pack = make_pack(tmp_path)
    with pytest.raises(ValueError):
        store.save_pack(pack.model_copy(update={"project_id": "../escape"}))


def test_visual_pack_persistence_does_not_change_project_plan_or_adapted_files(tmp_path):
    state, plan, adapted, pack = make_pack(tmp_path)
    data_root = tmp_path / "data"
    project_store = ProjectStore(data_root)
    plan_store = AdaptationStore(data_root)
    adapted_store = AdaptedScreenplayStore(data_root)
    project_store.save_project(state)
    plan_store.save_plan(plan)
    adapted_store.save_adapted_screenplay(adapted)
    before = {
        "project": project_store.load_project(state.project_id).model_dump(mode="json"),
        "plan": plan_store.load_plan(state.project_id).model_dump(mode="json"),
        "adapted": adapted_store.load_adapted_screenplay(state.project_id).model_dump(mode="json"),
    }
    VisualPackStore(data_root).save_pack(pack)
    assert project_store.load_project(state.project_id).model_dump(mode="json") == before["project"]
    assert plan_store.load_plan(state.project_id).model_dump(mode="json") == before["plan"]
    assert adapted_store.load_adapted_screenplay(state.project_id).model_dump(mode="json") == before["adapted"]
