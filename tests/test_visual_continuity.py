from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from test_screenplay_adapter import RAW, evidence_pack, make_change, make_plan, sample_state

from app.models.adaptation import AdaptationCategory
from app.services.screenplay_adapter import adapt_screenplay
from app.services.visual_continuity_validator import validate_visual_pack
from app.services.visual_pack_generator import MockVisualPackGenerator


def setup_pack(tmp_path, change=None):
    state = sample_state()
    _, evidence = evidence_pack(tmp_path)
    plan = make_plan([change] if change else [])
    adapted = adapt_screenplay(state, plan, evidence, RAW)
    pack = MockVisualPackGenerator().generate(state, adapted, plan, evidence)
    return state, adapted, plan, evidence, pack


def test_generator_pack_passes_canonical_scene_character_and_prop_validation(tmp_path):
    state, adapted, plan, evidence, pack = setup_pack(tmp_path)
    result = validate_visual_pack(state, pack, adapted, plan, evidence)
    assert result.valid
    assert result.character_count == len(state.characters)
    assert result.scene_keyframe_count == len(state.scenes)
    assert result.errors == []


def test_invalid_character_reference_is_detected(tmp_path):
    state, adapted, plan, evidence, pack = setup_pack(tmp_path)
    frame = pack.scene_keyframes[0].model_copy(update={"character_visual_refs": ["CHAR_MISSING"], "characters_present": ["CHAR_MISSING"]})
    changed = pack.model_copy(update={"scene_keyframes": [frame, *pack.scene_keyframes[1:]]})
    result = validate_visual_pack(state, changed, adapted, plan, evidence)
    assert any("unknown character CHAR_MISSING" in item for item in result.missing_references)


def test_invalid_costume_reference_is_detected(tmp_path):
    state, adapted, plan, evidence, pack = setup_pack(tmp_path)
    frame = pack.scene_keyframes[0].model_copy(update={"costume_visual_refs": ["COSTUME_UNKNOWN"]})
    changed = pack.model_copy(update={"scene_keyframes": [frame, *pack.scene_keyframes[1:]]})
    result = validate_visual_pack(state, changed, adapted, plan, evidence)
    assert any("unknown costume COSTUME_UNKNOWN" in item for item in result.missing_references)


def test_invalid_scene_reference_and_missing_keyframe_are_detected(tmp_path):
    state, adapted, plan, evidence, pack = setup_pack(tmp_path)
    frame = pack.scene_keyframes[0].model_copy(update={"scene_id": "SCENE_UNKNOWN"})
    changed = pack.model_copy(update={"scene_keyframes": [frame, *pack.scene_keyframes[1:]]})
    result = validate_visual_pack(state, changed, adapted, plan, evidence)
    assert any("unknown scene SCENE_UNKNOWN" in item for item in result.missing_references)
    assert any("preserve scene order" in item for item in result.errors)
    omitted = pack.model_copy(update={"scene_keyframes": pack.scene_keyframes[:1]})
    assert any("preserve scene order" in item for item in validate_visual_pack(state, omitted, adapted, plan, evidence).errors)


def test_duplicate_character_bible_and_missing_bible_are_detected(tmp_path):
    state, adapted, plan, evidence, pack = setup_pack(tmp_path)
    duplicate = pack.model_copy(update={"character_bibles": [*pack.character_bibles, pack.character_bibles[0]]})
    result = validate_visual_pack(state, duplicate, adapted, plan, evidence)
    assert any("Duplicate character bibles" in item for item in result.errors)
    missing = pack.model_copy(update={"character_bibles": pack.character_bibles[:1]})
    assert any("Missing character bible" in item for item in validate_visual_pack(state, missing, adapted, plan, evidence).errors)


def test_character_age_cannot_conflict_with_canonical_project_state(tmp_path):
    state, adapted, plan, evidence, pack = setup_pack(tmp_path)
    state.characters[0].age = "adult"
    changed_bible = pack.character_bibles[0].model_copy(update={"age_description": "teenager"})
    changed = pack.model_copy(update={"character_bibles": [changed_bible, *pack.character_bibles[1:]]})
    result = validate_visual_pack(state, changed, adapted, plan, evidence)
    assert any("Character age conflicts" in item for item in result.errors)


