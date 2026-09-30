"""Phase 0 foundation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.models import Character, Costume, ProductionElement, Project, ProjectStatus, Scene

ROOT = Path(__file__).resolve().parent.parent


def test_project_can_be_created() -> None:
    project = Project(title="Chai Stall", culture="Awadhi", region="Lucknow")
    assert project.title == "Chai Stall"
    assert project.status == ProjectStatus.DRAFT
    assert project.source_filename is None
    assert project.project_id


def test_project_ids_are_unique() -> None:
    assert Project(title="A").project_id != Project(title="A").project_id


def test_scene_can_be_created() -> None:
    scene = Scene(scene_number=1, heading="INT. KITCHEN - DAY")
    assert scene.summary == ""
    assert scene.scene_id


def test_character_can_be_created() -> None:
    character = Character(name="Asha", aliases=["Ashu"], role="protagonist")
    assert character.aliases == ["Ashu"]
    assert Character(name="Ravi").aliases == []


def test_costume_and_production_element_can_be_created() -> None:
    assert Costume(name="Chikankari kurta", scenes=[1, 2]).scenes == [1, 2]
    assert ProductionElement(category="prop", description="Brass kettle").scenes == []


def test_invalid_required_data_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Project()  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Project(title="   ")
    with pytest.raises(ValidationError):
        Project(title="X", status="not-a-status")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Scene(scene_number=0, heading="INT. ROOM")
    with pytest.raises(ValidationError):
        Scene(scene_number=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Character()  # type: ignore[call-arg]


def test_settings_load_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "Test App")
    monkeypatch.setenv("DEBUG", "true")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.app_name == "Test App"
        assert settings.debug is True
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "relative_path",
    [
        "app/main.py",
        "app/config.py",
        "run.py",
        "requirements.txt",
        "README.md",
        ".env.example",
        ".gitignore",
        "data/projects",
        "data/culture",
    ],
)
def test_project_files_exist(relative_path: str) -> None:
    assert (ROOT / relative_path).exists()
