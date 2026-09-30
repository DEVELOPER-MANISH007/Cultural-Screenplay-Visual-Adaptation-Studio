"""Versioned JSON persistence for canonical project state; independent of Streamlit."""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.models.project_state import ProjectState


class ProjectStateLoadError(ValueError):
    """The stored JSON is unreadable or does not match the supported state schema."""


class ProjectStore:
    def __init__(self, data_root: str | Path | None = None):
        self.data_root = Path(data_root) if data_root is not None else Path(__file__).resolve().parents[2] / "data"
        self.projects_root = self.data_root / "projects"

    def _path(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
            raise ValueError("project_id may contain only letters, numbers, underscores, and hyphens")
        return self.projects_root / project_id / "project.json"

    def project_exists(self, project_id: str) -> bool:
        return self._path(project_id).is_file()

    def create_project(self, state: ProjectState) -> ProjectState:
        path = self._path(state.project_id)
        if path.exists():
            raise FileExistsError(f"project already exists: {state.project_id}")
        state = state.model_copy(update={"version": max(1, state.version), "updated_at": _now()})
        self._write_atomic(path, state)
        return state

    def save_project(self, state: ProjectState) -> ProjectState:
        path = self._path(state.project_id)
        if path.exists():
            current = self.load_project(state.project_id)
            if _content(state) == _content(current):
                return current
            saved = state.model_copy(update={"version": current.version + 1, "updated_at": _now()})
        else:
            saved = state.model_copy(update={"version": max(1, state.version), "updated_at": _now()})
        self._write_atomic(path, saved)
        return saved

    def load_project(self, project_id: str) -> ProjectState:
        path = self._path(project_id)
        if not path.is_file():
            raise FileNotFoundError(f"project state not found: {project_id}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return ProjectState.model_validate(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, OSError, TypeError) as exc:
            raise ProjectStateLoadError(f"Invalid project state at {path}: {exc}") from exc

    def _write_atomic(self, path: Path, state: ProjectState) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent,
                                             prefix=".project-", suffix=".tmp", delete=False) as handle:
                temp_name = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
            raise


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content(state: ProjectState) -> dict:
    data = state.model_dump(mode="json")
    data.pop("version", None)
    data.pop("updated_at", None)
    return data
