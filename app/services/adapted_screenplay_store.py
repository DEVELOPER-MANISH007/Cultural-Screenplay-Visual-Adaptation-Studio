"""Atomic JSON persistence for adapted screenplay output; never writes project.json."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from pydantic import ValidationError

from app.models.adapted_screenplay import AdaptedScreenplay


class AdaptedScreenplayLoadError(ValueError):
    """Stored adapted screenplay is invalid or unreadable."""


class AdaptedScreenplayStore:
    def __init__(self, data_root: str | Path | None = None):
        self.data_root = Path(data_root) if data_root is not None else Path(__file__).resolve().parents[2] / "data"
        self.projects_root = self.data_root / "projects"

    def _path(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
            raise ValueError("project_id may contain only letters, numbers, underscores, and hyphens")
        return self.projects_root / project_id / "adapted_screenplay.json"

    def exists(self, project_id: str) -> bool:
        return self._path(project_id).is_file()

    def save_adapted_screenplay(self, screenplay: AdaptedScreenplay) -> AdaptedScreenplay:
        path = self._path(screenplay.project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(screenplay.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent,
                                             prefix=".adapted-screenplay-", suffix=".tmp", delete=False) as handle:
                temp_name = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
            raise
        return screenplay

    def load_adapted_screenplay(self, project_id: str) -> AdaptedScreenplay:
        path = self._path(project_id)
        if not path.is_file():
            raise FileNotFoundError(f"adapted screenplay not found for project {project_id}")
        try:
            return AdaptedScreenplay.model_validate_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, OSError, TypeError) as exc:
            raise AdaptedScreenplayLoadError(f"Invalid adapted screenplay at {path}: {exc}") from exc
