"""The `set_combat` tool: the GM keeps the status page's table of a fight up to date (docs/STATUS.md 4)."""

from typing import Any

from aigm.combat import ALLY, FOE, HEALTH_WORDS, MAX_COMBATANTS, MAX_CONDITION, MAX_CONDITIONS, MAX_COUNT, MAX_HEALTH, MAX_NAME, SIDES, Combat, Combatant
from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.tools.timing import read_minutes, spend

FIGHT_MINUTES = 10  # a fight takes more than its rounds (docs/TIME.md 6)

SCHEMA: dict[str, Any] = {
    "name": "set_combat",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "update", "end"]},
            "minutes": {
                "type": "integer",
                "description": "With action end: how long the fight took in minutes. 10 if you leave it out.",
            },
            "combatants": {
                "type": "array",
                "description": "For start: everyone in the fight except the party. For update: only the ones that change.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "side": {"type": "string", "enum": list(SIDES)},
                        "count": {"type": "integer", "description": "How many, for a group (a pack of four wolves is one entry with count 4)."},
                        "health": {"type": "string"},
                        "conditions": {"type": "array", "items": {"type": "string"}},
                        "remove": {"type": "boolean", "description": "Update only: take this one out of the list (fled, killed and cleared away)."},
                    },
                    "required": ["name"],
                },
            },
        },
        "required": ["action"],
    },
}


def _health(value: Any, side: str, problems: list[str], name: str) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).lower().split()) if side == FOE else " ".join(str(value).split())
    if side == FOE and text not in HEALTH_WORDS:
        problems.append(f"{name}: a foe's health is one of {', '.join(HEALTH_WORDS)} (the player is not told a monster's numbers)")
        return None
    if len(text) > MAX_HEALTH:
        problems.append(f"{name}: health is at most {MAX_HEALTH} characters")
        return None
    return text


def _fields(row: dict[str, Any], side: str, problems: list[str]) -> dict[str, Any]:
    """The checked fields a row sets."""
    name, out = str(row.get("name", "")), {}
    count = row.get("count")
    if count is not None:
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_COUNT:
            problems.append(f"{name}: count must be a whole number from 1 to {MAX_COUNT}")
        else:
            out["count"] = count
    health = _health(row.get("health"), side, problems, name)
    if health is not None:
        out["health"] = health
    conditions = row.get("conditions")
    if conditions is not None:
        if not isinstance(conditions, list) or not all(isinstance(c, str) for c in conditions):
            problems.append(f"{name}: conditions must be a list of strings")
        else:
            out["conditions"] = [c for c in dict.fromkeys(" ".join(c.split())[:MAX_CONDITION] for c in conditions) if c][:MAX_CONDITIONS]
    return out


def _row(raw: Any, problems: list[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"].strip():
        problems.append("every combatant needs a name")
        return None
    return raw


def set_combat(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    action, rows, problems = tool_input.get("action"), tool_input.get("combatants"), []
    if action == "end":
        minutes, problem = read_minutes(tool_input)
        if problem:
            return ToolOutcome(f"{problem[0].upper()}{problem[1:]}. Nothing changed.", is_error=True)
        had = state.combat is not None
        state.combat = None
        if not had:
            return ToolOutcome("There was no fight recorded.")
        passed = spend(state, FIGHT_MINUTES if minutes is None else minutes, "the fight")
        return ToolOutcome("The fight is over." + (f" {passed}" if passed else ""))
    if action not in ("start", "update"):
        return ToolOutcome("'action' must be start, update or end. Nothing changed.", is_error=True)
    if action == "update" and state.combat is None:
        return ToolOutcome("There is no fight recorded; use action 'start' first. Nothing changed.", is_error=True)
    if not isinstance(rows, list) or (action == "start" and not rows):
        return ToolOutcome("'combatants' must be a list" + (" with at least one entry" if action == "start" else "") + ". Nothing changed.", is_error=True)
    combat = Combat() if action == "start" else state.combat.copy()
    for raw in rows:
        row = _row(raw, problems)
        if row is None:
            continue
        name = " ".join(row["name"].split())[:MAX_NAME]
        if state.find_hero(name):
            problems.append(f"{name} is a party member: the party is part of the fight already")
            continue
        existing = combat.find(name)
        if action == "update" and row.get("remove") is True:
            if existing is None:
                problems.append(f"{name} is not in the fight")
            else:
                combat.combatants.remove(existing)
            continue
        side = row.get("side", existing.side if existing else None)
        if side not in SIDES:
            problems.append(f"{name}: side must be 'foe' or 'ally'")
            continue
        fields = _fields(row, side, problems)
        if existing is None:
            combat.combatants.append(Combatant(name, side, **fields))
        else:
            existing.side = side
            for key, value in fields.items():
                setattr(existing, key, value)
            if side == FOE and existing.health not in HEALTH_WORDS:
                existing.health = "unhurt"  # an ally that turned foe loses its numbers
    if len(combat.combatants) > MAX_COMBATANTS:
        problems.append(f"at most {MAX_COMBATANTS} combatants; group them with 'count'")
    if problems:
        return ToolOutcome("The fight was not changed:\n- " + "\n- ".join(problems), is_error=True)
    state.combat = combat if combat.combatants else None
    listing = ", ".join(f"{c.label} ({c.health})" for c in combat.combatants) or "nobody left"
    return ToolOutcome(f"Fight: {listing}.")


SET_COMBAT = Tool(schema=SCHEMA, handler=set_combat, phases=frozenset({Phase.ADVENTURE}))
