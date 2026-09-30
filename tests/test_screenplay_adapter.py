from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.adaptation import AdaptationCategory, AdaptationChange, AdaptationChangeStatus, AdaptationPlan
from app.models.adapted_screenplay import AdaptationValidationResult, AdaptedScene, AdaptedScreenplay
from app.models.cultural_evidence import CulturalEvidence, CulturalEvidenceStatus
from app.models.extraction import Character, Location, ProductionElement, Scene
from app.models.project_state import ProjectState, ProjectStateStatus
from app.models.screenplay import ScreenplayDocument, SourceType
from app.services.adaptation_store import AdaptationStore
from app.services.adaptation_validator import validate_adapted_screenplay
from app.services.cultural_pack import seed_marwari_marwar_pack
from app.services.cultural_store import CulturalStore
from app.services.screenplay_adapter import (
    DIALECT_WARNING, MockScreenplayAdapter, _validate_approved_change,
    adapt_persisted_screenplay, adapt_screenplay,
)


RAW = """INT. COURTYARD - MORNING

RAVI enters the courtyard carrying an old envelope.

RAVI
I found this under the old table.

MEENA
What is it?

Ravi gives the envelope to Meena.

EXT. MARKET - AFTERNOON

Ravi and Meena walk through the market.

RAVI
We need to find out who wrote this letter.
"""


def sample_state():
    return ProjectState(
        project_id="RAVI_MEENA", screenplay_id="SCREENPLAY_SAMPLE", title="Ravi and Meena",
        culture="Marwari", dialect="Marwari", region="Marwar / Jodhpur", setting="Rural", script="Devanagari",
        scenes=[
            Scene(scene_id="SCENE_001", scene_number=1, heading="INT. COURTYARD - MORNING", location="Courtyard",
                  summary="Ravi and Meena meet in a courtyard and exchange an envelope.",
                  character_ids=["CHAR_001", "CHAR_002"], production_element_ids=["PROP_001", "PROP_002"]),
            Scene(scene_id="SCENE_002", scene_number=2, heading="EXT. MARKET - AFTERNOON", location="Market",
                  summary="Ravi and Meena walk through a market and discuss a letter.",
                  character_ids=["CHAR_001", "CHAR_002"], production_element_ids=["PROP_003"]),
        ],
        characters=[
            Character(character_id="CHAR_001", canonical_name="Ravi", role="protagonist", scene_ids=["SCENE_001", "SCENE_002"]),
            Character(character_id="CHAR_002", canonical_name="Meena", role="supporting character", scene_ids=["SCENE_001", "SCENE_002"]),
        ],
        locations=[Location(location_id="LOC_001", canonical_name="Courtyard", scenes=["SCENE_001"]),
                   Location(location_id="LOC_002", canonical_name="Market", scenes=["SCENE_002"])],
        production_elements=[
            ProductionElement(element_id="PROP_001", category="prop", name="old envelope", scenes=["SCENE_001"]),
            ProductionElement(element_id="PROP_002", category="prop", name="old table", scenes=["SCENE_001"]),
            ProductionElement(element_id="PROP_003", category="prop", name="letter", scenes=["SCENE_002"]),
        ], continuity_states=[], version=1, updated_at="2026-09-29T10:00:00+00:00",
        state_status=ProjectStateStatus.EXTRACTED,
    )


def make_change(change_id, *, status="pending", scene_id="SCENE_002", category="costume",
                target_type="scene", target_id=None, evidence_ids=None, proposed=None):
    return AdaptationChange(
        change_id=change_id, scene_id=scene_id, category=category, target_type=target_type,
        target_id=target_id or scene_id, original_element="Ravi and Meena walk through the market.",
        proposed_change=proposed or "Add a Jodhpur-associated bandhej textile stall as a background detail; keep all events and dialogue unchanged.",
        rationale="A human approved this bounded optional visual detail based on the cited craft/location evidence.",
        evidence_ids=evidence_ids if evidence_ids is not None else ["EVID_005"], confidence=0.94,
        status=status,
    )


