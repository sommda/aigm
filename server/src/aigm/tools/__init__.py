from typing import Any

from aigm.prompts import PromptLibrary
from aigm.tools.base import Tool, ToolOutcome
from aigm.tools.roll_dice import ROLL_DICE

REGISTRY: dict[str, Tool] = {ROLL_DICE.schema["name"]: ROLL_DICE}


def tool_schemas(prompts: PromptLibrary | None = None) -> list[dict[str, Any]]:
    """Tool definitions as sent to the model, with descriptions loaded from prompt files."""
    prompts = prompts or PromptLibrary()
    return [
        {"name": name, "description": prompts.tool_description(name), "input_schema": tool.schema["input_schema"]}
        for name, tool in REGISTRY.items()
    ]


def dispatch(name: str, tool_use_id: str, tool_input: dict[str, Any]) -> ToolOutcome:
    tool = REGISTRY.get(name)
    if tool is None:
        return ToolOutcome(content=f"Unknown tool {name!r}", is_error=True)
    try:
        return tool.handler(tool_use_id, tool_input)
    except Exception as exc:
        return ToolOutcome(content=f"Tool {name!r} failed: {type(exc).__name__}", is_error=True)
