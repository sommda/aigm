from typing import Any

from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome

MAX_PARTY_SIZE = 6
MIN_SETTING = 300  # characters; a few sentences of real detail
MIN_OPENING = 100
MIN_SHEET = 150  # per character
MAX_TOTAL = 30_000

# The description is a prompt: it lives in prompts/tools/begin_adventure.md.
SCHEMA: dict[str, Any] = {
    "name": "begin_adventure",
    "input_schema": {
        "type": "object",
        "properties": {
            "confirmed": {
                "type": "boolean",
                "description": "True only if the player has clearly confirmed, in their latest message, that they are ready to begin.",
            },
            "setting": {
                "type": "string",
                "description": f"A detailed description of the world or region as agreed with the player (at least {MIN_SETTING} characters): its nature and tone, the places, factions and people that matter, the central tension, and how dangerous it is for this party.",
            },
            "opening": {
                "type": "string",
                "description": f"Where the adventure opens (at least {MIN_OPENING} characters): the starting location, what is happening there, and the immediate hook that gets the party moving.",
            },
            "level": {"type": "integer", "description": "The party's starting level, 1-20."},
            "party": {
                "type": "array",
                "description": f"Every player character in the party, 1-{MAX_PARTY_SIZE} of them. The player controls all of them (and may switch between them); NPCs are not party members.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "sheet": {
                            "type": "string",
                            "description": f"The complete character, enough to play from (at least {MIN_SHEET} characters), in the terms of the chosen ruleset: race or species, class, level, ability scores, HP, Armor Class, saves, skills or proficiencies, features, spells, equipment, and personality.",
                        },
                    },
                    "required": ["name", "sheet"],
                },
            },
            "gm_notes": {
                "type": "string",
                "description": "Optional private notes for yourself that the player has not been told: secrets, the villain's plans, planned first encounters.",
            },
        },
        "required": ["confirmed", "setting", "opening", "level", "party"],
    },
}


def _error(*problems: str) -> ToolOutcome:
    return ToolOutcome(
        content="Cannot begin the adventure yet:\n- "
        + "\n- ".join(problems)
        + "\nNothing has changed. Fix these and call begin_adventure again, or keep talking with the player.",
        is_error=True,
    )


def _text(tool_input: dict[str, Any], key: str, minimum: int, problems: list[str]) -> str:
    value = tool_input.get(key)
    if not isinstance(value, str) or not value.strip():
        problems.append(f"'{key}' must be a non-empty string")
        return ""
    value = value.strip()
    if len(value) < minimum:
        problems.append(
            f"'{key}' is too thin ({len(value)} characters; at least {minimum} are needed). "
            "Everything about it must be written out: Session 0 is discarded once the adventure begins"
        )
    return value


def _party(raw: Any, problems: list[str]) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_PARTY_SIZE:
        problems.append(f"'party' must be a list of 1 to {MAX_PARTY_SIZE} characters")
        return []
    party, names = [], set()
    for i, member in enumerate(raw, 1):
        if not isinstance(member, dict):
            problems.append(f"party member {i} must be an object with name and sheet")
            continue
        name = member.get("name")
        label = f"party member {i}" + (f" ({name})" if isinstance(name, str) and name.strip() else "")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"{label}: 'name' must be a non-empty string")
        elif name.strip().lower() in names:
            problems.append(f"{label}: duplicate name")
        else:
            names.add(name.strip().lower())
        sheet = member.get("sheet")
        if not isinstance(sheet, str) or len(sheet.strip()) < MIN_SHEET:
            problems.append(
                f"{label}: 'sheet' is too thin (at least {MIN_SHEET} characters; give the full character: "
                "class, level, ability scores, HP, AC, saves, features, equipment, personality)"
            )
        party.append(
            {
                "name": name.strip() if isinstance(name, str) else "",
                "sheet": sheet.strip() if isinstance(sheet, str) else "",
            }
        )
    return party


def begin_adventure(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    if state.phase is not Phase.SESSION_ZERO:
        return _error("the adventure has already begun")
    if tool_input.get("confirmed") is not True:
        return _error("the player has not confirmed. Ask them whether they are ready, and wait for a clear yes")
    if state.structure is None:
        return _error(
            "the player has not been asked what kind of game they want. Ask whether they want a story with a "
            "beginning, middle and end (short, medium or long) or an endless campaign, then record the answer "
            "with set_structure"
        )
    problems: list[str] = []
    setting = _text(tool_input, "setting", MIN_SETTING, problems)
    opening = _text(tool_input, "opening", MIN_OPENING, problems)
    level = tool_input.get("level")
    if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 20:
        problems.append("'level' must be an integer from 1 to 20")
    party = _party(tool_input.get("party"), problems)
    notes = tool_input.get("gm_notes")
    if notes is not None and not isinstance(notes, str):
        problems.append("'gm_notes' must be a string")
    if problems:
        return _error(*problems)
    campaign: dict[str, Any] = {"setting": setting, "opening": opening, "level": level, "party": party}
    if notes and notes.strip():
        campaign["gm_notes"] = notes.strip()
    if len(setting) + len(opening) + sum(len(m["sheet"]) for m in party) + len(notes or "") > MAX_TOTAL:
        return _error("the record is too long; condense it")
    state.phase = Phase.ADVENTURE
    state.campaign = campaign
    return ToolOutcome(content="The adventure has begun.")


BEGIN_ADVENTURE = Tool(schema=SCHEMA, handler=begin_adventure, phases=frozenset({Phase.SESSION_ZERO}))
