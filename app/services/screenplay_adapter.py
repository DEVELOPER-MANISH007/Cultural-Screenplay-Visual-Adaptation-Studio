"""Approval-gated screenplay adapter with a deterministic annotation mock."""
from __future__ import annotations

import hashlib
import re
from typing import Protocol

from app.models.adapted_screenplay import AdaptedScene, AdaptedScreenplay
from app.models.adaptation import AdaptationCategory, AdaptationChange, AdaptationChangeStatus, AdaptationPlan
from app.models.cultural_evidence import CulturalEvidence, CulturalEvidenceStatus
from app.models.project_state import ProjectState
from app.models.screenplay import ScreenplayDocument
from app.services.adaptation_store import AdaptationStore

ADAPTATION_PROMPT = "\n".join([
    "Rewrite only according to the approved changes.",
    "Do not introduce new cultural facts.",
    "Do not invent evidence.",
    "Do not change story events.",
    "Do not change character relationships unless an approved change explicitly requires it.",
    "Preserve the dramatic purpose and emotional arc.",
    "Use only the supplied original scene, approved changes, referenced evidence, and project context.",
    "Never invent Marwari phrases; preserve the original dialogue if phrase-level evidence is unavailable.",
])
DIALECT_WARNING = "Phrase-level Marwari evidence is not currently available; original dialogue was preserved."
MOCK_WARNING = "Mock adapter output uses visible annotations to demonstrate approved changes; it is not polished literary rewriting."
PRODUCTION_DESIGN_CHANGE_ID = "CHANGE_011"
PRODUCTION_DESIGN_PROPOSAL = "Add restrained background merchandise detail showing bandhej fabric being sold in Jodhpur market."
PRODUCTION_DESIGN_CONTEXT = "Jodhpur market context was explicitly provided by the human producer; it was not inferred from the screenplay."
PRODUCTION_DESIGN_BACKGROUND_ONLY = "Bandhej fabric appears only as background merchandise for sale; it is not worn by Ravi or Meena."
PRODUCTION_DESIGN_RESTRICTION = "Do not change Ravi or Meena clothing, dialogue, character action, dramatic purpose, or scene order."
PRODUCTION_DESIGN_EXCLUSIONS = "Do not add music, dance, rituals, or food."
PRODUCTION_DESIGN_APPROVAL = "Explicit human approval is required before Phase 6 can apply this proposal."


class ScreenplayAdapter(Protocol):
    def apply_scene(self, original_text: str, changes: list[AdaptationChange],
                    evidence: list[CulturalEvidence], *, context: dict[str, str | None],
                    character_context: list[dict]) -> str: ...


class MockScreenplayAdapter:
    """Deterministically appends trace annotations without altering source lines."""

    def apply_scene(self, original_text: str, changes: list[AdaptationChange],
                    evidence: list[CulturalEvidence], *, context: dict[str, str | None],
                    character_context: list[dict]) -> str:
        if not changes:
            return original_text
        evidence_by_id = {item.evidence_id: item for item in evidence}
        result = original_text
        for change in sorted(changes, key=lambda item: item.change_id):
            citations = ", ".join(change.evidence_ids)
            summary = "; ".join(evidence_by_id[eid].claim for eid in change.evidence_ids)
            marker = (f"[MOCK APPLIED {change.change_id}: {change.proposed_change} "
                      f"| Evidence {citations}: {summary}]")
            if result and not result.endswith(("\n", "\r")):
                result += "\n"
            result += marker
        return result


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _scene_chunks(original_text: str, project_state: ProjectState) -> tuple[str, list[tuple[str, str]], bool]:
    lines = original_text.splitlines(keepends=True)
    positions: list[tuple[int, str]] = []
    offset = 0
    expected_headings = {_norm(scene.heading) for scene in project_state.scenes}
    heading_re = re.compile(r"^(INT\.|EXT\.|INT/EXT\.|I/E\.)\s*.+", re.IGNORECASE)
    for line in lines:
        visible = line.rstrip("\r\n").strip()
        if _norm(visible) in expected_headings or heading_re.match(visible):
            positions.append((offset, visible))
        offset += len(line)
    if not positions:
        return original_text, [], False
    preamble = original_text[:positions[0][0]]
    chunks = []
    for index, (start, heading) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(original_text)
        chunks.append((heading, original_text[start:end]))
    aligned = len(chunks) == len(project_state.scenes)
    if aligned:
        aligned = all(_norm(header) == _norm(scene.heading) for (header, _), scene in zip(chunks, project_state.scenes))
    return preamble, chunks, aligned


