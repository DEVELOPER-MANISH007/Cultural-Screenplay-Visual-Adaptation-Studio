import json

import pytest
from pydantic import ValidationError

from app.models.extraction import Character, Location, ProductionElement, ScreenplayExtraction
from app.models.project_state import ProjectState, ProjectStateStatus
from app.models.screenplay import ScreenplayDocument, SourceType
from app.services.canonical_registry import CharacterRegistry, LocationRegistry, ProductionElementRegistry
from app.services.extractor import extract_screenplay
from app.services.llm_provider import MockLLMProvider
from app.services.normalizer import build_project_state, normalize_name
from app.services.project_store import ProjectStateLoadError, ProjectStore


SAMPLE = """INT. COURTYARD - MORNING

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


def extraction():
    document = ScreenplayDocument(source_type=SourceType.PASTED_TEXT, filename="sample.txt", raw_text=SAMPLE)
    return extract_screenplay(document, MockLLMProvider())


def state(project_id="project-test"):
    return build_project_state(extraction(), title="Sample", project_id=project_id, source_filename="sample.txt")


def test_project_state_creation_and_validation():
    value = state()
    assert value.state_status == ProjectStateStatus.EXTRACTED
    assert value.version == 1
    assert value.project_id == "project-test"
    assert value.scenes and value.characters
    with pytest.raises(ValidationError):
        ProjectState(project_id="p", screenplay_id="s", title="t", scenes=[{
            "scene_id": "SCENE_001", "scene_number": 1, "heading": "INT. ROOM", "summary": "x",
            "character_ids": ["missing"],
        }], version=1, updated_at="2026-09-29T00:00:00Z")


def test_stable_ids_for_all_entity_groups():
    first = state()
    second = state()
    assert [x.scene_id for x in first.scenes] == ["SCENE_001", "SCENE_002"]
    assert [x.character_id for x in first.characters] == ["CHAR_001", "CHAR_002"]
    assert [x.location_id for x in first.locations] == ["LOC_001", "LOC_002"]
    assert [x.element_id for x in first.production_elements] == ["PROP_001", "PROP_002", "PROP_003"]
    assert [x.scene_id for x in first.scenes] == [x.scene_id for x in second.scenes]
    assert [x.character_id for x in first.characters] == [x.character_id for x in second.characters]
    assert [x.location_id for x in first.locations] == [x.location_id for x in second.locations]
    assert [x.element_id for x in first.production_elements] == [x.element_id for x in second.production_elements]


def test_name_normalization_and_uncertain_candidates_stay_separate():
    assert normalize_name("  RAVI   Kumar ") == "ravi kumar"
    registry = CharacterRegistry()
    ravi = Character(character_id="CHAR_001", canonical_name="Ravi", scene_ids=["SCENE_001"])
    ravi_kumar = Character(character_id="CHAR_002", canonical_name="Ravi Kumar", scene_ids=["SCENE_002"])
    registry.add_entity(ravi)
    result = registry.add_entity(ravi_kumar)
    assert len(registry.list_entities()) == 2
    assert result.character_id == "CHAR_002"
    assert registry.warnings and "kept separate" in registry.warnings[0]


def test_exact_character_duplicate_preserves_aliases_references_and_metadata():
    registry = CharacterRegistry()
    registry.add_entity(Character(character_id="CHAR_001", canonical_name="Ravi", aliases=["RAVI"], age=None,
                                  relationships={"Meena": "sister"}, scene_ids=["SCENE_001"]))
    merged = registry.add_entity(Character(character_id="CHAR_002", canonical_name=" ravi ", aliases=["Rav"],
                                           role="speaker", scene_ids=["SCENE_002"]))
    assert merged.character_id == "CHAR_001"
    assert set(merged.aliases) == {"RAVI", "ravi", "Rav"}
    assert merged.scene_ids == ["SCENE_001", "SCENE_002"]
    assert merged.role == "speaker"
    assert merged.relationships == {"Meena": "sister"}
    assert len(registry.list_entities()) == 1


def test_confirmed_merge_preserves_data_and_uncertain_merge_requires_confirmation():
    registry = CharacterRegistry()
    registry.add_entity(Character(character_id="CHAR_001", canonical_name="Ravi", relationships={"Meena": "sister"}, scene_ids=["SCENE_001"]))
    registry.add_entity(Character(character_id="CHAR_002", canonical_name="Ravi Kumar", aliases=["Mr. Ravi"], age="adult", scene_ids=["SCENE_002"]))
    with pytest.raises(ValueError, match="explicit confirmation"):
        registry.merge_entities("CHAR_001", "CHAR_002")
    merged = registry.merge_entities("CHAR_001", "CHAR_002", confirmed=True)
    assert merged.canonical_name == "Ravi"
    assert set(merged.aliases) >= {"Ravi Kumar", "Mr. Ravi"}
    assert merged.scene_ids == ["SCENE_001", "SCENE_002"]
    assert merged.age == "adult"
    assert merged.relationships == {"Meena": "sister"}


def test_location_and_production_registries_are_typed_and_conservative():
    locations = LocationRegistry()
    first = locations.add_entity(Location(location_id="LOC_001", canonical_name="Courtyard", scenes=["SCENE_001"]))
    duplicate = locations.add_entity(Location(location_id="LOC_002", canonical_name=" courtyard ", scenes=["SCENE_002"]))
    assert duplicate.location_id == first.location_id
    assert duplicate.scenes == ["SCENE_001", "SCENE_002"]
    props = ProductionElementRegistry()
    envelope = props.add_entity(ProductionElement(element_id="PROP_001", category="prop", name="old envelope", scenes=["SCENE_001"]))
    possible = props.add_entity(ProductionElement(element_id="PROP_002", category="prop", name="envelope", scenes=["SCENE_002"]))
    letter = props.add_entity(ProductionElement(element_id="PROP_003", category="prop", name="letter", scenes=["SCENE_002"]))
    same_name_other_category = props.add_entity(ProductionElement(element_id="ELEM_001", category="set", name="letter", scenes=["SCENE_001"]))
    assert len(props.list_entities()) == 4
    assert possible.element_id != envelope.element_id
    assert letter.name == "letter"
    assert same_name_other_category.element_id == "ELEM_001"
    assert props.warnings


def test_project_state_json_round_trip_and_scene_references():
    original = state()
    restored = ProjectState.model_validate_json(original.model_dump_json())
    assert restored.characters[0].scene_ids == ["SCENE_001", "SCENE_002"]
    assert restored.locations[0].scenes == ["SCENE_001"]
    assert restored.production_elements[0].scenes == ["SCENE_001"]
    assert restored.continuity_states == original.continuity_states
    assert restored.updated_at == original.updated_at


def test_project_store_create_load_and_exists(tmp_path):
    store = ProjectStore(tmp_path / "data")
    original = state("safe-project")
    with_alias = original.characters[0].model_copy(update={"aliases": ["Ravi Kumar", "Mr. Ravi"]})
    original = original.model_copy(update={"characters": [with_alias, *original.characters[1:]]})
    assert not store.project_exists(original.project_id)
    saved = store.create_project(original)
    assert store.project_exists(original.project_id)
    loaded = store.load_project(original.project_id)
    assert saved.version == loaded.version == 1
    assert [x.character_id for x in loaded.characters] == [x.character_id for x in original.characters]
    assert loaded.characters[0].aliases == original.characters[0].aliases
    assert loaded.characters[0].scene_ids == original.characters[0].scene_ids
    assert loaded.continuity_states == original.continuity_states
    path = tmp_path / "data" / "projects" / "safe-project" / "project.json"
    assert json.loads(path.read_text(encoding="utf-8"))["state_status"] == "extracted"


def test_project_store_version_changes_only_for_meaningful_update(tmp_path):
    store = ProjectStore(tmp_path)
    original = store.create_project(state("v-project"))
    unchanged = store.save_project(original)
    assert unchanged.version == original.version
    changed = original.model_copy(update={"title": "Renamed"})
    saved = store.save_project(changed)
    assert saved.version == 2
    assert saved.updated_at >= original.updated_at
    assert [x.scene_id for x in saved.scenes] == [x.scene_id for x in original.scenes]


def test_project_store_missing_and_invalid_state_handling(tmp_path):
    store = ProjectStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.load_project("missing")
    path = tmp_path / "projects" / "broken" / "project.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"project_id": "broken", "version": 0}', encoding="utf-8")
    with pytest.raises(ProjectStateLoadError, match="Invalid project state"):
        store.load_project("broken")
    with pytest.raises(ValueError, match="project_id"):
        store.project_exists("../outside")
