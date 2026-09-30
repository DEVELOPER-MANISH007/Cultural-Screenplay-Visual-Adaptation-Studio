import pytest
from pydantic import ValidationError

from app.models.adaptation import (
    AdaptationCategory, AdaptationChange, AdaptationChangeStatus, AdaptationPlan,
    AdaptationPlanStatus,
)
from app.models.cultural_evidence import CulturalEvidenceStatus
from app.models.extraction import Character, ProductionElement, Scene, ScreenplayExtraction
from app.models.project_state import ProjectState, ProjectStateStatus
from app.services.adaptation_planner import (
    DIALECT_WARNING, GENERAL_WARNING, MockAdaptationPlanner, create_adaptation_plan,
    validate_plan_references,
)
from app.services.cultural_pack import seed_marwari_marwar_pack
from app.services.cultural_store import CulturalStore


def state(*, culture="Marwari", region="Marwar / Jodhpur", scene_summaries=None):
    scene_summaries = scene_summaries or [
        ("SCENE_001", "INT. HOUSE - DAY", "Ravi waits beside a table and letter."),
        ("SCENE_002", "EXT. VILLAGE - NIGHT", "Ravi returns to the village."),
    ]
    scenes = [Scene(scene_id=sid, scene_number=i + 1, heading=heading, location=None,
                    summary=summary, character_ids=["CHAR_001"], production_element_ids=[])
              for i, (sid, heading, summary) in enumerate(scene_summaries)]
    char = Character(character_id="CHAR_001", canonical_name="Ravi", aliases=["Ravi Kumar"],
                     age="adult", role="protagonist", relationships={"CHAR_002": "brother"},
                     personality=["reserved"], emotional_state="worried", scene_ids=[x.scene_id for x in scenes])
    return ProjectState(project_id="PROJECT_1", screenplay_id="SCREEN_1", title="Test", culture=culture,
                        dialect="Marwari", region=region, setting="Rural", script="Devanagari",
                        scenes=scenes, characters=[char], locations=[], production_elements=[],
                        continuity_states=[], updated_at="2026-09-29T10:00:00+00:00",
                        state_status=ProjectStateStatus.EXTRACTED)


def pack(tmp_path):
    store = seed_marwari_marwar_pack(CulturalStore(tmp_path))
    return store, list(store.evidence.values())


def test_plan_and_change_models_validate_status_and_context():
    change = AdaptationChange(change_id="CHANGE_001", scene_id="SCENE_001", category="dialect",
        target_type="character", target_id="CHAR_001", original_element="Original line",
        proposed_change="Queue for expert review", rationale="Phrase evidence is missing",
        evidence_ids=[], confidence=0, status="insufficient_evidence")
    plan = AdaptationPlan(plan_id="PLAN_1", project_id="PROJECT_1", culture="Marwari", dialect="Marwari",
        region="Marwar / Jodhpur", setting="Rural", script="Devanagari", status="pending_review",
        changes=[change], created_at="2026-09-29T10:00:00+00:00", updated_at="2026-09-29T10:00:00+00:00")
    assert plan.status == AdaptationPlanStatus.PENDING_REVIEW
    assert plan.changes[0].status == AdaptationChangeStatus.INSUFFICIENT_EVIDENCE
    with pytest.raises(ValidationError):
        AdaptationChange.model_validate({**change.model_dump(), "confidence": 2.0})
    with pytest.raises(ValidationError):
        AdaptationPlan(**{**plan.model_dump(), "created_at": "yesterday"})


def test_planner_uses_canonical_scene_and_character_ids_and_project_context(tmp_path):
    _, evidence = pack(tmp_path)
    project = state()
    plan = create_adaptation_plan(project, evidence)
    assert (plan.culture, plan.region, plan.setting, plan.script) == ("Marwari", "Marwar / Jodhpur", "Rural", "Devanagari")
    assert all(change.scene_id.startswith("SCENE_") for change in plan.changes)
    assert all(change.target_id == "CHAR_001" for change in plan.changes if change.target_type == "character")
    assert plan.status == "pending_review"
    assert all(change.status != "approved" for change in plan.changes)


