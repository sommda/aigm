from typing import Any

from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.tools.award import AWARD
from aigm.tools.begin_adventure import BEGIN_ADVENTURE
from aigm.tools.combat import SET_COMBAT
from aigm.tools.character import UPDATE_CHARACTER
from aigm.tools.motive import SET_MOTIVE
from aigm.tools.roll_dice import ROLL_DICE
from aigm.tools.ruleset import SET_RULESET
from aigm.tools.social import SOCIAL_CHECK
from aigm.tools.story import END_STORY
from aigm.tools.structure import SET_STRUCTURE
from aigm.tools.world import ESTABLISH, RECALL, SET_SCENE

REGISTRY: dict[str, Tool] = {t.schema["name"]: t for t in (ROLL_DICE, SET_RULESET, SET_STRUCTURE, BEGIN_ADVENTURE, RECALL, ESTABLISH, SET_SCENE, UPDATE_CHARACTER, SET_COMBAT, SET_MOTIVE, SOCIAL_CHECK, AWARD, END_STORY)}


def tool_schemas(
    prompts: PromptLibrary | None = None, phase: Phase = Phase.ADVENTURE, structured: bool = False
) -> list[dict[str, Any]]:
    """Tool definitions offered to the model in a phase, with descriptions loaded from prompt files.
    A story game (`structured`) also gets the story tools and the story fields of the others."""
    prompts = prompts or PromptLibrary()
    out = []
    for name, tool in REGISTRY.items():
        if phase not in tool.phases or (tool.story_only and not structured):
            continue
        description = prompts.tool_description(name)
        input_schema = tool.schema["input_schema"]
        if structured and tool.story_properties:
            description += "\n\n" + prompts.tool_description(f"{name}_story")
            input_schema = {**input_schema, "properties": {**input_schema["properties"], **tool.story_properties}}
        out.append(
            {
                "name": name,
                "description": description,
                "input_schema": input_schema,
                **({"eager_input_streaming": True} if tool.schema.get("eager_input_streaming") else {}),
            }
        )
    return out


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
