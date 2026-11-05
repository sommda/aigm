"""The `pass_time` tool: time passes with no roll, or a roll's result forces more of it (docs/TIME.md 4.2). The
description is a prompt: prompts/tools/pass_time.md."""

from typing import Any

from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.tools.timing import MAX_ACTION_MINUTES, read_minutes, spend

MIN_REASON_CHARS = 3
MAX_REASON_CHARS = 120

SCHEMA: dict[str, Any] = {
    "name": "pass_time",
    "input_schema": {
        "type": "object",
        "properties": {
            "minutes": {
                "type": "integer",
                "description": f"Whole minutes that pass, from 1 to {MAX_ACTION_MINUTES} (a day).",
            },
            "reason": {"type": "string", "description": "One line on what the time is spent on."},
        },
        "required": ["minutes", "reason"],
    },
}


def pass_time(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    minutes, problem = read_minutes(tool_input)
    reason = tool_input.get("reason")
    problems = [problem] if problem else []
    if minutes is None and not problem:
        problems.append("`minutes` is required")
    elif minutes == 0:
        problems.append("`minutes` must be at least 1; do not call this for a moment")
    if not isinstance(reason, str) or not MIN_REASON_CHARS <= len(reason.strip()) <= MAX_REASON_CHARS:
        problems.append(f"`reason` must be a line of {MIN_REASON_CHARS} to {MAX_REASON_CHARS} characters")
    if problems:
        return ToolOutcome("No time passed: " + "; ".join(problems) + ".", is_error=True)
    assert minutes is not None and isinstance(reason, str)
    return ToolOutcome(spend(state, minutes, reason.strip()))


PASS_TIME = Tool(schema=SCHEMA, handler=pass_time, phases=frozenset({Phase.ADVENTURE}))