def test_phrase_level_dialect_is_never_invented_and_has_insufficient_status(tmp_path):
    store, evidence = pack(tmp_path)
    project = state()
    raw = "INT. HOUSE - DAY\nRAVI\nI need the letter.\n\nEXT. VILLAGE - NIGHT\nRAVI\nWe should go."
    plan = create_adaptation_plan(project, evidence, language_evidence=list(store.language_evidence.values()), raw_text=raw)
    dialect = [c for c in plan.changes if c.category == AdaptationCategory.DIALECT]
    assert len(dialect) == 2
    assert all(c.status == AdaptationChangeStatus.INSUFFICIENT_EVIDENCE and c.evidence_ids == [] for c in dialect)
    assert "I need the letter." in dialect[0].original_element
    assert all("Marwari" not in c.proposed_change or "reviewer" in c.proposed_change for c in dialect)
    assert any(DIALECT_WARNING in w for w in plan.global_warnings)


def test_no_raw_text_does_not_fabricate_exact_dialogue(tmp_path):
    _, evidence = pack(tmp_path)
    plan = create_adaptation_plan(state(), evidence)
    dialect = [c for c in plan.changes if c.category == "dialect"]
    assert dialect and all("not present in the structured extraction" in c.original_element for c in dialect)
    assert all(not c.evidence_ids and c.status == "insufficient_evidence" for c in dialect)


def test_rajasthan_general_source_gets_scope_warning_and_never_marwar_label(tmp_path):
    store, evidence = pack(tmp_path)
    project = state(scene_summaries=[("SCENE_001", "INT. WEDDING HOUSE - DAY", "The family prepares a wedding ritual and toran.")])
    plan = create_adaptation_plan(project, evidence)
    ritual = next(c for c in plan.changes if c.category == AdaptationCategory.RITUAL)
    assert ritual.status == AdaptationChangeStatus.NEEDS_REVIEW
    assert "EVID_011" in ritual.evidence_ids
    assert GENERAL_WARNING in ritual.warnings
    assert store.get_evidence("EVID_011").scope == "Rajasthan-general"


def test_insufficient_evidence_creates_review_item_without_fake_ids(tmp_path):
    _, evidence = pack(tmp_path)
    plan = create_adaptation_plan(state(), evidence)
    costumes = [c for c in plan.changes if c.category == AdaptationCategory.COSTUME]
    assert costumes
    assert all(c.status == "insufficient_evidence" and c.evidence_ids == [] for c in costumes)
    assert all(any("Insufficient evidence" in w for w in c.warnings) for c in costumes)


def test_evidence_supported_festival_changes_resolve_exact_records(tmp_path):
    _, evidence = pack(tmp_path)
    project = state(scene_summaries=[("SCENE_001", "EXT. MARWAR FESTIVAL - DAY",
        "Folk music plays while performers present Ghoomar dance at the festival in Jodhpur.")])
    plan = create_adaptation_plan(project, evidence)
    music = [c for c in plan.changes if c.category == AdaptationCategory.MUSIC]
    assert music
    assert all(c.status == "pending" and c.evidence_ids for c in music)
    catalog = {item.evidence_id for item in evidence}
    assert all(set(c.evidence_ids) <= catalog for c in music)


def test_fake_evidence_and_scene_ids_are_rejected(tmp_path):
    _, evidence = pack(tmp_path)
    project = state()
    plan = create_adaptation_plan(project, evidence)
    change = plan.changes[0].model_copy(update={"evidence_ids": ["EVID_FAKE"]})
    bad = plan.model_copy(update={"changes": [change, *plan.changes[1:]]})
    with pytest.raises(ValueError, match="unknown evidence IDs"):
        validate_plan_references(bad, project, evidence)
    change = plan.changes[0].model_copy(update={"scene_id": "SCENE_FAKE"})
    bad = plan.model_copy(update={"changes": [change, *plan.changes[1:]]})
    with pytest.raises(ValueError, match="unknown scene"):
        validate_plan_references(bad, project, evidence)


def test_character_and_production_targets_must_be_canonical(tmp_path):
    _, evidence = pack(tmp_path)
    project = state()
    plan = create_adaptation_plan(project, evidence)
    char_change = next(c for c in plan.changes if c.target_type == "character")
    bad = plan.model_copy(update={"changes": [char_change.model_copy(update={"target_id": "Ravi"})]})
    with pytest.raises(ValueError, match="unknown character"):
        validate_plan_references(bad, project, evidence)


def test_planner_preserves_story_logic_and_does_not_mutate_source(tmp_path):
    _, evidence = pack(tmp_path)
    project = state()
    before = project.model_dump(mode="json")
    original_order = [s.scene_id for s in project.scenes]
    plan = create_adaptation_plan(project, evidence)
    assert project.model_dump(mode="json") == before
    assert [s.scene_id for s in project.scenes] == original_order
    assert all("events" in c.proposed_change or "story" in c.proposed_change or "dialogue" in c.proposed_change
               or "costume" in c.proposed_change or "concrete costume" in c.proposed_change
               or "identity" in c.proposed_change or "detail" in c.proposed_change or "clothing" in c.proposed_change
               for c in plan.changes)


