"""Project model."""

from __future__ import annotations

from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ProjectStatus(str, Enum):
    """Lifecycle status of a project. Phase 0 only uses ``DRAFT``."""

    DRAFT = "draft"


class Project(BaseModel):
    """A screenplay adaptation project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: str = Field(default_factory=lambda: uuid4().hex)
    title: str = Field(min_length=1)
    source_filename: str | None = None
    culture: str = ""
    dialect: str = ""
    region: str = ""
    setting: str = ""
    script: str = ""
    status: ProjectStatus = ProjectStatus.DRAFT
