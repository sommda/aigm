"""The `set_ruleset` tool: Session 0 only. Picks the rules the game is played under (docs/RULESETS.md)."""

from typing import Any

from aigm.rulesets import BY_ID, RULESETS
from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome

# The description is a prompt: it lives in prompts/tools/set_ruleset.md.
SCHEMA: dict[str, Any] = {
    "name": "set_ruleset",
    "input_schema": {
        "type": "object",
        "properties": {
            "ruleset": {
                "type": "string",
                "enum": [r.id for r in RULESETS],
                "description": "The ruleset id. " + "; ".join(f"{r.id} = {r.name}, {r.year}" for r in RULESETS) + ".",
            }
        },
        "required": ["ruleset"],
    },
}


def set_ruleset(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    if state.phase is not Phase.SESSION_ZERO:
        return ToolOutcome(content="The ruleset cannot be changed once the adventure has begun.", is_error=True)
    ruleset = BY_ID.get(str(tool_input.get("ruleset")))
    if ruleset is None:
        return ToolOutcome(content="Unknown ruleset. Choose one of: " + ", ".join(BY_ID), is_error=True)
    if ruleset.id == state.ruleset:
        return ToolOutcome(content=f"The game already uses {ruleset.name}; nothing changed.")
    state.ruleset = ruleset.id
    return ToolOutcome(
        content=f"The game now uses {ruleset.name}. Its rules and period feel replace the previous ruleset's in "
        "your instructions from now on. Any character already built under another ruleset must be rebuilt for this one."
    )


SET_RULESET = Tool(schema=SCHEMA, handler=set_ruleset, phases=frozenset({Phase.SESSION_ZERO}))