def test_recurring_character_review_protects_relationship_and_identity(tmp_path):
    _, evidence = pack(tmp_path)
    plan = create_adaptation_plan(state(), evidence)
    review = next(c for c in plan.changes if c.category == AdaptationCategory.CHARACTER)
    assert review.target_id == "CHAR_001"
    assert "relationships" in review.original_element
    assert "Preserve" in review.proposed_change
    assert review.evidence_ids == []


def test_multiple_changes_can_target_one_scene_and_json_round_trip(tmp_path):
    store, evidence = pack(tmp_path)
    project = state(scene_summaries=[("SCENE_001", "EXT. MARWAR FESTIVAL - DAY",
        "Ravi sings as Ghoomar dancers perform at the Marwar Festival.")])
    plan = create_adaptation_plan(project, evidence)
    assert len([c for c in plan.changes if c.scene_id == "SCENE_001"]) > 1
    encoded = plan.model_dump_json()
    restored = AdaptationPlan.model_validate_json(encoded)
    assert restored == plan
    assert all(store.get_evidence(eid) for change in plan.changes for eid in change.evidence_ids)


def test_mock_planner_is_deterministic_offline(tmp_path):
    _, evidence = pack(tmp_path)
    project = state()
    planner = MockAdaptationPlanner()
    first = planner.create_adaptation_plan(project, evidence)
    second = planner.create_adaptation_plan(project, evidence)
    assert first == second


def test_extraction_mismatch_is_rejected(tmp_path):
    _, evidence = pack(tmp_path)
    project = state()
    extraction = ScreenplayExtraction(screenplay_id="OTHER", scenes=[
        {"scene_id": "SCENE_001", "scene_number": 1, "heading": "INT. HOUSE - DAY", "summary": "x"}
    ])
    with pytest.raises(ValueError, match="does not belong"):
        create_adaptation_plan(project, evidence, extraction=extraction)


def test_approval_and_rejection_statuses_are_supported_but_never_default():
    base = AdaptationChange(change_id="C", scene_id="S", category="props", target_type="scene",
        target_id="S", original_element="Letter", proposed_change="Review it", rationale="Test", confidence=0.5)
    assert base.status == AdaptationChangeStatus.PENDING
    approved = AdaptationChange.model_validate({**base.model_dump(), "status": "approved"})
    rejected = AdaptationChange.model_validate({**base.model_dump(), "status": "rejected"})
    assert approved.status == AdaptationChangeStatus.APPROVED
    assert rejected.status == AdaptationChangeStatus.REJECTED


def test_costume_review_uses_canonical_production_element_id(tmp_path):
    from app.models.extraction import ProductionElement
    _, evidence = pack(tmp_path)
    project = state()
    project.production_elements = [ProductionElement(element_id="COSTUME_001", category="costume",
        name="jacket", description="A worn jacket", scenes=["SCENE_001"])]
    plan = create_adaptation_plan(project, evidence)
    costume = next(change for change in plan.changes if change.category == AdaptationCategory.COSTUME
                   and change.scene_id == "SCENE_001")
    assert costume.target_type == "production_element"
    assert costume.target_id == "COSTUME_001"


def test_conflicting_evidence_is_reported_and_never_silently_resolved(tmp_path):
    from app.models.cultural_evidence import CulturalEvidence
    store, evidence = pack(tmp_path)
    original = store.get_evidence("EVID_009")
    competing = original.model_copy(update={
        "evidence_id": "EVID_CONFLICT", "claim": "The festival is described as featuring no folk music.",
        "conflict_group": "festival-music",
    })
    original = original.model_copy(update={"conflict_group": "festival-music"})
    evidence = [original if e.evidence_id == original.evidence_id else e for e in evidence] + [competing]
    project = state(scene_summaries=[("SCENE_001", "EXT. MARWAR FESTIVAL - DAY",
        "Folk music plays at the festival in Jodhpur.")])
    plan = create_adaptation_plan(project, evidence)
    music = next(c for c in plan.changes if c.category == AdaptationCategory.MUSIC)
    assert music.status == AdaptationChangeStatus.NEEDS_REVIEW
    assert set(music.evidence_ids) == {"EVID_009", "EVID_CONFLICT"}
    assert any("Cultural evidence conflict" in w for w in plan.global_warnings)
