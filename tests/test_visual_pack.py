from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent))
from test_screenplay_adapter import RAW, evidence_pack, make_change, make_plan, sample_state

from app.models.adaptation import AdaptationCategory
from app.models.cultural_evidence import CulturalEvidenceStatus
from app.services.screenplay_adapter import adapt_screenplay
from app.services.visual_pack_generator import MockVisualPackGenerator


def generate(tmp_path, *, change=None, evidence_override=None):
    state = sample_state()
    store, evidence = evidence_pack(tmp_path)
    plan = make_plan([change] if change else [])
    if evidence_override is not None:
        evidence = evidence_override
    adapted = adapt_screenplay(state, plan, evidence, RAW)
    pack = MockVisualPackGenerator().generate(state, adapted, plan, evidence)
    return state, plan, adapted, evidence, pack


def test_character_bible_for_every_canonical_character_without_duplicate_ids(tmp_path):
    state, _, _, _, pack = generate(tmp_path)
    assert [b.character_id for b in pack.character_bibles] == [c.character_id for c in state.characters]
    assert len({b.character_id for b in pack.character_bibles}) == len(pack.character_bibles)
    assert all(b.face_identity is None and b.baseline_wardrobe is None for b in pack.character_bibles)
    assert all(b.warnings for b in pack.character_bibles)


def test_costume_bible_generated_only_for_approved_character_targeted_supported_variant(tmp_path):
    change = make_change("VISUAL_COSTUME", status="approved", category=AdaptationCategory.COSTUME,
                         target_type="character", target_id="CHAR_001", evidence_ids=["EVID_005"])
    _, _, _, _, pack = generate(tmp_path, change=change)
    assert len(pack.costume_bibles) == 1
    bible = pack.costume_bibles[0]
    assert bible.character_id == "CHAR_001" and bible.scene_ids == ["SCENE_002"]
    assert bible.evidence_ids == ["EVID_005"]
    assert bible.garments == [] and bible.fabric is None and bible.colors == []


def test_exactly_one_keyframe_per_scene_in_canonical_order(tmp_path):
    state, _, _, _, pack = generate(tmp_path)
    assert len(pack.scene_keyframes) == len(state.scenes)
    assert [frame.scene_id for frame in pack.scene_keyframes] == [scene.scene_id for scene in state.scenes]


def test_evidence_traceability_attaches_citation_to_keyframe_and_costume(tmp_path):
    change = make_change("VISUAL_COSTUME", status="approved", category=AdaptationCategory.COSTUME,
                         target_type="character", target_id="CHAR_001", evidence_ids=["EVID_005"])
    _, _, _, evidence, pack = generate(tmp_path, change=change)
    assert pack.scene_keyframes[1].evidence_ids == ["EVID_005"]
    assert pack.scene_keyframes[1].applied_change_ids == ["VISUAL_COSTUME"]
    assert pack.costume_bibles[0].evidence_ids == ["EVID_005"]
    assert "VISUAL_COSTUME" in pack.scene_keyframes[1].generation_prompt
    assert "EVID_005" in {item.evidence_id for item in evidence}


def test_invalid_evidence_blocks_visual_claim_and_emits_warning(tmp_path):
    change = make_change("MISSING_EVID", status="approved", category=AdaptationCategory.COSTUME,
                         target_type="character", target_id="CHAR_001", evidence_ids=["EVID_DOES_NOT_EXIST"])
    _, _, _, _, pack = generate(tmp_path, change=change)
    assert not pack.scene_keyframes[1].cultural_details
    assert any("EVID_DOES_NOT_EXIST is missing" in warning for warning in pack.continuity_warnings)


def test_rajasthan_general_evidence_is_never_narrowed_to_marwari(tmp_path):
    change = make_change("GENERAL_RITUAL", status="approved", category=AdaptationCategory.RITUAL,
                         target_type="scene", target_id="SCENE_002", evidence_ids=["EVID_011"])
    _, _, _, _, pack = generate(tmp_path, change=change)
    assert not pack.scene_keyframes[1].cultural_details
    assert any("Rajasthan-general" in warning and "cannot be narrowed" in warning for warning in pack.continuity_warnings)


def test_insufficient_evidence_remains_unknown_and_warned(tmp_path):
    _, _, _, evidence, _ = generate(tmp_path)
    insufficient = evidence[4].model_copy(update={"evidence_id": "EVID_UNSURE", "status": CulturalEvidenceStatus.INSUFFICIENT_EVIDENCE})
    change = make_change("UNSURE_COSTUME", status="approved", category=AdaptationCategory.COSTUME,
                         target_type="character", target_id="CHAR_001", evidence_ids=["EVID_UNSURE"])
    _, _, _, _, pack = generate(tmp_path, change=change, evidence_override=[*evidence, insufficient])
    assert not pack.costume_bibles
    assert any("EVID_UNSURE is insufficient" in warning for warning in pack.continuity_warnings)


def test_output_is_deterministic_and_does_not_mutate_inputs(tmp_path):
    state = sample_state(); state_before = state.model_dump(mode="json")
    store, evidence = evidence_pack(tmp_path); plan = make_plan(); plan_before = plan.model_dump(mode="json")
    adapted = adapt_screenplay(state, plan, evidence, RAW); adapted_before = adapted.model_dump(mode="json")
    generator = MockVisualPackGenerator()
    first = generator.generate(state, adapted, plan, evidence)
    second = generator.generate(state, adapted, plan, evidence)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert state.model_dump(mode="json") == state_before
    assert plan.model_dump(mode="json") == plan_before
    assert adapted.model_dump(mode="json") == adapted_before
    assert store.evidence


def test_provider_ready_prompt_is_structured_and_states_unknowns(tmp_path):
    _, _, _, _, pack = generate(tmp_path)
    prompt = pack.scene_keyframes[0].generation_prompt
    for label in ("Subject:", "Characters:", "Appearance:", "Costume:", "Location:", "Architecture:",
                  "Environment:", "Props:", "Lighting:", "Camera framing:", "Composition:", "Mood:", "Cultural visual details"):
        assert label in prompt
    assert "unspecified" in prompt
    assert "watermarks" in pack.scene_keyframes[0].negative_prompt
