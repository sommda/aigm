"""The `set_structure` tool: Session 0 only. Picks endless play or a story of some length (docs/STORY.md 4)."""

from typing import Any

from aigm.session.state import GameState, Phase
from aigm.story import ENDLESS, STRUCTURES
from aigm.tools.base import Tool, ToolOutcome

# The description is a prompt: it lives in prompts/tools/set_structure.md.
SCHEMA: dict[str, Any] = {
    "name": "set_structure",
    "input_schema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": list(STRUCTURES),
                "description": "endless = no planned story, it emerges from play; short, medium or long = a story "
                "with a beginning, middle and end, of that length.",
            }
        },
        "required": ["mode"],
    },
}

SAID = {
    ENDLESS: "an endless campaign: no planned story or ending; the story emerges from what the player does",
    "short": "a short story with a beginning, middle and end, meant to be finished in a session or two",
    "medium": "a medium-length story with a beginning, middle and end",
    "long": "a long story with a beginning, middle and end and a winding path to its goal",
}


def set_structure(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    if state.phase is not Phase.SESSION_ZERO:
        return ToolOutcome(content="The kind of game cannot be changed once the adventure has begun.", is_error=True)
    mode = tool_input.get("mode")
    if mode not in STRUCTURES:
        return ToolOutcome(content="Unknown mode. Choose one of: " + ", ".join(STRUCTURES), is_error=True)
    if mode == state.structure:
        return ToolOutcome(content=f"The game is already {SAID[mode]}; nothing changed.")
    state.structure = mode
    return ToolOutcome(
        content=f"The game will be {SAID[mode]}."
        + ("" if mode == ENDLESS else " The story is planned in secret once the adventure begins; do not plan it now.")
    )


SET_STRUCTURE = Tool(schema=SCHEMA, handler=set_structure, phases=frozenset({Phase.SESSION_ZERO}))
