from __future__ import annotations

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))
from phase9_fixtures import complete_fixture
from app.services.final_validator import validate_final_project


def validate(items, **overrides):
    state, plan, adapted, pack, batch, evidence, sources, source, _ = items
    args = dict(project_state=state, source_screenplay=source, adaptation_plan=plan,
                adapted_screenplay=adapted, visual_pack=pack, generation_batch=batch,
                cultural_evidence=evidence, cultural_sources=sources)
    args.update(overrides)
    return validate_final_project(**args)


def test_complete_project_is_structurally_valid_and_reports_mock_warning(tmp_path):
    result = validate(complete_fixture(tmp_path))
    assert result.valid
    assert result.continuity_report.status == "passed"
    assert any("Mock artifact" in warning or "Mock" in warning for warning in result.warnings)


def test_missing_adapted_screenplay_blocks_validation(tmp_path):
    result = validate(complete_fixture(tmp_path), adapted_screenplay=None)
    assert not result.valid and any("adapted screenplay is missing" in x for x in result.errors)


def test_missing_visual_keyframe_blocks_validation(tmp_path):
    items = complete_fixture(tmp_path)
    pack = items[3].model_copy(update={"scene_keyframes": items[3].scene_keyframes[:-1]})
    result = validate(items, visual_pack=pack)
    assert not result.valid and any("keyframes" in x.casefold() for x in result.errors)


def test_invalid_character_reference_blocks_validation(tmp_path):
    items = complete_fixture(tmp_path)
    pack = items[3].model_copy(update={"character_bibles": [items[3].character_bibles[0].model_copy(update={"character_id": "UNKNOWN"}), *items[3].character_bibles[1:]]})
    result = validate(items, visual_pack=pack)
    assert not result.valid


def test_invalid_costume_reference_blocks_validation(tmp_path):
    items = complete_fixture(tmp_path)
    frames = list(items[3].scene_keyframes)
    frames[1] = frames[1].model_copy(update={"costume_visual_refs": ["COSTUME_MISSING"]})
    result = validate(items, visual_pack=items[3].model_copy(update={"scene_keyframes": frames}))
    assert not result.valid


def test_invalid_generated_artifact_reference_blocks_validation(tmp_path):
    items = complete_fixture(tmp_path)
    art = items[4].artifacts[0].model_copy(update={"request_id": "REQUEST_MISSING"})
    batch = items[4].model_copy(update={"artifacts": [art]})
    result = validate(items, generation_batch=batch)
    assert not result.valid and any("missing request" in x for x in result.errors)


def test_missing_evidence_blocks_provenance(tmp_path):
    items = complete_fixture(tmp_path)
    result = validate(items, cultural_evidence=[])
    assert not result.valid


def test_unresolved_evidence_warning_is_preserved(tmp_path):
    items = complete_fixture(tmp_path)
    from app.models.cultural_evidence import CulturalEvidence
    insufficient = [CulturalEvidence.model_validate({**e.model_dump(mode="json"), "status": "insufficient_evidence"}) if e.evidence_id == "EVID_001" else e for e in items[5]]
    result = validate(items, cultural_evidence=insufficient)
    assert result.valid
    assert any("insufficient_evidence" in item for item in result.unresolved_items)


def test_original_screenplay_unchanged_and_mutation_detected(tmp_path):
    items = complete_fixture(tmp_path)
    assert validate(items).valid
    changed = items[7].model_copy(update={"raw_text": items[7].raw_text + "changed"})
    result = validate(items, source_screenplay=changed)
    assert not result.valid and any("preserve" in x for x in result.errors)


def test_scene_count_and_order_are_checked(tmp_path):
    items = complete_fixture(tmp_path)
    reversed_scenes = list(reversed(items[2].scenes))
    result = validate(items, adapted_screenplay=items[2].model_copy(update={"scenes": reversed_scenes}))
    assert not result.valid and any("order" in x for x in result.errors)


def test_only_approved_requests_can_have_generated_artifacts(tmp_path):
    items = complete_fixture(tmp_path)
    from app.models.visual_generation import VisualGenerationRequest
    request = VisualGenerationRequest.model_validate({**items[4].requests[0].model_dump(mode="json"), "status": "pending"})
    batch = items[4].model_copy(update={"requests": [request, *items[4].requests[1:]]})
    result = validate(items, generation_batch=batch)
    assert not result.valid and any("not approved" in x for x in result.errors)


def test_prompt_hash_integrity_is_checked(tmp_path):
    items = complete_fixture(tmp_path)
    from app.models.visual_generation import VisualGenerationRequest
    request = VisualGenerationRequest.model_validate({**items[4].requests[0].model_dump(mode="json"), "prompt_hash": "bad-hash"})
    batch = items[4].model_copy(update={"requests": [request, *items[4].requests[1:]]})
    result = validate(items, generation_batch=batch)
    assert not result.valid and any("hash" in x.casefold() for x in result.errors)