def make_plan(changes=None):
    return AdaptationPlan(
        plan_id="PLAN_RAVI_MEENA", project_id="RAVI_MEENA", culture="Marwari", dialect="Marwari",
        region="Marwar / Jodhpur", setting="Rural", script="Devanagari", status="pending_review", version=2,
        changes=changes if changes is not None else [
            make_change("CHANGE_APPROVED", status="approved"),
            make_change("CHANGE_REJECTED", status="rejected"),
            make_change("CHANGE_PENDING", status="pending"),
        ], global_warnings=[], unresolved_questions=[],
        created_at="2026-09-29T10:00:00+00:00", updated_at="2026-09-29T10:05:00+00:00",
    )


def make_change_011(*, status="approved", evidence_ids=None, scene_id="SCENE_002",
                    target_type="scene", target_id=None, proposed=None):
    return AdaptationChange(
        change_id="CHANGE_011", scene_id=scene_id, category=AdaptationCategory.PRODUCTION_DESIGN,
        target_type=target_type, target_id=target_id or scene_id,
        original_element="Ravi and Meena walk through the market.",
        proposed_change=proposed or "Add restrained background merchandise detail showing bandhej fabric being sold in Jodhpur market.",
        rationale="The Jodhpur market is human-provided context; EVID_005 supports bandhej availability there.",
        evidence_ids=evidence_ids if evidence_ids is not None else ["EVID_005"], confidence=0.94,
        status=status,
        assumptions=[
            "Jodhpur market context was explicitly provided by the human producer; it was not inferred from the screenplay.",
            "Bandhej fabric appears only as background merchandise for sale; it is not worn by Ravi or Meena.",
        ],
        warnings=[
            "Do not use festival evidence for this ordinary market scene.",
            "Do not change Ravi or Meena clothing, dialogue, character action, dramatic purpose, or scene order.",
            "Do not add music, dance, rituals, or food.",
            "Explicit human approval is required before Phase 6 can apply this proposal.",
        ],
    )


def evidence_pack(tmp_path):
    store = seed_marwari_marwar_pack(CulturalStore(tmp_path))
    return store, list(store.evidence.values())


def test_adapted_screenplay_and_scene_models_validate():
    scene = AdaptedScene(scene_id="SCENE_001", scene_number=1, original_heading="INT. ROOM - DAY",
        adapted_heading="INT. ROOM - DAY", original_text="INT. ROOM - DAY\n", adapted_text="INT. ROOM - DAY\n")
    result = AdaptationValidationResult(valid=True, checked_scene_count=1, applied_change_count=0)
    screenplay = AdaptedScreenplay(adaptation_id="ADAPT_1", project_id="p", source_screenplay_id="s",
        plan_id="plan", plan_version=1, culture="Marwari", region="Marwar / Jodhpur", setting="Rural",
        scenes=[scene], created_at="2026-09-29T10:00:00+00:00", updated_at="2026-09-29T10:00:00+00:00")
    assert screenplay.scenes[0].scene_id == "SCENE_001" and result.valid
    with pytest.raises(ValidationError):
        AdaptedScene(scene_id="", scene_number=0, original_heading="", adapted_heading="", original_text="", adapted_text="")


def test_only_approved_evidence_compatible_change_is_applied(tmp_path):
    project = sample_state()
    source, evidence = evidence_pack(tmp_path)
    plan = make_plan()
    result = adapt_screenplay(project, plan, evidence, RAW)
    assert result.applied_change_ids == ["CHANGE_APPROVED"]
    assert result.blocked_change_ids == []
    assert "MOCK APPLIED CHANGE_APPROVED" in result.adapted_screenplay_text
    assert "MOCK APPLIED CHANGE_REJECTED" not in result.adapted_screenplay_text
    assert "MOCK APPLIED CHANGE_PENDING" not in result.adapted_screenplay_text
    assert result.scenes[1].evidence_ids == ["EVID_005"]
    assert source.get_evidence("EVID_005").source_id in source.sources


