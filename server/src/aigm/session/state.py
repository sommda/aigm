"""Per-session game state: the mode the game is in, plus what Session 0 established."""

import copy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from aigm.errors import CorruptSave


class Phase(StrEnum):
    SESSION_ZERO = "session_zero"  # establishing the setting and the party
    ADVENTURE = "adventure"  # the real game


@dataclass
class GameState:
    """What the save file and the live session carry besides the message history.

    `campaign` is filled in by the `begin_adventure` tool at the end of Session 0 and holds
    the keys `setting`, `party`, `party_size`, `level` and (optionally) `gm_notes`."""

    phase: Phase = Phase.SESSION_ZERO
    campaign: dict[str, Any] | None = None

    def copy(self) -> "GameState":
        return GameState(self.phase, copy.deepcopy(self.campaign))

    def to_dict(self) -> dict[str, Any]:
        return {"phase": self.phase.value, "campaign": self.campaign}

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
        return cls(phase, campaign)
