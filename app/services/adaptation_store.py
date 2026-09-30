"""Versioned JSON persistence for adaptation plans and human review decisions."""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from app.models.adaptation import (
    AdaptationCategory, AdaptationChange, AdaptationChangeStatus,
    AdaptationPlan, AdaptationPlanStatus,
)


class AdaptationPlanLoadError(ValueError):
    """Stored plan JSON is invalid or incompatible with the current model."""


class AdaptationStore:
    def __init__(self, data_root: str | Path | None = None):
        self.data_root = Path(data_root) if data_root is not None else Path(__file__).resolve().parents[2] / "data"
        self.projects_root = self.data_root / "projects"

    def _path(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
            raise ValueError("project_id may contain only letters, numbers, underscores, and hyphens")
        return self.projects_root / project_id / "adaptation_plan.json"

    def plan_exists(self, project_id: str) -> bool:
        return self._path(project_id).is_file()

    def save_plan(self, plan: AdaptationPlan) -> AdaptationPlan:
        """Create a project's plan once; existing review state is never overwritten."""
        path = self._path(plan.project_id)
        if path.exists():
            raise FileExistsError(f"an adaptation plan is already saved for project {plan.project_id}; load or update it")
        saved = plan.model_copy(update={"version": max(1, plan.version)})
        self._write_atomic(path, saved)
        return saved

    def load_plan(self, project_id: str) -> AdaptationPlan:
        path = self._path(project_id)
        if not path.is_file():
            raise FileNotFoundError(f"adaptation plan not found for project {project_id}")
        try:
            return AdaptationPlan.model_validate_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, OSError, TypeError) as exc:
            raise AdaptationPlanLoadError(f"Invalid adaptation plan at {path}: {exc}") from exc

    def update_plan(self, plan: AdaptationPlan) -> AdaptationPlan:
        """Persist review statuses only; bump version/time only when review state changes."""
        path = self._path(plan.project_id)
        if not path.is_file():
            raise FileNotFoundError(f"adaptation plan not found for project {plan.project_id}")
        current = self.load_plan(plan.project_id)
        if current.plan_id != plan.plan_id:
            raise ValueError("plan_id does not match the saved project plan")
        current_ids = [change.change_id for change in current.changes]
        proposed_ids = [change.change_id for change in plan.changes]
        if proposed_ids != current_ids:
            raise ValueError("change_id values and order cannot change during review updates")
        current_data = current.model_dump(mode="json")
        proposed_data = plan.model_dump(mode="json")
        for data in (current_data, proposed_data):
            data.pop("version", None)
            data.pop("updated_at", None)
            data.pop("status", None)
            for change in data["changes"]:
                change.pop("status", None)
        if current_data != proposed_data:
            raise ValueError("update_plan only accepts plan-level and individual review status changes")
        review_changed = current.status != plan.status or any(
            old.status != new.status for old, new in zip(current.changes, plan.changes)
        )
        if not review_changed:
            return current
        updated = plan.model_copy(update={
            "version": current.version + 1,
            "created_at": current.created_at,
            "updated_at": _next_timestamp(current.updated_at),
        })
        self._write_atomic(path, updated)
        return updated

    def append_change(
        self,
        project_id: str,
        *,
        scene_id: str,
        category: AdaptationCategory,
        target_type: str,
        target_id: str,
        original_element: str,
        proposed_change: str,
        rationale: str,
        evidence_ids: list[str],
        confidence: float,
        assumptions: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> AdaptationPlan:
        """Append one pending proposal without changing existing decisions or records."""
        path = self._path(project_id)
        if not path.is_file():
            raise FileNotFoundError(f"adaptation plan not found for project {project_id}")
        current = self.load_plan(project_id)
        if target_type != "scene" or target_id != scene_id:
            raise ValueError("appended scene-level proposals must target their own scene")
        if scene_id not in {change.scene_id for change in current.changes}:
            raise ValueError(f"scene_id is not present in the saved plan: {scene_id}")
        if not evidence_ids:
            raise ValueError("an appended cultural proposal must reference evidence")

        numbers = [
            int(match.group(1))
            for change in current.changes
            if (match := re.fullmatch(r"CHANGE_(\d+)", change.change_id))
        ]
        change_id = f"CHANGE_{max(numbers, default=0) + 1:03d}"
        added = AdaptationChange(
            change_id=change_id,
            scene_id=scene_id,
            category=category,
            target_type=target_type,
            target_id=target_id,
            original_element=original_element,
            proposed_change=proposed_change,
            rationale=rationale,
            evidence_ids=evidence_ids,
            confidence=confidence,
            status=AdaptationChangeStatus.PENDING,
            assumptions=assumptions or [],
            warnings=warnings or [],
        )
        updated = current.model_copy(update={
            "changes": [*current.changes, added],
            "status": AdaptationPlanStatus.PENDING_REVIEW,
            "version": current.version + 1,
            "updated_at": _next_timestamp(current.updated_at),
        })
        self._write_atomic(path, updated)
        return updated

    @staticmethod
    def _write_atomic(path: Path, plan: AdaptationPlan) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent,
                                             prefix=".adaptation-", suffix=".tmp", delete=False) as handle:
                temp_name = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
            raise


def _next_timestamp(previous: str) -> str:
    now = datetime.now(timezone.utc)
    previous_dt = datetime.fromisoformat(previous.replace("Z", "+00:00"))
    if now <= previous_dt:
        now = previous_dt + timedelta(microseconds=1)
    return now.isoformat()
