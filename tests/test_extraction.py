import pytest
from pydantic import ValidationError

from app.models.extraction import Character, ContinuityState, Location, ProductionElement, Scene, ScreenplayExtraction
from app.models.screenplay import ScreenplayDocument, SourceType
from app.services.extractor import extract_screenplay
from app.services.llm_provider import MockLLMProvider


def doc(text):
    return ScreenplayDocument(source_type=SourceType.PASTED_TEXT, raw_text=text)


def test_model_shapes_validate():
    Scene(scene_id="s", scene_number=1, heading="INT. ROOM - DAY", summary="Ravi enters")
    Character(character_id="c", canonical_name="Ravi")
    Location(location_id="l", canonical_name="Room")
    ProductionElement(element_id="p", category="prop", name="cup")
    ContinuityState(scene_id="s")


def test_successful_offline_extraction():
    result = extract_screenplay(doc("INT. ROOM - DAY\nRavi enters."), MockLLMProvider())
    assert len(result.scenes) == 1
    assert result.scenes[0].heading == "INT. ROOM - DAY"
    assert result.scenes[0].scene_id == "SCENE_001"
    assert result.extraction_warnings


def test_empty_extraction_rejected():
    with pytest.raises(ValidationError):
        ScreenplayExtraction(screenplay_id="x", scenes=[])


def test_duplicate_ids_rejected():
    scene = dict(scene_id="s", scene_number=1, heading="INT. A", summary="A")
    with pytest.raises(ValidationError):
        ScreenplayExtraction(screenplay_id="x", scenes=[scene, {**scene, "scene_number": 2}])


def test_broken_references_rejected():
    with pytest.raises(ValidationError):
        ScreenplayExtraction(screenplay_id="x", scenes=[dict(scene_id="s", scene_number=1, heading="INT. A", summary="A", character_ids=["missing"])])


def test_order_rejected():
    base = dict(heading="INT. A", summary="A")
    with pytest.raises(ValidationError):
        ScreenplayExtraction(screenplay_id="x", scenes=[dict(base, scene_id="s2", scene_number=2), dict(base, scene_id="s1", scene_number=1)])


def test_broken_production_reference_rejected():
    with pytest.raises(ValidationError):
        ScreenplayExtraction(screenplay_id="x", scenes=[dict(scene_id="s", scene_number=1, heading="INT. A", summary="A", production_element_ids=["missing"])])


def test_continuity_scene_reference_rejected():
    with pytest.raises(ValidationError):
        ScreenplayExtraction(screenplay_id="x", scenes=[dict(scene_id="s", scene_number=1, heading="INT. A", summary="A")], continuity_states=[dict(scene_id="unknown")])


def test_aliases_preserved_without_inferred_merge():
    extraction = ScreenplayExtraction(screenplay_id="x", scenes=[dict(scene_id="s", scene_number=1, heading="INT. A", summary="A")], characters=[dict(character_id="c1", canonical_name="Ravi Kumar", aliases=["Ravi", "Mr. Ravi"])])
    assert extraction.characters[0].aliases == ["Ravi", "Mr. Ravi"]


def test_mock_provider_is_repeatable_and_empty_has_warning():
    provider = MockLLMProvider()
    assert provider.generate_structured(prompt="", schema=ScreenplayExtraction, screenplay=doc(""))["extraction_warnings"]
    assert provider.generate_structured(prompt="", schema=ScreenplayExtraction, screenplay=doc("INT. ROOM - DAY")) == provider.generate_structured(prompt="", schema=ScreenplayExtraction, screenplay=doc("INT. ROOM - DAY"))


SAMPLE_SCREENPLAY = """INT. COURTYARD - MORNING

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


def test_mock_extracts_explicit_entities_and_scene_details():
    result = extract_screenplay(doc(SAMPLE_SCREENPLAY), MockLLMProvider())
    assert len(result.scenes) == 2
    assert [scene.int_ext for scene in result.scenes] == ["INT", "EXT"]
    assert [scene.location for scene in result.scenes] == ["Courtyard", "Market"]
    assert [scene.time_of_day for scene in result.scenes] == ["Morning", "Afternoon"]
    assert [(c.character_id, c.canonical_name) for c in result.characters] == [("CHAR_001", "Ravi"), ("CHAR_002", "Meena")]
    assert [(loc.location_id, loc.canonical_name) for loc in result.locations] == [("LOC_001", "Courtyard"), ("LOC_002", "Market")]
    # The dialogue explicitly mentions a letter in scene 2, so it is retained as a prop too.
    assert {element.name for element in result.production_elements} == {"old envelope", "old table", "letter"}
    assert all(element.category == "prop" for element in result.production_elements)
    assert result.extraction_confidence is not None and 0.7 <= result.extraction_confidence < 1


def test_mock_references_and_continuity_are_grounded():
    result = extract_screenplay(doc(SAMPLE_SCREENPLAY), MockLLMProvider())
    scene_ids = {scene.scene_id for scene in result.scenes}
    assert result.characters[0].scene_ids == ["SCENE_001", "SCENE_002"]
    assert result.characters[0].entrance_scene_id == "SCENE_001"
    assert result.locations[0].scenes == ["SCENE_001"]
    assert result.locations[1].scenes == ["SCENE_002"]
    assert all(set(item.scenes) <= scene_ids for item in result.production_elements)
    assert result.scenes[0].character_ids == ["CHAR_001", "CHAR_002"]
    assert result.scenes[0].production_element_ids == ["PROP_001", "PROP_002"]
    assert result.scenes[1].production_element_ids == ["PROP_003"]
    states = {state.scene_id: state for state in result.continuity_states}
    assert states["SCENE_001"].carries == ["Ravi carries old envelope"]
    assert states["SCENE_001"].prop_transfers == ["Ravi transfers old envelope to Meena"]


def test_mock_does_not_invent_unsupported_facts():
    result = extract_screenplay(doc(SAMPLE_SCREENPLAY), MockLLMProvider())
    for character in result.characters:
        assert character.age is None
        assert character.role is None
        assert character.relationships == {}
        assert character.personality == []
        assert character.dialect is None
        assert character.emotional_state is None
    for scene in result.scenes:
        assert scene.date is None and scene.weather is None and scene.mood is None
