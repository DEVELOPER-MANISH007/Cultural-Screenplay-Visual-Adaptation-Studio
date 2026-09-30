"""Validated Phase 2 screenplay structure models."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractionModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class Scene(ExtractionModel):
    scene_id: str = Field(min_length=1)
    scene_number: int = Field(ge=1)
    heading: str = Field(min_length=1)
    int_ext: str | None = None
    location: str | None = None
    sub_location: str | None = None
    time_of_day: str | None = None
    date: str | None = None
    weather: str | None = None
    mood: str | None = None
    summary: str
    dramatic_purpose: str | None = None
    character_ids: list[str] = Field(default_factory=list)
    production_element_ids: list[str] = Field(default_factory=list)
    continuity_notes: list[str] = Field(default_factory=list)


class Character(ExtractionModel):
    character_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    age: str | None = None
    role: str | None = None
    relationships: dict[str, str] = Field(default_factory=dict)
    personality: list[str] = Field(default_factory=list)
    dialect: str | None = None
    emotional_state: str | None = None
    entrance_scene_id: str | None = None
    exit_scene_id: str | None = None
    scene_ids: list[str] = Field(default_factory=list)


class Location(ExtractionModel):
    location_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    type: str | None = None
    description: str | None = None
    scenes: list[str] = Field(default_factory=list)


class ProductionElement(ExtractionModel):
    element_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    scenes: list[str] = Field(default_factory=list)


class ContinuityState(ExtractionModel):
    scene_id: str = Field(min_length=1)
    wears: list[str] = Field(default_factory=list)
    carries: list[str] = Field(default_factory=list)
    knows: list[str] = Field(default_factory=list)
    loses: list[str] = Field(default_factory=list)
    gains: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    injuries: list[str] = Field(default_factory=list)
    prop_transfers: list[str] = Field(default_factory=list)


class ScreenplayExtraction(ExtractionModel):
    screenplay_id: str = Field(min_length=1)
    scenes: list[Scene]
    characters: list[Character] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    production_elements: list[ProductionElement] = Field(default_factory=list)
    continuity_states: list[ContinuityState] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_references(self):
        def unique(items, attr, label):
            values = [getattr(item, attr) for item in items]
            if len(values) != len(set(values)):
                raise ValueError(f"{label} IDs must be unique")
        if not self.scenes:
            raise ValueError("screenplay must contain at least one scene")
        unique(self.scenes, "scene_id", "scene")
        unique(self.characters, "character_id", "character")
        unique(self.locations, "location_id", "location")
        unique(self.production_elements, "element_id", "production element")
        numbers = [s.scene_number for s in self.scenes]
        if numbers != sorted(numbers):
            raise ValueError("scene numbers must be ordered")
        scene_ids = {s.scene_id for s in self.scenes}
        character_ids = {c.character_id for c in self.characters}
        element_ids = {e.element_id for e in self.production_elements}
        for scene in self.scenes:
            if missing := set(scene.character_ids) - character_ids:
                raise ValueError(f"unknown character IDs: {sorted(missing)}")
            if missing := set(scene.production_element_ids) - element_ids:
                raise ValueError(f"unknown production element IDs: {sorted(missing)}")
        for state in self.continuity_states:
            if state.scene_id not in scene_ids:
                raise ValueError(f"unknown continuity scene ID: {state.scene_id}")
        return self