def _scope_compatible(evidence: CulturalEvidence, plan: AdaptationPlan) -> tuple[bool, str | None]:
    culture = plan.culture.casefold()
    ev_culture = evidence.culture.casefold()
    if evidence.scope == "Rajasthan-general":
        if culture != "rajasthan" or ev_culture != "rajasthan":
            return False, "Evidence is Rajasthan-general rather than specific to the selected culture and region."
    elif ev_culture != culture:
        return False, f"Evidence culture {evidence.culture!r} does not match selected culture {plan.culture!r}."
    region = _norm(plan.region)
    scope = (evidence.scope or "").casefold()
    if scope == "marwar-specific" and "marwar" not in region:
        return False, "Evidence scope is Marwar-specific but the selected region is not Marwar."
    if scope == "jodhpur-specific" and not any(term in region for term in ("jodhpur", "marwar")):
        return False, "Evidence scope is Jodhpur-specific but the selected region does not include Jodhpur/Marwar."
    if scope == "western rajasthan" and not any(term in region for term in ("western rajasthan", "marwar", "jodhpur")):
        return False, "Evidence scope is Western Rajasthan and is not compatible with the selected region."
    if evidence.region:
        region_tokens = set(region.split())
        evidence_tokens = set(_norm(evidence.region).split())
        if region_tokens and evidence_tokens and not (region_tokens & evidence_tokens) and scope != "Rajasthan-general":
            return False, f"Evidence region {evidence.region!r} does not match selected region {plan.region!r}."
    if not scope:
        return False, "Evidence has no regional scope."
    if evidence.status == CulturalEvidenceStatus.INSUFFICIENT_EVIDENCE:
        return False, "Referenced evidence is marked insufficient_evidence."
    return True, None


def _evidence_category_compatible(change: AdaptationChange, evidence: CulturalEvidence) -> bool:
    if change.category == AdaptationCategory.PRODUCTION_DESIGN:
        # This is a single, tightly scoped exception for the reviewed Jodhpur-market
        # proposal. It is not a general mapping from textile evidence to production design.
        return (
            change.change_id == PRODUCTION_DESIGN_CHANGE_ID
            and change.scene_id == "SCENE_002"
            and change.target_type == "scene"
            and change.target_id == "SCENE_002"
            and change.original_element == "Ravi and Meena walk through the market."
            and change.proposed_change == PRODUCTION_DESIGN_PROPOSAL
            and change.evidence_ids == ["EVID_005"]
            and PRODUCTION_DESIGN_CONTEXT in change.assumptions
            and PRODUCTION_DESIGN_BACKGROUND_ONLY in change.assumptions
            and PRODUCTION_DESIGN_RESTRICTION in change.warnings
            and PRODUCTION_DESIGN_EXCLUSIONS in change.warnings
            and PRODUCTION_DESIGN_APPROVAL in change.warnings
            and evidence.evidence_id == "EVID_005"
            and evidence.source_id == "SRC_005"
            and evidence.category == "clothing"
            and evidence.scope == "Jodhpur-specific"
            and evidence.region == "Marwar / Jodhpur"
            and evidence.status == CulturalEvidenceStatus.VERIFIED
            and str(evidence.source_url) == "https://www.tourism.rajasthan.gov.in/shopping-in-rajasthan.html"
        )
    expected = {
        AdaptationCategory.DIALECT: {"language"}, AdaptationCategory.DIALOGUE: {"language"},
        AdaptationCategory.KINSHIP: {"kinship", "language"}, AdaptationCategory.HONORIFIC: {"honorifics", "language"},
        AdaptationCategory.GREETING: {"greetings", "language"}, AdaptationCategory.GESTURE: {"gestures"},
        AdaptationCategory.POSTURE: {"gestures", "social_behavior"}, AdaptationCategory.EYE_CONTACT: {"social_behavior"},
        AdaptationCategory.TOUCH: {"social_behavior", "gestures"}, AdaptationCategory.SEATING: {"interiors", "social_behavior"},
        AdaptationCategory.FOOD: {"food"}, AdaptationCategory.COSTUME: {"clothing", "textiles"},
        AdaptationCategory.GROOMING: {"grooming", "clothing"}, AdaptationCategory.JEWELLERY: {"jewellery", "clothing"},
        AdaptationCategory.ARCHITECTURE: {"architecture"}, AdaptationCategory.INTERIOR: {"interiors", "architecture", "textiles"},
        AdaptationCategory.PROPS: {"props"}, AdaptationCategory.TRANSPORT: {"transport"},
        AdaptationCategory.LANDSCAPE: {"landscape"}, AdaptationCategory.RITUAL: {"rituals"},
        AdaptationCategory.SOUND: {"soundscape", "music"}, AdaptationCategory.MUSIC: {"music"},
        AdaptationCategory.CHARACTER: {"occupations", "social_behavior", "kinship"},
        AdaptationCategory.RELATIONSHIP: {"kinship", "social_behavior"},
        AdaptationCategory.SOCIAL_BEHAVIOR: {"social_behavior", "greetings", "gestures", "kinship"},
        AdaptationCategory.HUMOUR: {"language", "social_behavior"}, AdaptationCategory.STORY_WORLD: {"landscape", "architecture", "rituals", "music"},
    }
    return evidence.category.casefold() in expected.get(change.category, set())


