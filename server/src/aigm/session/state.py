"""Per-session game state: the mode the game is in, plus what Session 0 established."""

import copy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from aigm.errors import CorruptSave
from aigm.world import World


class Phase(StrEnum):
    SESSION_ZERO = "session_zero"  # establishing the setting and the party
    ADVENTURE = "adventure"  # the real game


@dataclass
class GameState:
    """What the save file and the live session carry besides the message history.

    `campaign` is filled in by the `begin_adventure` tool at the end of Session 0 and holds
    the keys `setting`, `party`, `party_size`, `level` and (optionally) `gm_notes`. `world` is
    the persistent knowledge base (docs/WORLD.md); it stays empty in Session 0."""

    phase: Phase = Phase.SESSION_ZERO
    campaign: dict[str, Any] | None = None
    world: World = field(default_factory=World)
    # The current turn number (player messages so far, including this one), set by the turn loop. Not saved: facts record it.
    turn: int = field(default=0, compare=False)
    # Set when the GM looked up something unrecorded: ask for a curator pass soon. Not saved.
    pass_requested: bool = field(default=False, compare=False)

    def copy(self) -> "GameState":
        return GameState(self.phase, copy.deepcopy(self.campaign), self.world.copy(), self.turn, self.pass_requested)

    def to_dict(self) -> dict[str, Any]:
        return {"phase": self.phase.value, "campaign": self.campaign, "world": self.world.to_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GameState":
        """Read a save file. Saves from before game state existed were all mid-adventure."""
        if "phase" not in data:
            return cls(Phase.ADVENTURE, None)
        try:
            phase = Phase(data["phase"])
        except ValueError:
            raise CorruptSave(f"unknown game phase {data['phase']!r}") from None
        campaign = data.get("campaign")
        if campaign is not None and not isinstance(campaign, dict):
            raise CorruptSave("campaign must be an object or null")
        if phase is Phase.SESSION_ZERO and campaign is not None:
            raise CorruptSave("a session_zero save cannot have a campaign")
        world = World.from_dict(data.get("world"))  # saves before version 3 have none
        if phase is Phase.SESSION_ZERO and not world.is_empty:
            raise CorruptSave("a session_zero save cannot have a world")
        return cls(phase, campaign, world)
