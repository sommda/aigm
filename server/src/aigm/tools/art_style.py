"""The `set_art_style` tool: Session 0 only. Picks the art style of the characters' portraits (docs/PORTRAITS.md 5.2)."""

from typing import Any

from aigm import art, rulesets
from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome

DEFAULT = "default"  # go back to the style that suits the ruleset

# The description is a prompt: it lives in prompts/tools/set_art_style.md.
SCHEMA: dict[str, Any] = {
    "name": "set_art_style",
    "input_schema": {
        "type": "object",
        "properties": {
            "style": {
                "type": "string",
                "enum": [*(s.id for s in art.STYLES), art.NO_PORTRAITS, DEFAULT],
                "description": "The style id. " + "; ".join(f"{s.id} = {s.name}" for s in art.STYLES)
                + f"; {art.NO_PORTRAITS} = no portraits; {DEFAULT} = the style that suits the chosen ruleset.",
            }
        },
        "required": ["style"],
    },
}


def set_art_style(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    if state.phase is not Phase.SESSION_ZERO:
        return ToolOutcome(content="The art style cannot be changed once the adventure has begun.", is_error=True)
    wanted = str(tool_input.get("style"))
    if wanted == DEFAULT:
        state.art_style = None
    elif wanted == art.NO_PORTRAITS or wanted in art.BY_ID:
        state.art_style = wanted
    else:
        return ToolOutcome(
            content="Unknown art style. Choose one of: " + ", ".join([*art.BY_ID, art.NO_PORTRAITS, DEFAULT]),
            is_error=True,
        )
    style = art.resolve_style(state.art_style, state.ruleset)
    if style is None:
        return ToolOutcome(content="The game will have no character portraits.")
    note = f" (the default for {rulesets.get(state.ruleset).short})" if state.art_style is None else ""
    return ToolOutcome(content=f"Portraits will use the {style.name} style{note}. It is final once the adventure begins.")


SET_ART_STYLE = Tool(schema=SCHEMA, handler=set_art_style, phases=frozenset({Phase.SESSION_ZERO}), needs_art=True)
