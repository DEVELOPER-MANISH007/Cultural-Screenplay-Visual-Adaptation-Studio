import json
import shutil
from pathlib import Path

import pytest

from app.models.adaptation import (
    AdaptationCategory, AdaptationChange, AdaptationChangeStatus, AdaptationPlan,
    AdaptationPlanStatus,
)
from app.services.adaptation_store import AdaptationPlanLoadError, AdaptationStore
from app.services.cultural_store import CulturalStore


def make_plan():
    change = AdaptationChange(
        change_id="CHANGE_001", scene_id="SCENE_001", category=AdaptationCategory.COSTUME,
        target_type="character", target_id="CHAR_001", original_element="No costume specified",
        proposed_change="Wait for human review", rationale="No specific evidence yet.",
        evidence_ids=["EVID_005"], confidence=0.7, status=AdaptationChangeStatus.PENDING,
    )
    return AdaptationPlan(
        plan_id="PLAN_STORE", project_id="PROJECT_STORE", culture="Marwari", dialect="Marwari",
        region="Marwar / Jodhpur", setting="Rural", script="Devanagari",
        status=AdaptationPlanStatus.PENDING_REVIEW, changes=[change],
        created_at="2026-09-29T10:00:00+00:00", updated_at="2026-09-29T10:00:00+00:00",
    )


def test_save_and_load_adaptation_plan(tmp_path):
    store = AdaptationStore(tmp_path)
    saved = store.save_plan(make_plan())
    assert saved.version == 1
    assert (tmp_path / "projects" / "PROJECT_STORE" / "adaptation_plan.json").is_file()
    assert store.load_plan("PROJECT_STORE") == saved
    assert store.plan_exists("PROJECT_STORE")


def test_missing_plan_has_clear_error(tmp_path):
    store = AdaptationStore(tmp_path)
    assert not store.plan_exists("missing")
    with pytest.raises(FileNotFoundError, match="not found"):
        store.load_plan("missing")


def test_invalid_plan_json_is_rejected(tmp_path):
    path = tmp_path / "projects" / "PROJECT_STORE" / "adaptation_plan.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ broken", encoding="utf-8")
    with pytest.raises(AdaptationPlanLoadError, match="Invalid adaptation plan"):
        AdaptationStore(tmp_path).load_plan("PROJECT_STORE")


def test_new_plan_version_and_timestamp_are_retained(tmp_path):
    saved = AdaptationStore(tmp_path).save_plan(make_plan())
    assert saved.version == 1
    assert saved.created_at == "2026-09-29T10:00:00+00:00"
    assert saved.updated_at == "2026-09-29T10:00:00+00:00"


@pytest.mark.parametrize("status", ["approved", "rejected", "needs_revision"] )
def test_review_status_update_increments_version_and_persists_after_new_store(tmp_path, status):
    store = AdaptationStore(tmp_path)
    original = store.save_plan(make_plan())
    updated_change = original.changes[0].model_copy(update={"status": AdaptationChangeStatus(status)})
    updated = original.model_copy(update={"changes": [updated_change]})
    persisted = store.update_plan(updated)
    assert persisted.version == 2
    assert persisted.updated_at != original.updated_at
    restarted = AdaptationStore(tmp_path).load_plan("PROJECT_STORE")
    assert restarted.changes[0].status.value == status
    assert restarted.version == 2


def test_plan_status_change_is_persisted_and_versions_increment(tmp_path):
    store = AdaptationStore(tmp_path)
    original = store.save_plan(make_plan())
    reviewed = original.model_copy(update={"status": AdaptationPlanStatus.APPROVED})
    saved = store.update_plan(reviewed)
    assert saved.status == AdaptationPlanStatus.APPROVED
    assert saved.version == 2


def test_unchanged_review_state_does_not_increment_version(tmp_path):
    store = AdaptationStore(tmp_path)
    original = store.save_plan(make_plan())
    assert store.update_plan(original).version == 1


def test_change_ids_and_evidence_ids_remain_stable(tmp_path):
    store = AdaptationStore(tmp_path)
    original = store.save_plan(make_plan())
    updated = original.model_copy(update={"changes": [original.changes[0].model_copy(update={"status": AdaptationChangeStatus.APPROVED})]})
    saved = store.update_plan(updated)
    assert [c.change_id for c in saved.changes] == ["CHANGE_001"]
    assert saved.changes[0].evidence_ids == ["EVID_005"]
    assert json.loads((tmp_path / "projects" / "PROJECT_STORE" / "adaptation_plan.json").read_text())["changes"][0]["evidence_ids"] == ["EVID_005"]


def test_update_rejects_changed_change_ids_or_plan_content(tmp_path):
    store = AdaptationStore(tmp_path)
    original = store.save_plan(make_plan())
    with pytest.raises(ValueError, match="change_id values"):
        store.update_plan(original.model_copy(update={"changes": [original.changes[0].model_copy(update={"change_id": "CHANGED"})]}))
    with pytest.raises(ValueError, match="only accepts"):
        store.update_plan(original.model_copy(update={"culture": "Different"}))