def test_costume_canonical_character_and_scene_consistency(tmp_path):
    change = make_change("COSTUME_OK", status="approved", category=AdaptationCategory.COSTUME,
                         target_type="character", target_id="CHAR_001", evidence_ids=["EVID_005"])
    state, adapted, plan, evidence, pack = setup_pack(tmp_path, change)
    costume = pack.costume_bibles[0].model_copy(update={"character_id": "CHAR_MISSING", "scene_ids": ["SCENE_MISSING"]})
    changed = pack.model_copy(update={"costume_bibles": [costume]})
    result = validate_visual_pack(state, changed, adapted, plan, evidence)
    assert any("unknown character CHAR_MISSING" in item for item in result.missing_references)
    assert any("unknown scene SCENE_MISSING" in item for item in result.missing_references)


def test_same_costume_variant_cannot_have_contradictory_attributes(tmp_path):
    change = make_change("COSTUME_OK", status="approved", category=AdaptationCategory.COSTUME,
                         target_type="character", target_id="CHAR_001", evidence_ids=["EVID_005"])
    state, adapted, plan, evidence, pack = setup_pack(tmp_path, change)
    second = pack.costume_bibles[0].model_copy(update={"costume_id": "COSTUME_SECOND", "colors": ["unsupported color"]})
    changed = pack.model_copy(update={"costume_bibles": [pack.costume_bibles[0], second]})
    result = validate_visual_pack(state, changed, adapted, plan, evidence)
    assert any("contradictory attributes" in item for item in result.errors)


def test_scene_only_costume_reference_must_belong_to_scene_character(tmp_path):
    change = make_change("COSTUME_OK", status="approved", category=AdaptationCategory.COSTUME,
                         target_type="character", target_id="CHAR_001", evidence_ids=["EVID_005"])
    state, adapted, plan, evidence, pack = setup_pack(tmp_path, change)
    frame = pack.scene_keyframes[0].model_copy(update={"costume_visual_refs": [pack.costume_bibles[0].costume_id]})
    changed = pack.model_copy(update={"scene_keyframes": [frame, *pack.scene_keyframes[1:]]})
    result = validate_visual_pack(state, changed, adapted, plan, evidence)
    assert any("does not belong to a character/scene" in item for item in result.errors)


def test_generation_claim_without_evidence_is_flagged(tmp_path):
    state, adapted, plan, evidence, pack = setup_pack(tmp_path)
    frame = pack.scene_keyframes[0].model_copy(update={"cultural_details": ["unsubstantiated custom"], "evidence_ids": [], "applied_change_ids": []})
    changed = pack.model_copy(update={"scene_keyframes": [frame, *pack.scene_keyframes[1:]]})
    result = validate_visual_pack(state, changed, adapted, plan, evidence)
    assert any("without evidence" in item for item in result.unsupported_cultural_details)
    assert not result.valid


def test_prompt_change_reference_requires_approved_evidence_trace(tmp_path):
    change = make_change("COSTUME_OK", status="approved", category=AdaptationCategory.COSTUME,
                         target_type="character", target_id="CHAR_001", evidence_ids=["EVID_005"])
    state, adapted, plan, evidence, pack = setup_pack(tmp_path, change)
    frame = pack.scene_keyframes[1].model_copy(update={"generation_prompt": "No approved visual detail included."})
    changed = pack.model_copy(update={"scene_keyframes": [pack.scene_keyframes[0], frame]})
    result = validate_visual_pack(state, changed, adapted, plan, evidence)
    assert any("omits approved change reference" in item for item in result.errors)
    assert any("differs from its supported structured fields" in item for item in result.unsupported_cultural_details)


def test_costume_visual_attributes_without_evidence_are_flagged(tmp_path):
    change = make_change("COSTUME_OK", status="approved", category=AdaptationCategory.COSTUME,
                         target_type="character", target_id="CHAR_001", evidence_ids=["EVID_005"])
    state, adapted, plan, evidence, pack = setup_pack(tmp_path, change)
    costume = pack.costume_bibles[0].model_copy(update={"evidence_ids": [], "colors": ["claimed color"]})
    changed = pack.model_copy(update={"costume_bibles": [costume]})
    result = validate_visual_pack(state, changed, adapted, plan, evidence)
    assert any("without evidence IDs" in item for item in result.unsupported_cultural_details)
