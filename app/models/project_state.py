"""Persistent canonical screenplay project state (Phase 3)."""
from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator, model_validator

from app.models.extraction import (
    Character,
    ContinuityState,
    Location,
    ProductionElement,
    Scene,
    ExtractionModel,
)


class ProjectStateStatus(str, Enum):
    DRAFT = "draft"
    EXTRACTED = "extracted"
    APPROVED = "approved"
    ADAPTED = "adapted"
    GENERATED = "generated"
    EXPORTED = "exported"


class ProjectState(ExtractionModel):
    project_id: str = Field(min_length=1)
    screenplay_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_filename: str | None = None
    culture: str | None = None
    dialect: str | None = None
    region: str | None = None
    setting: str | None = None
    script: str | None = None
    scenes: list[Scene] = Field(default_factory=list)
    characters: list[Character] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    production_elements: list[ProductionElement] = Field(default_factory=list)
    continuity_states: list[ContinuityState] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
    updated_at: str = Field(min_length=1)
    state_status: ProjectStateStatus = ProjectStateStatus.DRAFT
    normalization_warnings: list[str] = Field(default_factory=list)

    @field_validator("updated_at")
    @classmethod
    def valid_iso_timestamp(cls, value: str) -> str:
        from datetime import datetime
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("updated_at must be an ISO 8601 timestamp") from exc
        return value

    @model_validator(mode="after")
    def validate_state_references(self):
        def unique(items, attr, label):
            ids = [getattr(item, attr) for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} IDs must be unique")
        unique(self.scenes, "scene_id", "scene")
        unique(self.characters, "character_id", "character")
        unique(self.locations, "location_id", "location")
        unique(self.production_elements, "element_id", "production element")
        scene_ids = {item.scene_id for item in self.scenes}
        character_ids = {item.character_id for item in self.characters}
        element_ids = {item.element_id for item in self.production_elements}
        for scene in self.scenes:
            if missing := set(scene.character_ids) - character_ids:
                raise ValueError(f"unknown character IDs in {scene.scene_id}: {sorted(missing)}")
            if missing := set(scene.production_element_ids) - element_ids:
                raise ValueError(f"unknown production element IDs in {scene.scene_id}: {sorted(missing)}")
        for character in self.characters:
            refs = set(character.scene_ids)
            refs.update(x for x in (character.entrance_scene_id, character.exit_scene_id) if x)
            if missing := refs - scene_ids:
                raise ValueError(f"unknown scene IDs for {character.character_id}: {sorted(missing)}")
        for location in self.locations:
            if missing := set(location.scenes) - scene_ids:
                raise ValueError(f"unknown scene IDs for {location.location_id}: {sorted(missing)}")
        for element in self.production_elements:
            if missing := set(element.scenes) - scene_ids:
                raise ValueError(f"unknown scene IDs for {element.element_id}: {sorted(missing)}")
        for continuity in self.continuity_states:
            if continuity.scene_id not in scene_ids:
                raise ValueError(f"unknown continuity scene ID: {continuity.scene_id}")
        return self