def _validate_approved_change(change: AdaptationChange, project: ProjectState, plan: AdaptationPlan,
                              evidence_by_id: dict[str, CulturalEvidence]) -> list[str]:
    errors = []
    scene = next((item for item in project.scenes if item.scene_id == change.scene_id), None)
    if scene is None:
        return [f"Scene {change.scene_id} does not exist in ProjectState."]
    allowed_targets = {
        "scene": {item.scene_id for item in project.scenes},
        "character": {item.character_id for item in project.characters},
        "location": {item.location_id for item in project.locations},
        "production_element": {item.element_id for item in project.production_elements},
        "project": {project.project_id},
    }
    if change.target_type not in allowed_targets:
        errors.append(f"Unknown target_type {change.target_type!r}.")
    elif change.target_id not in allowed_targets[change.target_type]:
        errors.append(f"Target {change.target_id} does not exist as {change.target_type}.")
    elif change.target_type == "character" and change.target_id not in scene.character_ids:
        errors.append(f"Character {change.target_id} is not referenced by {change.scene_id}.")
    elif change.target_type == "production_element" and change.target_id not in scene.production_element_ids:
        errors.append(f"Production element {change.target_id} is not referenced by {change.scene_id}.")
    if not change.evidence_ids:
        errors.append("Approved cultural change has no evidence IDs.")
    for evidence_id in change.evidence_ids:
        item = evidence_by_id.get(evidence_id)
        if item is None:
            errors.append(f"Evidence ID {evidence_id} does not exist in the supplied evidence catalog.")
            continue
        compatible, reason = _scope_compatible(item, plan)
        if not compatible:
            errors.append(f"Evidence {evidence_id} is not scope-compatible: {reason}")
        if not _evidence_category_compatible(change, item):
            errors.append(f"Evidence {evidence_id} category {item.category!r} does not support change category {change.category.value!r}.")
    if plan.culture.casefold() == "marwari" and change.category in {AdaptationCategory.DIALECT, AdaptationCategory.DIALOGUE}:
        errors.append(DIALECT_WARNING)
    if plan.culture.casefold() == "marwari" and re.search(r"[\u0900-\u097f]", change.proposed_change):
        errors.append(DIALECT_WARNING)
    return list(dict.fromkeys(errors))


