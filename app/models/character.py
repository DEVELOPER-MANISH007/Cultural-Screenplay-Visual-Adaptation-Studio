"""Character model."""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Character(BaseModel):
    """A screenplay character (placeholder; no extraction logic yet)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    character_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    role: str = ""
