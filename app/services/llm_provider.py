"""Provider abstraction and deterministic offline extraction provider."""
from __future__ import annotations

import re
from typing import Any, Protocol

from app.models.screenplay import ScreenplayDocument


class LLMProvider(Protocol):
    def generate_structured(self, *, prompt: str, schema: type, screenplay: ScreenplayDocument) -> Any: ...


_HEADING = re.compile(r"^(INT\.|EXT\.|INT/EXT\.|I/E\.)\s*(.*?)\s+-\s+(.+?)\s*$", re.IGNORECASE)
_SPEAKER = re.compile(r"^[A-Z][A-Z0-9 .'-]{0,39}$")
_PROP_NOUNS = {
    "envelope", "table", "letter", "cup", "glass", "phone", "bag", "key", "book",
    "chair", "knife", "box", "bottle", "photo", "photograph", "wallet", "watch",
    "umbrella", "lamp", "door", "car", "bicycle",
}
_ADJECTIVE = r"(?:old|new|small|large|little|red|blue|wooden|broken|empty|sealed|open)"
_OBJECT = re.compile(rf"\b({_ADJECTIVE}\s+)?({'|'.join(sorted(_PROP_NOUNS, key=len, reverse=True))})\b", re.IGNORECASE)


def _display(value: str) -> str:
    """Make a display form from explicit text without adding semantic information."""
    return " ".join(word[:1].upper() + word[1:].lower() for word in value.split())


