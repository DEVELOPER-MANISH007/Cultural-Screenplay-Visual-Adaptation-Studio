"""Atomic JSON persistence for visual packs; separate from all earlier phase artifacts."""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.models.visual_pack import VisualProductionPack


class VisualPackLoadError(ValueError):
    """Stored visual production pack is malformed or incompatible."""


class VisualPackStore:
    def __init__(self, data_root: str | Path | None = None):
        self.data_root = Path(data_root) if data_root is not None else Path(__file__).resolve().parents[2] / "data"
        self.projects_root = self.data_root / "projects"

    def _path(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
            raise ValueError("project_id may contain only letters, numbers, underscores, and hyphens")
        return self.projects_root / project_id / "visual_production_pack.json"

    def pack_exists(self, project_id: str) -> bool:
        return self._path(project_id).is_file()

    def save_pack(self, pack: VisualProductionPack) -> VisualProductionPack:
        """Save a validated snapshot, incrementing version only when replacing a saved pack."""
        path = self._path(pack.project_id)
        to_save = pack
        if path.is_file():
            prior = self.load_pack(pack.project_id)
            to_save = pack.model_copy(update={
                "created_at": prior.created_at,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "version": prior.version + 1,
            })
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(to_save.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent,
                                             prefix=".visual-pack-", suffix=".tmp", delete=False) as handle:
                temp_name = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
            raise
        return to_save

    def load_pack(self, project_id: str) -> VisualProductionPack:
        path = self._path(project_id)
        if not path.is_file():
            raise FileNotFoundError(f"visual production pack not found for project {project_id}")
        try:
            pack = VisualProductionPack.model_validate_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, OSError, TypeError) as exc:
            raise VisualPackLoadError(f"Invalid visual production pack at {path}: {exc}") from exc
        if pack.project_id != project_id:
            raise VisualPackLoadError("stored visual pack project_id does not match its storage path")
        return pack