def adapt_screenplay(project_state: ProjectState, adaptation_plan: AdaptationPlan,
                     cultural_evidence: list[CulturalEvidence], original_screenplay: str | ScreenplayDocument,
                     *, adapter: ScreenplayAdapter | None = None) -> AdaptedScreenplay:
    """Pure adapter. The plan must be loaded by the caller from persistent storage."""
    original_text = original_screenplay.raw_text if isinstance(original_screenplay, ScreenplayDocument) else original_screenplay
    if adaptation_plan.project_id != project_state.project_id:
        raise ValueError("AdaptationPlan project_id does not match ProjectState")
    if not original_text:
        raise ValueError("Original screenplay text is required")
    provider = adapter or MockScreenplayAdapter()
    evidence_by_id = {item.evidence_id: item for item in cultural_evidence}
    if len(evidence_by_id) != len(cultural_evidence):
        raise ValueError("duplicate CulturalEvidence IDs supplied")
    preamble, chunks, aligned = _scene_chunks(original_text, project_state)
    warnings = [MOCK_WARNING] if isinstance(provider, MockScreenplayAdapter) else []
    if not aligned:
        warnings.append("Original screenplay scene headings could not be aligned exactly with ProjectState; no changes were applied.")
    approved_changes = [c for c in adaptation_plan.changes if c.status == AdaptationChangeStatus.APPROVED]
    unapproved = [c for c in adaptation_plan.changes if c.status != AdaptationChangeStatus.APPROVED]
    if unapproved:
        warnings.append(f"{len(unapproved)} pending, rejected, or needs-revision change(s) were not applied.")
    changes_by_scene: dict[str, list[AdaptationChange]] = {}
    blocked_ids: list[str] = []
    for change in approved_changes:
        reasons = []
        if not aligned:
            reasons.append("Scene text alignment failed; cannot safely apply to a scene.")
        reasons.extend(_validate_approved_change(change, project_state, adaptation_plan, evidence_by_id))
        if reasons:
            blocked_ids.append(change.change_id)
            warnings.extend(f"Blocked {change.change_id}: {reason}" for reason in reasons)
        else:
            changes_by_scene.setdefault(change.scene_id, []).append(change)
    adapted_scenes: list[AdaptedScene] = []
    adapted_chunks: list[str] = []
    applied_ids: list[str] = []
    all_used_evidence: list[str] = []
    assumptions: list[str] = []
    for index, source_scene in enumerate(project_state.scenes):
        header, source_chunk = chunks[index] if aligned and index < len(chunks) else (source_scene.heading, "")
        scene_changes = changes_by_scene.get(source_scene.scene_id, [])
        scene_evidence = [evidence_by_id[eid] for change in scene_changes for eid in change.evidence_ids]
        characters = [c.model_dump(mode="json") for c in project_state.characters if c.character_id in source_scene.character_ids]
        context = {"culture": adaptation_plan.culture, "dialect": adaptation_plan.dialect,
                   "region": adaptation_plan.region, "setting": adaptation_plan.setting, "script": adaptation_plan.script}
        adapted_chunk = provider.apply_scene(source_chunk, scene_changes, scene_evidence, context=context, character_context=characters)
        scene_applied = [c.change_id for c in scene_changes]
        scene_refs = list(dict.fromkeys(eid for c in scene_changes for eid in c.evidence_ids))
        scene_warnings = [warning for warning in warnings if any(c.change_id in warning for c in approved_changes if c.scene_id == source_scene.scene_id)]
        adapted_scenes.append(AdaptedScene(
            scene_id=source_scene.scene_id, scene_number=source_scene.scene_number,
            original_heading=header, adapted_heading=header, original_text=source_chunk, adapted_text=adapted_chunk,
            applied_change_ids=scene_applied, evidence_ids=scene_refs, warnings=scene_warnings,
        ))
        adapted_chunks.append(adapted_chunk)
        applied_ids.extend(scene_applied)
        all_used_evidence.extend(scene_refs)
        assumptions.extend(a for c in scene_changes for a in c.assumptions)
    adapted_text = preamble + "".join(adapted_chunks) if aligned else original_text
    digest = hashlib.sha256((project_state.project_id + adaptation_plan.plan_id + str(adaptation_plan.version) + original_text).encode("utf-8")).hexdigest()[:16].upper()
    timestamp = adaptation_plan.updated_at
    return AdaptedScreenplay(
        adaptation_id=f"ADAPT_{digest}", project_id=project_state.project_id,
        source_screenplay_id=project_state.screenplay_id, plan_id=adaptation_plan.plan_id,
        plan_version=adaptation_plan.version, culture=adaptation_plan.culture, dialect=adaptation_plan.dialect,
        region=adaptation_plan.region, setting=adaptation_plan.setting, scenes=adapted_scenes,
        applied_change_ids=applied_ids, blocked_change_ids=blocked_ids,
        evidence_ids=list(dict.fromkeys(all_used_evidence)), original_screenplay_text=original_text,
        adapted_screenplay_text=adapted_text, warnings=list(dict.fromkeys(warnings)),
        assumptions=list(dict.fromkeys(assumptions)), created_at=timestamp, updated_at=timestamp,
    )


def adapt_persisted_screenplay(project_state: ProjectState, cultural_evidence: list[CulturalEvidence],
                               original_screenplay: str | ScreenplayDocument, *,
                               plan_store: AdaptationStore | None = None,
                               adapter: ScreenplayAdapter | None = None) -> AdaptedScreenplay:
    """Load the persisted plan before adapting; never trust session-only review state."""
    store = plan_store or AdaptationStore()
    plan = store.load_plan(project_state.project_id)
    return adapt_screenplay(project_state, plan, cultural_evidence, original_screenplay, adapter=adapter)
