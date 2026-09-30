"""Atomic storage for generated visual media and their request/batch metadata."""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.models.visual_generation import GeneratedVisualArtifact, VisualGenerationBatch


class VisualArtifactLoadError(ValueError):
    """Saved artifact batch is malformed or inconsistent with its project path."""


class VisualArtifactStore:
    def __init__(self, data_root: str | Path | None = None):
        self.data_root = Path(data_root) if data_root is not None else Path(__file__).resolve().parents[2] / "data"
        self.projects_root = self.data_root / "projects"

    def _project_dir(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
            raise ValueError("project_id may contain only letters, numbers, underscores, and hyphens")
        return self.projects_root / project_id

    def _metadata_path(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "visual_artifacts.json"

    def batch_exists(self, project_id: str) -> bool:
        return self._metadata_path(project_id).is_file()

    def save_artifact(self, artifact: GeneratedVisualArtifact) -> GeneratedVisualArtifact:
        project_dir = self._project_dir(artifact.project_id)
        visual_dir = project_dir / "visuals"
        visual_dir.mkdir(parents=True, exist_ok=True)
        metadata = dict(artifact.image_metadata)
        media_content = metadata.pop("_media_content", None)
        representation = metadata.get("representation")
        if media_content is None:
            if artifact.image_path:
                return artifact
            return artifact.model_copy(update={"image_metadata": metadata})
        extensions = {"svg": ".svg", "png": ".png", "jpeg": ".jpg", "jpg": ".jpg"}
        extension = extensions.get(representation)
        if extension is None:
            raise ValueError("unsupported media representation; use SVG, PNG or JPEG")
        if representation == "svg" and (not isinstance(media_content, str) or not media_content.startswith("<svg")):
            raise ValueError("invalid SVG media content")
        if representation in {"png", "jpeg", "jpg"} and not isinstance(media_content, bytes):
            raise ValueError("PNG/JPEG media content must be bytes")
        if representation == "png" and not media_content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PNG media content has an invalid signature")
        if representation in {"jpeg", "jpg"} and not (media_content.startswith(b"\xff\xd8") and media_content.endswith(b"\xff\xd9")):
            raise ValueError("JPEG media content has an invalid signature")
        filename = f"{artifact.artifact_id}{extension}"
        path = visual_dir / filename
        if representation == "svg":
            self._atomic_write_text(path, media_content, prefix=".visual-image-")
        else:
            self._atomic_write_bytes(path, media_content, prefix=".visual-image-")
        metadata["media_format"] = representation
        return artifact.model_copy(update={
            "image_path": f"visuals/{filename}", "image_metadata": metadata,
        })

    def save_batch(self, batch: VisualGenerationBatch) -> VisualGenerationBatch:
        project_dir = self._project_dir(batch.project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        artifacts = [self.save_artifact(item) if item.image_metadata.get("_media_content") is not None else item for item in batch.artifacts]
        to_save = batch.model_copy(update={"artifacts": artifacts})
        metadata_path = project_dir / "visual_artifacts.json"
        if metadata_path.exists():
            previous = self.load_batch(batch.project_id)
            to_save = to_save.model_copy(update={
                "created_at": previous.created_at,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "version": previous.version + 1,
            })
        payload = json.dumps(to_save.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self._atomic_write_text(metadata_path, payload, prefix=".visual-artifacts-")
        return to_save

    def load_batch(self, project_id: str) -> VisualGenerationBatch:
        path = self._metadata_path(project_id)
        if not path.is_file():
            raise FileNotFoundError(f"visual artifacts not found for project {project_id}")
        try:
            batch = VisualGenerationBatch.model_validate_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, OSError, TypeError) as exc:
            raise VisualArtifactLoadError(f"Invalid visual artifact metadata at {path}: {exc}") from exc
        if batch.project_id != project_id:
            raise VisualArtifactLoadError("batch project_id does not match storage path")
        if any(item.project_id != project_id for item in batch.artifacts) or any(item.project_id != project_id for item in batch.requests):
            raise VisualArtifactLoadError("visual artifact or request project_id does not match batch")
        return batch

    def read_media(self, project_id: str, artifact: GeneratedVisualArtifact) -> bytes:
        project_dir = self._project_dir(project_id)
        if artifact.project_id != project_id or not artifact.image_path:
            raise ValueError("artifact has no media path for this project")
        relative = Path(artifact.image_path)
        allowed_names = {f"{artifact.artifact_id}.svg", f"{artifact.artifact_id}.png", f"{artifact.artifact_id}.jpg"}
        if relative.parts[:1] != ("visuals",) or len(relative.parts) != 2 or relative.name not in allowed_names:
            raise ValueError("artifact image_path is outside the managed visuals directory")
        path = project_dir / relative
        return path.read_bytes()

    @staticmethod
    def _atomic_write_text(path: Path, text: str, *, prefix: str) -> None:
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent,
                                             prefix=prefix, suffix=".tmp", delete=False) as handle:
                temp_name = handle.name
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
            raise

    @staticmethod
    def _atomic_write_bytes(path: Path, content: bytes, *, prefix: str) -> None:
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=prefix, suffix=".tmp", delete=False) as handle:
                temp_name = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
            raise
