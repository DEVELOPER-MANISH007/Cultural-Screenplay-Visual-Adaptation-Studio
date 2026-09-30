"""Scene model."""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Scene(BaseModel):
    """A single screenplay scene (placeholder; no extraction logic yet)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    scene_id: str = Field(default_factory=lambda: uuid4().hex)
    scene_number: int = Field(ge=1)
    heading: str = Field(min_length=1)
    summary: str = ""
