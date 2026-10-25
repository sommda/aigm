"""The `update_character` tool: the GM records a change to a party member's sheet (docs/STATUS.md 3.3).

Like `establish` and `set_scene` it works on the turn's working copy, so a failed turn records nothing. The server only
keeps the numbers and lines; what a change means in the ruleset is the GM's business."""

from typing import Any

from aigm.characters import hp_text
from aigm.session.state import GameState, Phase
from aigm.sheets import MAX_CONDITION, MAX_CONDITIONS, MAX_HP, MAX_LINE, MAX_LINES, MAX_SECTIONS, MAX_TITLE, Section
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
    if all(tool_input.get(k) is None for k in ("hp", "hp_delta", "max_hp", "conditions_add", "conditions_remove", "section")):
        problems.append("nothing to change: give hp, hp_delta, max_hp, conditions_add, conditions_remove or section")
    if problems:
        return ToolOutcome(f"{name}'s sheet was not changed:\n- " + "\n- ".join(problems), is_error=True)
    state.sheets[name] = sheet
    now = [f"HP {hp_text(sheet.hp, sheet.max_hp)}" if hp_text(sheet.hp, sheet.max_hp) else "", f"conditions: {', '.join(sheet.conditions) or 'none'}"]
    return ToolOutcome(f"{name}: {'; '.join(x for x in now if x)}." + "".join(f" {n}" for n in notes))


UPDATE_CHARACTER = Tool(schema=SCHEMA, handler=update_character, phases=frozenset({Phase.ADVENTURE}))
