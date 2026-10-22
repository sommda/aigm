"""The `award` tool: the party earns experience points or gains a level (docs/PROGRESSION.md).

The server keeps the totals (`GameState.level` and `xp`) and tells the player; the GM decides what is earned and,
under the ruleset's own tables, when a level is reached. Descriptions live in prompts/tools/award.md."""

from typing import Any

from aigm.models import Award
from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome

MAX_LEVEL = 20
MAX_XP_AWARD = 1_000_000
MAX_REASON = 160

SCHEMA: dict[str, Any] = {
    "name": "award",
    "input_schema": {
        "type": "object",
        "properties": {
            "xp": {"type": "integer", "description": "Experience points earned by the whole party, if any."},
            "level": {
                "type": "integer",
                "description": "The party's new level, one above its current level, when it has just gained one.",
            },
            "reason": {"type": "string", "description": "What earned it, in a few words (a defeated foe, a quest)."},
        },
        "required": ["reason"],
    },
}


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def award(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    xp, level = tool_input.get("xp"), tool_input.get("level")
    reason = tool_input.get("reason")
    problems = []
    if xp is not None and (_int(xp) is None or not 0 <= xp <= MAX_XP_AWARD):
        problems.append(f"'xp' must be an integer from 0 to {MAX_XP_AWARD}")
    if level is not None and (_int(level) is None or not state.party_level < level <= min(MAX_LEVEL, state.party_level + 1)):
        problems.append(
            f"'level' must be the next level, {state.party_level + 1} (the party is level {state.party_level}); "
            "award one level at a time"
            if state.party_level < MAX_LEVEL
            else "the party is already at the highest level"
        )
    if not isinstance(reason, str) or not reason.strip():
        problems.append("'reason' must say what earned it")
    if not xp and level is None and not problems:
        problems.append("give 'xp', 'level' or both")
    if problems:
        return ToolOutcome(content="Nothing was awarded: " + "; ".join(problems) + ".", is_error=True)
    previous = state.party_level
    gained = xp or 0
    state.xp += gained
    state.level = level if level is not None else previous
    event = Award(
        tool_use_id=tool_use_id,
        xp_gained=gained,
        xp=state.xp,
        level=state.level,
        previous_level=previous,
        reason=reason.strip()[:MAX_REASON],
    )
    parts = ([f"+{gained} XP, total {state.xp}"] if gained else []) + (
        [f"the party is now level {state.level}: update every character sheet"] if state.level != previous else []
    )
    return ToolOutcome(content="Awarded: " + "; ".join(parts) + ". The player has been told.", event=event)


AWARD = Tool(schema=SCHEMA, handler=award, phases=frozenset({Phase.ADVENTURE}))