@pytest.mark.parametrize("status", ["pending", "rejected", "needs_revision"])
def test_nonapproved_statuses_never_modify_screenplay(tmp_path, status):
    project = sample_state()
    _, evidence = evidence_pack(tmp_path)
    change = make_change("CHANGE_NOT_APPROVED", status=status)
    result = adapt_screenplay(project, make_plan([change]), evidence, RAW)
    assert result.applied_change_ids == []
    assert result.adapted_screenplay_text == RAW
    assert result.original_screenplay_text == RAW
    assert "not applied" in " ".join(result.warnings)


def test_no_approved_changes_output_is_equivalent_to_original(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    plan = make_plan([make_change("C1", status="pending"), make_change("C2", status="rejected")])
    result = adapt_screenplay(sample_state(), plan, evidence, RAW)
    assert result.adapted_screenplay_text == RAW


def test_missing_evidence_id_blocks_change_instead_of_silently_applying(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    plan = make_plan([make_change("CHANGE_BAD_EVIDENCE", status="approved", evidence_ids=["EVID_MISSING"])])
    result = adapt_screenplay(sample_state(), plan, evidence, RAW)
    assert result.applied_change_ids == []
    assert result.blocked_change_ids == ["CHANGE_BAD_EVIDENCE"]
    assert any("does not exist" in warning for warning in result.warnings)
    assert result.adapted_screenplay_text == RAW


def test_missing_scene_and_target_ids_block_change(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    wrong_scene = make_change("BAD_SCENE", status="approved", scene_id="SCENE_999")
    wrong_target = make_change("BAD_TARGET", status="approved", target_type="character", target_id="CHAR_FAKE")
    result = adapt_screenplay(sample_state(), make_plan([wrong_scene, wrong_target]), evidence, RAW)
    assert set(result.blocked_change_ids) == {"BAD_SCENE", "BAD_TARGET"}
    assert not result.applied_change_ids


def test_rrajasthan_general_and_wrong_category_evidence_are_blocked(tmp_path):
    source, evidence = evidence_pack(tmp_path)
    general = source.get_evidence("EVID_011")
    change = make_change("GENERAL", status="approved", category="ritual", scene_id="SCENE_001",
                         evidence_ids=[general.evidence_id], proposed="Apply the wedding ritual detail.")
    wrong_category = make_change("WRONG_CATEGORY", status="approved", category="food", evidence_ids=["EVID_005"])
    result = adapt_screenplay(sample_state(), make_plan([change, wrong_category]), evidence, RAW)
    assert set(result.blocked_change_ids) == {"GENERAL", "WRONG_CATEGORY"}
    assert any("Rajasthan-general" in warning for warning in result.warnings)
    assert not result.applied_change_ids


def test_unsupported_marwari_dialect_is_blocked_without_inventing_phrases(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    dialogue = make_change("DIALECT", status="approved", category="dialect", scene_id="SCENE_001",
                           target_type="character", target_id="CHAR_001", evidence_ids=["EVID_002"],
                           proposed="Replace dialogue with a Marwari sounding phrase.")
    result = adapt_screenplay(sample_state(), make_plan([dialogue]), evidence, RAW)
    assert result.applied_change_ids == []
    assert result.blocked_change_ids == ["DIALECT"]
    assert DIALECT_WARNING in " ".join(result.warnings)
    assert RAW == result.adapted_screenplay_text


def test_scene_order_count_numbers_and_canonical_ids_are_preserved(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    project = sample_state()
    result = adapt_screenplay(project, make_plan(), evidence, RAW)
    assert len(result.scenes) == len(project.scenes) == 2
    assert [s.scene_id for s in result.scenes] == [s.scene_id for s in project.scenes]
    assert [s.scene_number for s in result.scenes] == [1, 2]


def test_original_screenplay_and_project_are_not_mutated(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    project = sample_state()
    original_project = project.model_dump(mode="json")
    result = adapt_screenplay(project, make_plan(), evidence, ScreenplayDocument(source_type=SourceType.PASTED_TEXT, raw_text=RAW))
    assert project.model_dump(mode="json") == original_project
    assert result.original_screenplay_text == RAW
    assert result.adapted_screenplay_text.startswith(RAW[:result.adapted_screenplay_text.index("[MOCK APPLIED")])
    assert "I found this under the old table." in result.adapted_screenplay_text
    assert "What is it?" in result.adapted_screenplay_text


def test_traceability_links_scene_change_evidence_and_source(tmp_path):
    store, evidence = evidence_pack(tmp_path)
    result = adapt_screenplay(sample_state(), make_plan(), evidence, RAW)
    assert result.scenes[1].applied_change_ids == ["CHANGE_APPROVED"]
    assert result.scenes[1].evidence_ids == ["EVID_005"]
    ev = store.get_evidence(result.scenes[1].evidence_ids[0])
    assert store.get_source(ev.source_id).url == ev.source_url


def test_change_011_is_eligible_only_with_its_exact_approved_scene_evidence(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    by_id = {item.evidence_id: item for item in evidence}
    change = make_change_011()
    plan = make_plan([change])
    assert _validate_approved_change(change, sample_state(), plan, by_id) == []


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_change_011_pending_or_rejected_is_excluded(tmp_path, status):
    _, evidence = evidence_pack(tmp_path)
    change = make_change_011(status=status)
    result = adapt_screenplay(sample_state(), make_plan([change]), evidence, RAW)
    assert result.applied_change_ids == []
    assert result.adapted_screenplay_text == RAW
    assert result.original_screenplay_text == RAW


@pytest.mark.parametrize("evidence_ids", [["EVID_006"], ["EVID_004"], ["EVID_005", "EVID_006"]])
def test_change_011_requires_only_evid_005(tmp_path, evidence_ids):
    _, evidence = evidence_pack(tmp_path)
    change = make_change_011(evidence_ids=evidence_ids)
    result = adapt_screenplay(sample_state(), make_plan([change]), evidence, RAW)
    assert result.applied_change_ids == []
    assert result.blocked_change_ids == ["CHANGE_011"]
    assert result.adapted_screenplay_text == RAW


@pytest.mark.parametrize("scene_id,target_type,target_id", [
    ("SCENE_001", "scene", "SCENE_001"),
    ("SCENE_002", "character", "CHAR_001"),
    ("SCENE_002", "scene", "SCENE_001"),
])
def test_change_011_is_limited_to_scene_002(scene_id, target_type, target_id, tmp_path):
    _, evidence = evidence_pack(tmp_path)
    change = make_change_011(scene_id=scene_id, target_type=target_type, target_id=target_id)
    result = adapt_screenplay(sample_state(), make_plan([change]), evidence, RAW)
    assert result.applied_change_ids == []
    assert result.blocked_change_ids == ["CHANGE_011"]
    assert result.adapted_screenplay_text == RAW


def test_approved_change_011_preserves_all_original_scene_content_and_only_marks_scene_002(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    project = sample_state()
    change = make_change_011()
    result = adapt_screenplay(project, make_plan([change]), evidence, RAW)
    assert result.applied_change_ids == ["CHANGE_011"]
    assert result.evidence_ids == ["EVID_005"]
    assert result.original_screenplay_text == RAW
    assert result.adapted_screenplay_text.startswith(RAW)
    assert result.scenes[0].adapted_text == result.scenes[0].original_text
    assert result.scenes[1].adapted_text.startswith(result.scenes[1].original_text)
    assert "MOCK APPLIED CHANGE_011: Add restrained background merchandise detail" in result.scenes[1].adapted_text
    assert "I found this under the old table." in result.adapted_screenplay_text
    assert "What is it?" in result.adapted_screenplay_text
    assert "We need to find out who wrote this letter." in result.adapted_screenplay_text
    assert project.scenes[1].summary == "Ravi and Meena walk through a market and discuss a letter."


def test_existing_costume_compatibility_is_unchanged_by_production_design_exception(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    existing_costume = make_change("EXISTING_COSTUME", status="approved", category="costume",
                                   evidence_ids=["EVID_005"])
    result = adapt_screenplay(sample_state(), make_plan([existing_costume]), evidence, RAW)
    assert result.applied_change_ids == ["EXISTING_COSTUME"]
    assert result.blocked_change_ids == []


def test_deterministic_mock_output_and_timestamps(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    first = adapt_screenplay(sample_state(), make_plan(), evidence, RAW, adapter=MockScreenplayAdapter())
    second = adapt_screenplay(sample_state(), make_plan(), evidence, RAW, adapter=MockScreenplayAdapter())
    assert first == second
    assert first.adaptation_id == second.adaptation_id


def test_scene_alignment_failure_blocks_every_change(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    malformed = RAW.replace("EXT. MARKET - AFTERNOON", "EXT. UNKNOWN - NIGHT")
    result = adapt_screenplay(sample_state(), make_plan(), evidence, malformed)
    assert not result.applied_change_ids
    assert result.blocked_change_ids == ["CHANGE_APPROVED"]
    assert result.adapted_screenplay_text == malformed
    validation = validate_adapted_screenplay(sample_state(), result, make_plan(), original_text=malformed)
    assert not validation.valid


def test_validator_catches_scene_number_change_and_unapproved_applied_id(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    project = sample_state()
    plan = make_plan()
    result = adapt_screenplay(project, plan, evidence, RAW)
    bad_scene = result.scenes[0].model_copy(update={"scene_number": 7})
    bad = result.model_copy(update={"scenes": [bad_scene, result.scenes[1]], "applied_change_ids": ["CHANGE_PENDING"]})
    validation = validate_adapted_screenplay(project, bad, plan, original_text=RAW)
    assert not validation.valid
    assert any("Scene number changed" in error for error in validation.errors)
    assert any("Unapproved or unknown changes" in error for error in validation.errors)


def test_persisted_adapter_loads_plan_from_store_not_session_object(tmp_path):
    project = sample_state()
    _, evidence = evidence_pack(tmp_path / "culture")
    plan_store = AdaptationStore(tmp_path / "data")
    persisted = make_plan()
    plan_store.save_plan(persisted)
    # Deliberately do not pass a plan object: the service loads the persisted approval state.
    result = adapt_persisted_screenplay(project, evidence, RAW, plan_store=plan_store)
    assert result.applied_change_ids == ["CHANGE_APPROVED"]
    assert result.plan_version == persisted.version


def test_missing_plan_and_empty_original_fail_closed(tmp_path):
    project = sample_state()
    _, evidence = evidence_pack(tmp_path / "culture")
    with pytest.raises(FileNotFoundError):
        adapt_persisted_screenplay(project, evidence, RAW, plan_store=AdaptationStore(tmp_path / "no-plan"))
    with pytest.raises(ValueError, match="Original screenplay"):
        adapt_screenplay(project, make_plan(), evidence, "")


def test_validator_result_shape_and_warning_fields(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    project = sample_state()
    result = adapt_screenplay(project, make_plan([make_change("PENDING", status="pending")]), evidence, RAW)
    validation = validate_adapted_screenplay(project, result, make_plan([make_change("PENDING", status="pending")]), RAW)
    assert validation.valid
    assert validation.checked_scene_count == 2
    assert validation.applied_change_count == 0
    assert validation.warnings


def test_invalid_applied_change_id_is_detected_by_validator(tmp_path):
    _, evidence = evidence_pack(tmp_path)
    project = sample_state()
    plan = make_plan([make_change("PENDING", status="pending")])
    result = adapt_screenplay(project, plan, evidence, RAW)
    tampered = result.model_copy(update={"applied_change_ids": ["FAKE_CHANGE"]})
    validation = validate_adapted_screenplay(project, tampered, plan)
    assert not validation.valid and any("Unapproved or unknown changes" in e for e in validation.errors)

