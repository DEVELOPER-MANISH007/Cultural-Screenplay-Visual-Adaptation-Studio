"""Production element model (props, locations, sound, etc.)."""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ProductionElement(BaseModel):
    """A production element such as a prop, location or set piece."""

    model_config = ConfigDict(str_strip_whitespace=True)

    element_id: str = Field(default_factory=lambda: uuid4().hex)
    category: str = Field(min_length=1)
    description: str = ""
    scenes: list[int] = Field(default_factory=list)
