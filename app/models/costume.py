"""Costume model."""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Costume(BaseModel):
    """A costume and the scenes (by scene number) in which it appears."""

    model_config = ConfigDict(str_strip_whitespace=True)

    costume_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str = Field(min_length=1)
    description: str = ""
    scenes: list[int] = Field(default_factory=list)
