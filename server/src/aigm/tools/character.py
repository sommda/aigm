"""The `update_character` tool: the GM records a change to a party member's sheet (docs/STATUS.md 3.3).

Like `establish` and `set_scene` it works on the turn's working copy, so a failed turn records nothing. The server only
keeps the numbers and lines; what a change means in the ruleset is the GM's business."""

from typing import Any

from aigm import story as story_rules
from aigm.characters import hp_text, living
from aigm.session.state import GameState, Phase
from aigm.sheets import REMAINS, MAX_CONDITION, MAX_CONDITIONS, MAX_HP, MAX_LINE, MAX_LINES, MAX_SECTIONS, MAX_TITLE, Section
from aigm.tools.base import Tool, ToolOutcome

SCHEMA: dict[str, Any] = {
    "name": "update_character",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The party member whose sheet changes."},
            "hp": {"type": "integer", "description": "The character's hit points now. Use this or hp_delta."},
            "hp_delta": {
                "type": "integer",
                "description": "Hit points gained (positive) or lost (negative). Use this or hp.",
            },
            "max_hp": {"type": "integer", "description": "The character's new maximum hit points, if it changed."},
            "conditions_add": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Conditions the character now has, such as poisoned or prone.",
            },
            "conditions_remove": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Conditions the character no longer has.",
            },
            "fate": {
                "type": "string",
                "enum": ["dead", "revived"],
                "description": "dead: the character has died. revived: a dead character is brought back (needs cost).",
            },
            "remains": {
                "type": "string",
                "enum": list(REMAINS),
                "description": "Where a dead character's body is: carried, left, buried or lost. The player decides.",
            },
            "cost": {"type": "string", "description": "With fate revived: one sentence on what bringing them back cost."},
            "cost_kind": {"type": "string", "enum": list(story_rules.COST_KINDS)},
            "cost_hours": {"type": "integer", "description": "With cost_kind time: the whole hours it took."},
            "section": {
                "type": "object",
                "description": "A section of the sheet to replace, or to add if there is none with that title.",
                "properties": {
                    "title": {"type": "string"},
                    "lines": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The section's complete new contents, one fact per line. An empty list removes it.",
                    },
                },
                "required": ["title", "lines"],
            },
        },
        "required": ["name"],
    },
}


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _strings(value: Any, key: str, problems: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problems.append(f"'{key}' must be a list of strings")
        return []
    return [" ".join(v.split())[:MAX_CONDITION] for v in value if v.strip()]


def _die(state: GameState, name: str, sheet: Any) -> tuple[bool, str]:
    """Mark the sheet dead. Returns (this was the last living member and the game is lost, a problem)."""
    if sheet.fate == "dead":
        return False, f"{name} is already dead"
    others = [n for n in living(state) if n != name]
    story = state.story
    if not others:
        if story is not None and story.chapter == story_rules.CHAPTERS[-1] and not story.concluded:
            ends_game = True
        else:
            return False, (
                f"{name} is the last of the party standing: the party is not wiped out by one death here. "
                "Use `defeat` for a total defeat (the party is captured, left for dead or routed), and leave this one alive"
            )
    else:
        ends_game = False
    sheet.fate, sheet.remains = "dead", None
    sheet.died_turn, sheet.died_at = state.turn, state.world.time.to_dict()
    if sheet.hp is not None:
        sheet.hp = 0
    return ends_game, ""


def _revive(state: GameState, name: str, sheet: Any, tool_input: dict[str, Any]) -> tuple[tuple[str, str, int] | None, str]:
    """Bring a dead sheet back. Returns the cost to record (kind, text, hours) in a story game, and a problem."""
    story = state.story
    if sheet.fate != "dead":
        return None, f"{name} is not dead"
    if sheet.remains == "lost":
        return None, f"{name}'s remains are lost: there is nothing to bring back"
    if story is not None and (story.fall is not None or story.concluded):
        return None, "the story is already lost: bringing someone back does not undo that"
    cost = None
    if story is not None:
        kinds = story_rules.failure_response(story).cost_kinds
        if story.chapter == 2:
            kinds = tuple(k for k in kinds if k != "time")  # a real cost, not time alone
        text, kind, hours = tool_input.get("cost"), tool_input.get("cost_kind"), tool_input.get("cost_hours") or 0
        if not isinstance(text, str) or not text.strip() or kind not in kinds:
            return None, f"bringing someone back is never free: give `cost` (one sentence) and a `cost_kind` of {', '.join(kinds)}"
        if kind == "time" and not (_int(hours) and 1 <= hours <= story_rules.MAX_COST_HOURS[story.chapter]):
            return None, "a time cost needs `cost_hours`, a whole number of hours"
        cost = (kind, text, hours if kind == "time" else 0)
    sheet.fate = sheet.remains = sheet.died_turn = sheet.died_at = None
    if sheet.hp == 0 and sheet.max_hp:
        sheet.hp = 1
    return cost, ""


def update_character(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    name = state.find_hero(str(tool_input.get("name", "")))
    if name is None:
        party = ", ".join(state.party_names) or "nobody"
        return ToolOutcome(f"{tool_input.get('name')!r} is not a party member (the party is: {party}). Nothing changed.", is_error=True)
    old = state.sheets.get(name)
    if old is None:
        return ToolOutcome(
            f"{name} has no sheet on record to update (this game began without one). Nothing changed; carry on without it.",
            is_error=True,
        )
    sheet, problems, notes = old.copy(), [], []
    fate, remains = tool_input.get("fate"), tool_input.get("remains")
    if fate not in (None, "dead", "revived"):
        problems.append("'fate' must be dead or revived")
    if remains is not None and remains not in REMAINS:
        problems.append(f"'remains' must be one of: {', '.join(REMAINS)}")
    if sheet.fate == "dead" and fate != "revived" and any(
        tool_input.get(k) is not None for k in ("hp", "hp_delta", "max_hp", "conditions_add", "conditions_remove", "section")
    ):
        problems.append(f"{name} is dead: bring them back first (fate revived), or change only their remains")

    hp, delta, new_max = tool_input.get("hp"), tool_input.get("hp_delta"), tool_input.get("max_hp")
    if hp is not None and delta is not None:
        problems.append("give 'hp' or 'hp_delta', not both")
    if any(v is not None and not _int(v) for v in (hp, delta, new_max)):
        problems.append("'hp', 'hp_delta' and 'max_hp' must be whole numbers")
        hp = delta = new_max = None
    if new_max is not None:
        if not 1 <= new_max <= MAX_HP:
            problems.append(f"'max_hp' must be from 1 to {MAX_HP}")
        else:
            had_hp = sheet.hp is not None
            sheet.max_hp = new_max
            sheet.hp = min(sheet.hp, new_max) if had_hp else new_max
    if (hp is not None or delta is not None) and not problems:
        if sheet.max_hp is None:
            problems.append(f"{name}'s sheet has no hit point maximum; give 'max_hp' as well")
        else:
            target = hp if hp is not None else (sheet.hp if sheet.hp is not None else sheet.max_hp) + delta
            sheet.hp = max(0, min(target, sheet.max_hp))
            if sheet.hp != target:
                notes.append(f"HP held at {sheet.hp} (the limits are 0 and the maximum {sheet.max_hp}).")

    add = _strings(tool_input.get("conditions_add"), "conditions_add", problems)
    remove = {c.lower() for c in _strings(tool_input.get("conditions_remove"), "conditions_remove", problems)}
    if not problems:
        kept = [c for c in sheet.conditions if c.lower() not in remove]
        missing = remove - {c.lower() for c in sheet.conditions}
        if missing:
            notes.append(f"Not on {name} to remove: {', '.join(sorted(missing))}.")
        have = {c.lower() for c in kept}
        for c in add:
            if c.lower() not in have:
                kept.append(c)
                have.add(c.lower())
        if len(kept) > MAX_CONDITIONS:
            problems.append(f"a character can have at most {MAX_CONDITIONS} conditions")
        sheet.conditions = kept

    section = tool_input.get("section")
    if section is not None:
        title = " ".join(str(section.get("title", "")).split())[:MAX_TITLE] if isinstance(section, dict) else ""
        raw = section.get("lines") if isinstance(section, dict) else None
        if not title or not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            problems.append("'section' needs a title and a list of lines (strings)")
        else:
            lines = [t for t in (" ".join(x.split())[:MAX_LINE] for x in raw) if t]
            if len(lines) > MAX_LINES:
                problems.append(f"a section can have at most {MAX_LINES} lines")
            at = next((i for i, s in enumerate(sheet.sections) if s.title.lower() == title.lower()), None)
            if not lines and at is not None:
                del sheet.sections[at]
            elif lines and at is not None:
                sheet.sections[at].lines = lines
            elif lines:
                if len(sheet.sections) >= MAX_SECTIONS:
                    problems.append(f"a sheet can have at most {MAX_SECTIONS} sections; replace one")
                else:
                    sheet.sections.append(Section(title, lines))
    if all(tool_input.get(k) is None for k in ("hp", "hp_delta", "max_hp", "conditions_add", "conditions_remove", "section", "fate", "remains")):
        problems.append("nothing to change: give hp, hp_delta, max_hp, conditions_add, conditions_remove, section, fate or remains")
    story = state.story
    revive_cost: tuple[str, str, int] | None = None
    ends_game = False
    if not problems and fate == "dead":
        ends_game, why = _die(state, name, sheet)
        if why:
            problems.append(why)
    if not problems and fate == "revived":
        revive_cost, why = _revive(state, name, sheet, tool_input)
        if why:
            problems.append(why)
    if not problems and remains is not None:
        if sheet.fate != "dead":
            problems.append(f"{name} is not dead, so there are no remains to settle")
        elif fate == "revived":
            problems.append("a character brought back has no remains")
        else:
            sheet.remains = remains
    if problems:
        return ToolOutcome(f"{name}'s sheet was not changed:\n- " + "\n- ".join(problems), is_error=True)
    state.sheets[name] = sheet
    if story is not None and fate in ("dead", "revived"):
        word = "fell" if fate == "dead" else "was brought back"
        story.choices = [*story.choices, {"turn": state.turn, "milestone": "", "note": f"{name} {word} ({state.world.time})."}][
            -story_rules.MAX_CHOICES :
        ]
    if revive_cost is not None and story is not None:
        kind, text, hours = revive_cost
        story_rules.record_cost(story, state.turn, "", kind, text, hours)
        if hours:
            state.world.advance_minutes(hours * 60, reported=True, turn=state.turn, why=f"bringing {name} back: {text}")
            notes.append(f"The clock moves on {hours} hours; narrate what filled them.")
    if ends_game and story is not None:
        story_rules.lose(story, state.turn, f"the last of the party, {name}, has fallen")
        notes.append("That was the last of the party: the story is lost. Finish the scene, then play out its ending.")
    elif fate == "dead":
        notes.append(f"{name} is dead. Put the choice of what to do with the body to the player (remains).")
    now = [f"HP {hp_text(sheet.hp, sheet.max_hp)}" if hp_text(sheet.hp, sheet.max_hp) else "", f"conditions: {', '.join(sheet.conditions) or 'none'}"]
    return ToolOutcome(f"{name}: {'; '.join(x for x in now if x)}." + "".join(f" {n}" for n in notes))


UPDATE_CHARACTER = Tool(schema=SCHEMA, handler=update_character, phases=frozenset({Phase.ADVENTURE}))