class MockLLMProvider:
    """Offline lexical extraction for development and repeatable smoke tests.

    It only emits facts matched by the small explicit rule set below. It is not a
    replacement for a production structured-output model.
    """

    def generate_structured(self, *, prompt: str, schema: type, screenplay: ScreenplayDocument) -> dict:
        lines = [line.strip() for line in screenplay.raw_text.splitlines()]
        heading_positions = [(i, _HEADING.match(line)) for i, line in enumerate(lines) if _HEADING.match(line)]
        if not heading_positions:
            return {
                "screenplay_id": "mock-screenplay", "scenes": [], "extraction_warnings": [
                    "Mock provider found no standard INT./EXT. scene headings."
                ], "extraction_confidence": 0.0,
            }

        raw_scenes = []
        for index, (line_index, match) in enumerate(heading_positions, 1):
            end = heading_positions[index][0] if index < len(heading_positions) else len(lines)
            location = _display(match.group(2)) if match.group(2) else None
            raw_scenes.append({
                "scene_id": f"scene-{index}", "scene_number": index, "heading": lines[line_index],
                "int_ext": match.group(1).split(".")[0].upper().replace("INT/EXT", "INT/EXT").replace("I/E", "INT/EXT"),
                "location": location, "time_of_day": _display(match.group(3)),
                "summary": " ".join(line for line in lines[line_index + 1:end] if line)[:500] or lines[line_index],
                "character_ids": [], "production_element_ids": [], "continuity_notes": [],
                "_body": lines[line_index + 1:end], "_location": location,
            })

        # Uppercase standalone screenplay cue lines are direct character evidence.
        speaker_names: list[str] = []
        for scene in raw_scenes:
            body = scene["_body"]
            for line_index, line in enumerate(body):
                if (line and _SPEAKER.fullmatch(line) and any(ch.isalpha() for ch in line)
                        and len(line.split()) <= 4
                        and (line_index + 1 < len(body) and body[line_index + 1].strip())):
                    if line.casefold() not in {name.casefold() for name in speaker_names}:
                        speaker_names.append(line)

        characters = []
        character_by_fold = {}
        for index, source_name in enumerate(speaker_names, 1):
            char_id = f"character-{index}"
            name = _display(source_name)
            character_by_fold[source_name.casefold()] = char_id
            characters.append({"character_id": char_id, "canonical_name": name, "aliases": [],
                               "age": None, "role": None, "relationships": {}, "personality": [],
                               "dialect": None, "emotional_state": None, "entrance_scene_id": None,
                               "exit_scene_id": None, "scene_ids": []})

        locations = []
        location_ids = {}
        for scene in raw_scenes:
            location = scene["_location"]
            if location and location.casefold() not in location_ids:
                location_id = f"location-{len(locations)+1}"
                location_ids[location.casefold()] = location_id
                locations.append({"location_id": location_id, "canonical_name": location, "aliases": [],
                                  "type": None, "description": None, "scenes": []})
            if location:
                locations[[x["location_id"] for x in locations].index(location_ids[location.casefold()])]["scenes"].append(scene["scene_id"])

        elements = []
        element_ids = {}
        for scene in raw_scenes:
            body = scene["_body"]
            body_text = "\n".join(body)
            for match in _OBJECT.finditer(body_text):
                adjective = (match.group(1) or "").strip()
                noun = match.group(2).lower()
                name = f"{adjective} {noun}".strip()
                key = name.casefold()
                # A later definite reference ("the envelope") links to an already
                # explicit qualified item in the same screenplay.
                if key not in element_ids:
                    generic_key = noun.casefold()
                    existing = next((candidate for candidate in element_ids
                                     if candidate.split()[-1] == generic_key), None)
                    if existing is not None and not adjective:
                        key = existing
                    else:
                        element_id = f"element-{len(elements)+1}"
                        element_ids[key] = element_id
                        elements.append({"element_id": element_id, "category": "prop", "name": name,
                                         "description": None, "scenes": []})
                element_id = element_ids[key]
                element = next(item for item in elements if item["element_id"] == element_id)
                if scene["scene_id"] not in element["scenes"]:
                    element["scenes"].append(scene["scene_id"])

            # Associate explicit speaker mentions and all dialogue cue speakers with scenes.
            mentioned = set()
            for name in speaker_names:
                if re.search(rf"\b{re.escape(name)}\b", body_text, re.IGNORECASE):
                    mentioned.add(character_by_fold[name.casefold()])
            for line_index, line in enumerate(body):
                if line.casefold() in character_by_fold and _SPEAKER.fullmatch(line):
                    mentioned.add(character_by_fold[line.casefold()])
            scene["character_ids"] = sorted(mentioned)
            for character in characters:
                if character["character_id"] in mentioned:
                    character["scene_ids"].append(scene["scene_id"])
                    if character["entrance_scene_id"] is None:
                        character["entrance_scene_id"] = scene["scene_id"]
            scene["production_element_ids"] = [element["element_id"] for element in elements if scene["scene_id"] in element["scenes"]]

        continuity = []
        for scene in raw_scenes:
            body_text = " ".join(scene["_body"])
            carries, transfers = [], []
            for speaker in speaker_names:
                # Capture explicit carry construction only.
                carry_pattern = rf"\b{re.escape(speaker)}\b\s+[^.\n]*?\bcarrying\s+(?:an?\s+)?((?:{_ADJECTIVE}\s+)?(?:{'|'.join(sorted(_PROP_NOUNS, key=len, reverse=True))}))"
                for match in re.finditer(carry_pattern, body_text, re.IGNORECASE):
                    carries.append(f"{_display(speaker)} carries {match.group(1).lower()}")
            for match in re.finditer(r"\b([A-Z][a-z]+)\s+gives\s+(?:the\s+)?([a-z]+)\s+to\s+([A-Z][a-z]+)\b", body_text):
                giver, item, receiver = match.groups()
                # Transfer is recorded only when the item is a previously extracted prop.
                prop = next((item["name"] for item in elements if item["name"].split()[-1] == match.group(2).casefold()), None)
                if prop:
                    transfers.append(f"{giver} transfers {prop} to {receiver}")
            if carries or transfers:
                continuity.append({"scene_id": scene["scene_id"], "wears": [], "carries": carries,
                                   "knows": [], "loses": [], "gains": [], "changes": [],
                                   "injuries": [], "prop_transfers": transfers})

        for scene in raw_scenes:
            scene.pop("_body", None)
            scene.pop("_location", None)
        return {
            "screenplay_id": "mock-screenplay", "scenes": raw_scenes, "characters": characters,
            "locations": locations, "production_elements": elements, "continuity_states": continuity,
            "extraction_warnings": ["Mock provider uses deterministic lexical rules; review results for screenplay-specific wording."],
            "extraction_confidence": 0.82 if characters and locations and elements else 0.68,
        }
