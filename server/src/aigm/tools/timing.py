"""Time that passes inside a tool call (docs/TIME.md 4): a roll's `minutes`, a fight's end, `pass_time`."""

from typing import Any

from aigm.session.state import GameState, Phase
from aigm.world.model import duration_text

MAX_ACTION_MINUTES = 24 * 60  # one call; longer stretches belong to `set_scene`

MINUTES_PROPERTY: dict[str, Any] = {
    "type": "integer",
    "description": (
        "Minutes the action being tested takes (a lock 10, a search of a room 30, a hard climb 60). Leave it out "
        "for a moment, and for a damage roll or any roll that only follows another."
    ),
}


def read_minutes(tool_input: dict[str, Any], key: str = "minutes") -> tuple[int | None, str | None]:
    """The `minutes` argument: (value or None when absent, a problem message or None)."""
    raw = tool_input.get(key)
    if raw is None:
        return None, None
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= MAX_ACTION_MINUTES:
        return None, f"`{key}` must be a whole number of minutes from 0 to {MAX_ACTION_MINUTES}"
    return raw, None


def spend(state: GameState | None, minutes: int | None, why: str) -> str:
    """Move the clock on the turn's working copy and say so; "" when there is nothing to do (no minutes, no state, or
    not the adventure)."""
    if not minutes or state is None or state.phase is not Phase.ADVENTURE:
        return ""
    world = state.world.copy()
    world.advance_minutes(minutes, reported=True, turn=state.turn, why=why)
    state.world = world
    return f"{duration_text(minutes).capitalize()} pass. It is now {world.time.rounded(5)}."
