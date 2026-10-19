from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aigm.models import SSEEvent
from aigm.session.state import GameState, Phase


@dataclass
class ToolOutcome:
    content: str
    is_error: bool = False
    event: SSEEvent | None = None
    say: str = ""  # story text the player is shown just before `event` (the narration that leads into a roll)


@dataclass
class Tool:
    schema: dict[str, Any]
    # handler(tool_use_id, tool_input, state) -> ToolOutcome. `state` is the turn's working
    # copy of the game state; a tool may change it (it only becomes real if the turn succeeds).
    handler: Callable[[str, dict[str, Any], GameState], ToolOutcome]
    phases: frozenset[Phase] = field(default_factory=lambda: frozenset(Phase))  # where it is offered
