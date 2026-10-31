from typing import Any

from aigm.session.state import GameState, Hero, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.world.independence import independence_problem

MAX_PARTY_SIZE = 6
MIN_SETTING = 300  # characters; a few sentences of real detail
MIN_OPENING = 100
MIN_SHEET = 150  # per character
MIN_BACKGROUND = 80  # per character; origin, reputation, ties
MIN_APPEARANCE = 60  # per character; how they look (docs/LOOKS.md 4.1)
MAX_KEY_CHARACTERS = 8
MAX_STARTING_ITEMS = 4
MAX_ITEM_NOTE_WORDS = 30
MAX_ROLE_WORDS = 40
MIN_ROLE_WORDS = 3
MAX_TOTAL = 30_000
MAX_XP = 100_000_000

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
                        "xp": {
                            "type": "integer",
                            "description": "The experience points this character starts with: the lowest total for their starting level in the chosen ruleset's advancement table, for their class (0 at level 1, and 0 under milestone leveling).",
                        },
                        "background": {
                            "type": "string",
                            "description": f"The character's life before the adventure (at least {MIN_BACKGROUND} characters): where they come from and what they did, their reputation or nickname, the people and places that know them, and which parts of the setting they know well, know only by hearsay, or do not know at all.",
                        },
                        "appearance": {
                            "type": "string",
                            "description": f"How the character looks (at least {MIN_APPEARANCE} characters): apparent age, build, coloring, hair, face, notable features and usual clothing, exactly as the player chose or approved. Only what anyone could see.",
                        },
                    },
                    "required": ["name", "sheet", "background", "appearance"],
                },
            },
            "characters": {
                "type": "array",
                "description": f"Optional: the key people of the setting that you and the player created in Session 0 (a patron, a rival, a companion, the villain), at most {MAX_KEY_CHARACTERS}. They are not party members. Do not list the player characters here.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {
                            "type": "string",
                            "description": "One sentence about who they are, using their name, as a fact about the world: 'Harlan Voss is the Thorn Guild's tax collector in Ashby.'",
                        },
                        "appearance": {
                            "type": "string",
                            "description": "How they look, if it was decided or discussed (what anyone could see). Leave it out to have it written for you.",
                        },
                        "known": {
                            "type": "boolean",
                            "description": "True if the player has already been told about this person in Session 0; false if they are a secret the player has not met or heard of.",
                        },
                    },
                    "required": ["name", "role", "known"],
                },
            },
            "key_items": {
                "type": "array",
                "description": f"Optional: quest objects the party has or knows of from the start (docs/KEY_ITEMS.md), at most {MAX_STARTING_ITEMS}: a map of the dungeon given in advance, a letter of introduction, a key left to them. Never ordinary gear (that goes on the character sheets) and never an item the player has not been told about.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "What the characters call it: 'the old mine map'."},
                        "appearance": {
                            "type": "string",
                            "description": f"What it is and looks like, as a phrase completing 'It is ...' (2 to {MAX_ITEM_NOTE_WORDS} words): 'a creased sheet of vellum with a hand-drawn plan of the mine'.",
                        },
                        "purpose": {
                            "type": "string",
                            "description": "Optional: one sentence using its name that says what it is for, as the party understands it.",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["held", "known"],
                            "description": "held: the party has it now. known: the party knows it exists and is looking for it.",
                        },
                    },
                    "required": ["name", "appearance", "status"],
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


def _party(raw: Any, problems: list[str]) -> list[dict[str, Any]]:
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
        background = member.get("background")
        if not isinstance(background, str) or len(background.strip()) < MIN_BACKGROUND:
            problems.append(
                f"{label}: 'background' is too thin (at least {MIN_BACKGROUND} characters; give where they come "
                "from, who knows them, and what they know of the setting)"
            )
        appearance = member.get("appearance")
        if not isinstance(appearance, str) or len(appearance.strip()) < MIN_APPEARANCE:
            problems.append(
                f"{label}: 'appearance' is too thin (at least {MIN_APPEARANCE} characters; give age, build, "
                "coloring, hair, face, notable features and usual clothing, as the player chose or approved)"
            )
        xp = member.get("xp", 0)
        if xp is None:
            xp = 0
        if isinstance(xp, bool) or not isinstance(xp, int) or not 0 <= xp <= MAX_XP:
            problems.append(f"{label}: 'xp' must be a whole number from 0 to {MAX_XP}")
            xp = 0
        party.append(
            {
                "xp": xp,
                "name": name.strip() if isinstance(name, str) else "",
                "sheet": sheet.strip() if isinstance(sheet, str) else "",
                "background": background.strip() if isinstance(background, str) else "",
                "appearance": appearance.strip() if isinstance(appearance, str) else "",
            }
        )
    return party


