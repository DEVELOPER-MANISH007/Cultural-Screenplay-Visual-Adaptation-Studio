"""Deterministic, evidence-bounded adaptation planning (no screenplay rewriting)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from app.models.adaptation import (
    AdaptationCategory as Category, AdaptationChange, AdaptationChangeStatus as ChangeStatus,
    AdaptationPlan, AdaptationPlanStatus,
)
from app.models.cultural_evidence import CulturalEvidence, CulturalEvidenceStatus, LanguageEvidence
from app.models.extraction import ScreenplayExtraction
from app.models.project_state import ProjectState

INSUFFICIENT = "Insufficient evidence for a culture-specific adaptation."
DIALECT_WARNING = "Phrase-level Marwari evidence is not currently available in the cultural evidence pack."
GENERAL_WARNING = "Evidence is Rajasthan-general rather than Marwar-specific."


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _raw_dialogue(raw_text: str | None, project: ProjectState) -> dict[tuple[str, str], str]:
    """Locate verbatim speaker turns where canonical names/aliases appear as cues."""
    if not raw_text:
        return {}
    scenes = project.scenes
    heading_to_index = {_norm(scene.heading): i for i, scene in enumerate(scenes)}
    names: dict[str, tuple[str, str]] = {}
    for character in project.characters:
        for name in [character.canonical_name, *character.aliases]:
            if name:
                names[_norm(name)] = (character.character_id, name)
    by_scene: dict[tuple[str, str], list[str]] = {}
    current_scene = scenes[0].scene_id if scenes else ""
    active_character: str | None = None
    active_lines: list[str] = []
    def flush():
        nonlocal active_character, active_lines
        if active_character and active_lines:
            text = "\n".join(active_lines).strip()
            if text:
                by_scene.setdefault((current_scene, active_character), []).append(text)
        active_character, active_lines = None, []
    for line in raw_text.splitlines():
        stripped = line.strip()
        norm_line = _norm(stripped)
        if norm_line in heading_to_index:
            flush()
            current_scene = scenes[heading_to_index[norm_line]].scene_id
            continue
        if re.match(r"^(INT\.|EXT\.|INT/EXT\.|I/E\.)", stripped, re.I):
            flush()
            # Heading normalization may differ in small punctuation; follow screenplay order.
            idx = next((i for i, scene in enumerate(scenes) if _norm(scene.heading) == norm_line), None)
            if idx is not None:
                current_scene = scenes[idx].scene_id
            continue
        cue = re.sub(r"\s*\([^)]*\)\s*$", "", stripped).rstrip(":").strip()
        character_match = names.get(_norm(cue))
        if character_match:
            flush()
            active_character = character_match[0]
            continue
        if active_character:
            if not stripped:
                # Keep natural line breaks, but don't absorb large blank gaps between cues.
                if active_lines and active_lines[-1] != "":
                    active_lines.append("")
            elif stripped.isupper() and len(stripped.split()) <= 5:
                flush()
            else:
                active_lines.append(stripped)
    flush()
    return {key: "\n".join(values) for key, values in by_scene.items()}


def _scope_eligible(evidence: CulturalEvidence, culture: str, region: str) -> bool:
    if evidence.scope == "Rajasthan-general":
        return culture.casefold() == "marwari"
    if evidence.culture.casefold() not in {culture.casefold(), "marwari" if culture.casefold() == "marwari" else ""}:
        return False
    if evidence.region is None:
        return evidence.scope in {"Marwar-specific", "Jodhpur-specific", "Western Rajasthan"}
    region_norm, evidence_region = _norm(region), _norm(evidence.region)
    return evidence_region in region_norm or any(token in evidence_region for token in region_norm.split() if len(token) > 3)


def _context_matches(evidence: CulturalEvidence, text: str) -> bool:
    corpus = _norm(text)
    cues = {
        "architecture": ("architecture", "house", "haveli", "fort", "temple", "jodhpur", "mehrangarh", "blue city"),
        "clothing": ("clothing", "costume", "dress", "wear", "turban", "safa", "dupatta", "bandhej", "bandhini"),
        "textiles": ("textile", "carpet", "rug", "dhurrie", "durrie", "bandhej", "fabric"),
        "landscape": ("landscape", "desert", "dune", "khejri", "camel", "osian", "stepwell", "village"),
        "music": ("music", "song", "sing", "folk", "festival", "marwar festival"),
        "dance": ("dance", "ghoomar", "performance", "festival"),
        "rituals": ("ritual", "wedding", "marriage", "toran", "custom"),
        "food": ("food", "meal", "eat", "cook", "kitchen", "bajra", "millet", "ker sangri", "dal baati"),
    }
    terms = cues.get(evidence.category.casefold(), ())
    return any(_norm(term) in corpus for term in terms)


def validate_plan_references(plan: AdaptationPlan, project: ProjectState, evidence: list[CulturalEvidence]) -> None:
    scenes = {item.scene_id for item in project.scenes}
    characters = {item.character_id for item in project.characters}
    element_ids = {item.element_id for item in project.production_elements}
    evidence_ids = {item.evidence_id for item in evidence}
    for change in plan.changes:
        if change.scene_id not in scenes:
            raise ValueError(f"change {change.change_id} references unknown scene {change.scene_id}")
        allowed = {"character": characters, "production_element": element_ids, "scene": scenes}
        if change.target_type in allowed and change.target_id not in allowed[change.target_type]:
            raise ValueError(f"change {change.change_id} references unknown {change.target_type} {change.target_id}")
        missing = set(change.evidence_ids) - evidence_ids
        if missing:
            raise ValueError(f"change {change.change_id} references unknown evidence IDs: {sorted(missing)}")


def create_adaptation_plan(
    project_state: ProjectState, cultural_evidence: list[CulturalEvidence], *,
    extraction: ScreenplayExtraction | None = None, language_evidence: list[LanguageEvidence] | None = None,
    raw_text: str | None = None, culture: str | None = None, dialect: str | None = None,
    region: str | None = None, setting: str | None = None, script: str | None = None,
    plan_id: str | None = None, timestamp: str | None = None,
) -> AdaptationPlan:
    """Create a pending-review plan using canonical IDs and only supplied evidence.

    The service only creates review proposals. It never edits or emits replacement screenplay text.
    """
    if extraction and extraction.screenplay_id != project_state.screenplay_id:
        raise ValueError("ScreenplayExtraction does not belong to this ProjectState")
    culture = culture or project_state.culture or "Unspecified"
    dialect = dialect if dialect is not None else project_state.dialect
    region = region or project_state.region or "Unspecified"
    setting = setting or project_state.setting or "Unspecified"
    script = script if script is not None else project_state.script
    all_evidence = list(cultural_evidence)
    evidence_by_id = {item.evidence_id: item for item in all_evidence}
    if len(evidence_by_id) != len(all_evidence):
        raise ValueError("duplicate CulturalEvidence IDs supplied")
    eligible = [item for item in all_evidence if _scope_eligible(item, culture, region)]
    local = [item for item in eligible if item.scope != "Rajasthan-general"]
    now = timestamp or datetime.now(timezone.utc).isoformat()
    plan_id = plan_id or f"PLAN_{uuid4().hex[:12].upper()}"
    changes: list[AdaptationChange] = []
    unresolved: list[str] = []
    global_warnings = [
        "This is a planning document only; screenplay dialogue, events, order, relationships and descriptions remain unchanged.",
        "All adaptation changes require human review; none are automatically approved.",
    ]
    if culture.casefold() == "marwari" and not any(
        item.dialect and item.dialect.casefold() == (dialect or "marwari").casefold()
        and item.phrase and item.meaning and item.status != CulturalEvidenceStatus.INSUFFICIENT_EVIDENCE
        for item in (language_evidence or [])
    ):
        global_warnings.append(DIALECT_WARNING)
        unresolved.append("Which source-verified Marwari phrase forms and regional variants should a qualified language reviewer approve?")
    if any(item.scope == "Rajasthan-general" for item in eligible):
        global_warnings.append(GENERAL_WARNING)
    conflict_groups: dict[str, list[CulturalEvidence]] = {}
    for item in eligible:
        if item.conflict_group:
            conflict_groups.setdefault(item.conflict_group, []).append(item)
    for group in conflict_groups.values():
        if len({item.claim for item in group}) > 1:
            detail = "; ".join(f"{item.evidence_id} ({item.source_title}): {item.claim}" for item in group)
            global_warnings.append(f"Cultural evidence conflict: {detail}")

    def add(scene_id: str, category: Category, target_type: str, target_id: str, original: str, proposed: str,
            rationale: str, refs: list[CulturalEvidence] | None = None, assumptions: list[str] | None = None,
            warnings: list[str] | None = None, *, insufficient: bool = False):
        refs = refs or []
        ws = list(warnings or [])
        if insufficient or not refs:
            ws.append(INSUFFICIENT)
            status = ChangeStatus.INSUFFICIENT_EVIDENCE
            confidence = 0.0
            refs = []
        elif all(item.scope == "Rajasthan-general" for item in refs):
            ws.append(GENERAL_WARNING)
            status = ChangeStatus.NEEDS_REVIEW
            confidence = min(0.49, max(item.confidence for item in refs))
        elif any(item.conflict_group and len({x.claim for x in eligible if x.conflict_group == item.conflict_group}) > 1 for item in refs):
            for item in refs:
                if item.conflict_group and len({x.claim for x in eligible if x.conflict_group == item.conflict_group}) > 1:
                    ws.append("Cultural evidence conflict; human review must preserve competing claims.")
            status = ChangeStatus.NEEDS_REVIEW
            confidence = min(item.confidence for item in refs)
        else:
            status = ChangeStatus.PENDING
            confidence = min(item.confidence for item in refs)
        changes.append(AdaptationChange(
            change_id=f"CHANGE_{len(changes)+1:03d}", scene_id=scene_id, category=category,
            target_type=target_type, target_id=target_id, original_element=original,
            proposed_change=proposed, rationale=rationale, evidence_ids=[item.evidence_id for item in refs],
            confidence=confidence, status=status, assumptions=assumptions or [], warnings=list(dict.fromkeys(ws)),
        ))

    dialogue = _raw_dialogue(raw_text, project_state)
    recurring = [char for char in project_state.characters if len(set(char.scene_ids)) > 1]
    for char in recurring:
        first_scene = next((scene_id for scene_id in char.scene_ids if any(s.scene_id == scene_id for s in project_state.scenes)), None)
        if first_scene:
            profile = f"{char.character_id}: name={char.canonical_name}; age={char.age or 'unspecified'}; role={char.role or 'unspecified'}; relationships={char.relationships}; personality={char.personality}; emotional_state={char.emotional_state or 'unspecified'}"
            add(first_scene, Category.CHARACTER, "character", char.character_id, profile,
                "Preserve the canonical identity, name, relationships, personality cues and emotional arc. Request human review before any culture-specific characterization.",
                "The recurring character is present in the source screenplay. No supplied evidence justifies changing identity or relationships.",
                insufficient=True, warnings=["Character identity and relationships must not be changed to make the screenplay appear more culturally specific."])
            unresolved.append(f"Does the portrayal of {char.character_id} require a locally reviewed social-context note? Do not infer a change from the character's name or identity.")

    for scene in project_state.scenes:
        scene_text = " ".join([scene.heading, scene.location or "", scene.sub_location or "", scene.summary,
                               scene.dramatic_purpose or "", scene.mood or "", *scene.continuity_notes])
        # Dialect review is keyed to canonical speakers and uses only verbatim source text when available.
        for char_id in scene.character_ids:
            char = next((item for item in project_state.characters if item.character_id == char_id), None)
            if not char:
                continue
            source_dialogue = dialogue.get((scene.scene_id, char_id))
            if not source_dialogue and raw_text:
                continue
            original = source_dialogue or "Dialogue is not present in the structured extraction; consult the source screenplay for this character's exact lines."
            add(scene.scene_id, Category.DIALECT, "character", char_id, original,
                "Keep the original dialogue and meaning unchanged. Queue the identified lines for a qualified Marwari language reviewer after phrase-level evidence is added.",
                "Phase 4 contains no source-verified Marwari phrase/meaning/context records. No Marwari wording has been generated.",
                insufficient=True, warnings=[DIALECT_WARNING],
                assumptions=["Any future dialect pass must preserve each line's meaning, speaker intent and story function."])
            unresolved.append(f"Source-verify dialect treatment for {char_id} in {scene.scene_id}; retain the original dialogue until review.")

        # Existing costume elements are the only visual elements considered here. Missing or culturally
        # unspecified clothing gets a review task rather than an invented wardrobe choice.
        scene_elements = [e for e in project_state.production_elements if scene.scene_id in e.scenes]
        costumes = [e for e in scene_elements if e.category.casefold() == "costume"]
        for char_id in scene.character_ids:
            char = next((item for item in project_state.characters if item.character_id == char_id), None)
            if not char:
                continue
            if costumes:
                for element in costumes:
                    evidence_matches = [e for e in local if e.category.casefold() in {"clothing", "textiles"}
                                        and _context_matches(e, scene_text + " " + (element.name or "") + " " + (element.description or ""))]
                    add(scene.scene_id, Category.COSTUME, "production_element", element.element_id,
                        f"{element.name}: {element.description or 'description unspecified'}",
                        "Retain the existing costume description unless a human reviewer selects a directly supported, scene-appropriate detail.",
                        "The source screenplay's costume element and its story function remain intact; only consider evidence that matches this scene's stated context.",
                        refs=evidence_matches, insufficient=not evidence_matches,
                        assumptions=[f"Character association remains the canonical scene membership for {char_id}; no costume-character link is inferred."])
            else:
                add(scene.scene_id, Category.COSTUME, "character", char_id,
                    f"No costume is specified for {char.canonical_name} ({char_id}) in {scene.scene_id}.",
                    "Do not add a concrete costume yet. Ask a human reviewer for scene-specific clothing evidence before making a choice.",
                    "The current clothing evidence is festival/craft-contextual and does not by itself justify inventing everyday rural clothing for this character.",
                    insufficient=True, warnings=["Existing clothing evidence does not establish this character's everyday or scene-specific costume."])

        # Inspect scene text against available domains. A match yields a conditional review proposal, never an edit.
        cue_map = {
            "architecture": (Category.ARCHITECTURE, ("house", "haveli", "fort", "temple", "jodhpur", "mehrangarh", "architecture")),
            "landscape": (Category.LANDSCAPE, ("desert", "dune", "khejri", "camel", "osian", "stepwell", "landscape", "village")),
            "music": (Category.MUSIC, ("music", "song", "sing", "festival", "folk")),
            "dance": (Category.MUSIC, ("dance", "ghoomar", "performance", "festival")),
            "rituals": (Category.RITUAL, ("ritual", "wedding", "marriage", "toran", "custom")),
            "food": (Category.FOOD, ("food", "meal", "eat", "cook", "kitchen", "bajra", "millet", "ker sangri", "dal baati")),
        }
        for evidence_category, (plan_category, cues) in cue_map.items():
            if not any(_norm(cue) in _norm(scene_text) for cue in cues):
                continue
            candidates = [e for e in eligible if e.category.casefold() == evidence_category and _context_matches(e, scene_text)]
            if not candidates:
                add(scene.scene_id, plan_category, "scene", scene.scene_id, scene_text,
                    "Leave the existing scene element unchanged; request source-backed regional review before adding cultural detail.",
                    "The screenplay contains a potentially relevant element, but the current pack has no sufficiently scoped evidence for it.",
                    insufficient=True)
                unresolved.append(f"Find locally scoped evidence for {evidence_category} in {scene.scene_id} before proposing a concrete change.")
            else:
                local_candidates = [e for e in candidates if e.scope != "Rajasthan-general"]
                selected = local_candidates or candidates
                add(scene.scene_id, plan_category, "scene", scene.scene_id, scene_text,
                    "Consider the cited detail only if a human confirms it fits this scene's time, place and story function; do not alter events or scene order.",
                    "A screenplay cue overlaps with the source claim, but the source's stated scope and context still constrain any use.",
                    refs=selected, assumptions=["Evidence overlap is a review lead, not a finding that the screenplay is inaccurate."])
    if not changes:
        unresolved.append("No screenplay element was sufficiently specific for a culture-linked planning item; review the screenplay and add evidence if needed.")
    # Stable de-duplication of questions and warnings.
    global_warnings = list(dict.fromkeys(global_warnings))
    plan = AdaptationPlan(
        plan_id=plan_id, project_id=project_state.project_id, culture=culture, dialect=dialect,
        region=region, setting=setting, script=script, status=AdaptationPlanStatus.PENDING_REVIEW,
        changes=changes, unresolved_questions=list(dict.fromkeys(unresolved)),
        global_warnings=global_warnings, created_at=now, updated_at=now,
    )
    validate_plan_references(plan, project_state, all_evidence)
    return plan


class MockAdaptationPlanner:
    """Offline deterministic adapter around the evidence-constrained planner."""
    def create_adaptation_plan(self, project_state: ProjectState, cultural_evidence: list[CulturalEvidence], **kwargs) -> AdaptationPlan:
        kwargs.setdefault("plan_id", f"PLAN_{project_state.project_id}")
        kwargs.setdefault("timestamp", project_state.updated_at)
        return create_adaptation_plan(project_state, cultural_evidence, **kwargs)
