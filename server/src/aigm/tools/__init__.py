from typing import Any

from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.tools.begin_adventure import BEGIN_ADVENTURE
from aigm.tools.roll_dice import ROLL_DICE

REGISTRY: dict[str, Tool] = {t.schema["name"]: t for t in (ROLL_DICE, BEGIN_ADVENTURE)}


def tool_schemas(prompts: PromptLibrary | None = None, phase: Phase = Phase.ADVENTURE) -> list[dict[str, Any]]:
    """Tool definitions offered to the model in a phase, with descriptions loaded from prompt files."""
    prompts = prompts or PromptLibrary()
    return [
        {"name": name, "description": prompts.tool_description(name), "input_schema": tool.schema["input_schema"]}
        for name, tool in REGISTRY.items()
        if phase in tool.phases
    ]


def dispatch(name: str, tool_use_id: str, tool_input: dict[str, Any], state: GameState | None = None) -> ToolOutcome:
    """Run a tool. Tools not offered in the state's phase are treated as unknown."""
    state = state or GameState(Phase.ADVENTURE)
    tool = REGISTRY.get(name)
    if tool is None or state.phase not in tool.phases:
        return ToolOutcome(content=f"Unknown tool {name!r}", is_error=True)
    try:
        return tool.handler(tool_use_id, tool_input, state)
    except Exception as exc:
        return ToolOutcome(content=f"Tool {name!r} failed: {type(exc).__name__}", is_error=True)