def _characters(raw: Any, party: list[dict[str, Any]], problems: list[str]) -> list[dict[str, Any]]:
    """The key people made in Session 0 (docs/LOOKS.md 4.1)."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_KEY_CHARACTERS:
        problems.append(f"'characters' must be a list of at most {MAX_KEY_CHARACTERS} people")
        return []
    taken = {m["name"].lower() for m in party}
    out = []
    for i, entry in enumerate(raw, 1):
        if not isinstance(entry, dict):
            problems.append(f"key character {i} must be an object with name, role and known")
            continue
        name, role = entry.get("name"), entry.get("role")
        label = f"key character {i}" + (f" ({name})" if isinstance(name, str) and name.strip() else "")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"{label}: 'name' must be a non-empty string")
            continue
        if name.strip().lower() in taken:
            problems.append(f"{label}: the name is already used by a party member or another key character")
        taken.add(name.strip().lower())
        words = len(role.split()) if isinstance(role, str) else 0
        if not MIN_ROLE_WORDS <= words <= MAX_ROLE_WORDS or name.strip().lower() not in role.lower():
            problems.append(
                f"{label}: 'role' must be one sentence of {MIN_ROLE_WORDS} to {MAX_ROLE_WORDS} words that uses "
                "their name, such as 'Harlan Voss is the Thorn Guild's tax collector in Ashby.'"
            )
        if isinstance(role, str) and (why := independence_problem(role, [m["name"] for m in party])):
            problems.append(f"{label}: 'role' {why}; write it as a fact about the world")
        known = entry.get("known")
        if not isinstance(known, bool):
            problems.append(f"{label}: 'known' must be true or false")
        appearance = entry.get("appearance")
        if appearance is not None and not isinstance(appearance, str):
            problems.append(f"{label}: 'appearance' must be a string")
        out.append(
            {
                "name": name.strip(),
                "role": role.strip() if isinstance(role, str) else "",
                "known": known is True,
                "appearance": appearance.strip() if isinstance(appearance, str) else "",
            }
        )
    return out


def _key_items(raw: Any, taken: set[str], problems: list[str]) -> list[dict[str, str]]:
    """The key items the party starts with or knows of (docs/KEY_ITEMS.md 5.3)."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_STARTING_ITEMS:
        problems.append(f"'key_items' must be a list of at most {MAX_STARTING_ITEMS} items")
        return []
    out = []
    for i, entry in enumerate(raw, 1):
        if not isinstance(entry, dict):
            problems.append(f"key item {i} must be an object with name, appearance and status")
            continue
        name, appearance, purpose, status = (entry.get(k) for k in ("name", "appearance", "purpose", "status"))
        label = f"key item {i}" + (f" ({name})" if isinstance(name, str) and name.strip() else "")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"{label}: 'name' must be a non-empty string")
            continue
        if name.strip().lower() in taken:
            problems.append(f"{label}: the name is already used by a party member, key character or key item")
        taken.add(name.strip().lower())
        words = len(appearance.split()) if isinstance(appearance, str) else 0
        if not 2 <= words <= MAX_ITEM_NOTE_WORDS:
            problems.append(f"{label}: 'appearance' must be a phrase of 2 to {MAX_ITEM_NOTE_WORDS} words saying what it looks like")
        if status not in ("held", "known"):
            problems.append(f"{label}: 'status' must be held or known")
        if purpose is not None and (not isinstance(purpose, str) or len(purpose.split()) < 3):
            problems.append(f"{label}: 'purpose' must be a sentence about what it is for")
        out.append(
            {
                "name": name.strip(),
                "appearance": " ".join(appearance.split()) if isinstance(appearance, str) else "",
                "purpose": " ".join(purpose.split()) if isinstance(purpose, str) else "",
                "status": status if status in ("held", "known") else "held",
            }
        )
    return out


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
    characters = _characters(tool_input.get("characters"), party, problems)
    taken = {m["name"].lower() for m in party} | {c["name"].lower() for c in characters}
    key_items = _key_items(tool_input.get("key_items"), taken, problems)
    notes = tool_input.get("gm_notes")
    if notes is not None and not isinstance(notes, str):
        problems.append("'gm_notes' must be a string")
    if problems:
        return _error(*problems)
    xp = {m["name"]: m.pop("xp") for m in party}  # starting experience belongs to the heroes, not to the record
    campaign: dict[str, Any] = {"setting": setting, "opening": opening, "level": level, "party": party}
    if characters:
        campaign["characters"] = characters
    if key_items:
        campaign["key_items"] = key_items
    if notes and notes.strip():
        campaign["gm_notes"] = notes.strip()
    size = sum(len(m["sheet"]) + len(m["background"]) + len(m["appearance"]) for m in party)
    size += sum(len(c["role"]) + len(c["appearance"]) for c in characters)
    size += sum(len(i["appearance"]) + len(i["purpose"]) for i in key_items)
    if len(setting) + len(opening) + size + len(notes or "") > MAX_TOTAL:
        return _error("the record is too long; condense it")
    state.phase = Phase.ADVENTURE
    state.campaign = campaign
    state.heroes = {name: Hero(level, points) for name, points in xp.items() if points}
    return ToolOutcome(content="The adventure has begun.")


BEGIN_ADVENTURE = Tool(schema=SCHEMA, handler=begin_adventure, phases=frozenset({Phase.SESSION_ZERO}))