def test_save_does_not_overwrite_existing_review_decisions(tmp_path):
    store = AdaptationStore(tmp_path)
    original = store.save_plan(make_plan())
    approved = original.model_copy(update={"changes": [original.changes[0].model_copy(update={"status": AdaptationChangeStatus.APPROVED})]})
    saved = store.update_plan(approved)
    with pytest.raises(FileExistsError):
        store.save_plan(make_plan())
    assert store.load_plan("PROJECT_STORE").changes[0].status == saved.changes[0].status


def test_append_production_design_proposal_preserves_reviewed_plan_and_other_artifacts(tmp_path):
    project_id = "7e0998d005d641f28e7ef6cba2806be9"
    repo_root = Path(__file__).resolve().parents[1]
    persisted = AdaptationStore(repo_root / "data").load_plan(project_id)
    evidence_path = repo_root / "data" / "culture" / "marwari_marwar" / "evidence.json"
    evidence_bytes = evidence_path.read_bytes()
    evidence = CulturalStore(repo_root / "data" / "culture" / "marwari_marwar").load().get_evidence("EVID_005")
    evidence_snapshot = evidence.model_dump(mode="json")
    prior_changes = [change for change in persisted.changes if change.change_id != "CHANGE_011"]
    assert len(prior_changes) == 10
    assert all(change.status == AdaptationChangeStatus.REJECTED for change in prior_changes)
    baseline = persisted.model_copy(update={
        "changes": prior_changes,
        "status": AdaptationPlanStatus.REJECTED,
        "version": 2,
        "updated_at": "2026-09-29T11:34:08.171020+00:00",
    })

    project_dir = tmp_path / "projects" / project_id
    project_dir.mkdir(parents=True)
    for name in ("project.json", "adapted_screenplay.json"):
        shutil.copyfile(repo_root / "data" / "projects" / project_id / name, project_dir / name)
    downstream = {
        name: f"preserve:{name}".encode()
        for name in ("visual_production_pack.json", "visual_artifacts.json", "final_validation.json", "export_manifest.json")
    }
    for name, content in downstream.items():
        (project_dir / name).write_bytes(content)

    store = AdaptationStore(tmp_path)
    store.save_plan(baseline)
    saved = store.append_change(
        project_id,
        scene_id="SCENE_002",
        category=AdaptationCategory.PRODUCTION_DESIGN,
        target_type="scene",
        target_id="SCENE_002",
        original_element="Ravi and Meena walk through the market.",
        proposed_change="Add restrained background merchandise detail showing bandhej fabric being sold in Jodhpur market.",
        rationale="The Jodhpur market location is an explicit human-provided production context. EVID_005 supports bandhej fabric being available for purchase in Jodhpur; the proposal keeps it in background merchandise only.",
        evidence_ids=["EVID_005"],
        confidence=0.94,
        assumptions=["Jodhpur market location is human-provided production context, not inferred from screenplay."],
        warnings=["Background merchandise only; do not put bandhej fabric on Ravi or Meena.",
                  "Do not change clothing, dialogue, action, dramatic purpose, scene order, music, dance, rituals, or food.",
                  "Explicit human approval is required before Phase 6 can apply this proposal."],
    )

    assert [change.model_dump(mode="json") for change in saved.changes[:10]] == [
        change.model_dump(mode="json") for change in prior_changes
    ]
    proposal = saved.changes[-1]
    assert proposal.change_id == "CHANGE_011"
    assert proposal.category == AdaptationCategory.PRODUCTION_DESIGN
    assert proposal.scene_id == proposal.target_id == "SCENE_002"
    assert proposal.evidence_ids == ["EVID_005"]
    assert proposal.status == AdaptationChangeStatus.PENDING
    assert proposal.proposed_change == "Add restrained background merchandise detail showing bandhej fabric being sold in Jodhpur market."
    assert saved.version == baseline.version + 1
    assert saved.status == AdaptationPlanStatus.PENDING_REVIEW

    reloaded = AdaptationStore(tmp_path).load_plan(project_id)
    assert reloaded == saved
    assert [change.model_dump(mode="json") for change in reloaded.changes[:10]] == [
        change.model_dump(mode="json") for change in prior_changes
    ]
    assert reloaded.changes[-1].status == AdaptationChangeStatus.PENDING
    assert (project_dir / "project.json").read_bytes() == (repo_root / "data" / "projects" / project_id / "project.json").read_bytes()
    assert (project_dir / "adapted_screenplay.json").read_bytes() == (repo_root / "data" / "projects" / project_id / "adapted_screenplay.json").read_bytes()
    assert {name: (project_dir / name).read_bytes() for name in downstream} == downstream
    assert evidence_path.read_bytes() == evidence_bytes
    assert CulturalStore(repo_root / "data" / "culture" / "marwari_marwar").load().get_evidence("EVID_005").model_dump(mode="json") == evidence_snapshot
