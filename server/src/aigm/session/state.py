"""Per-session game state: the mode the game is in, plus what Session 0 established."""

import copy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from aigm.errors import CorruptSave
from aigm.rulesets import BY_ID, DEFAULT_RULESET
from aigm.story import ENDLESS, STRUCTURES, Story
from aigm.world import World


class Phase(StrEnum):
    SESSION_ZERO = "session_zero"  # establishing the setting and the party
    ADVENTURE = "adventure"  # the real game


MAX_CHARACTER_LEVEL = 40  # a character's overall level can be the total of several classes


@dataclass
class Hero:
    """One party member's advancement. A level belongs to a class, and a character may have several, each at its own
    level; the overall level is whatever the ruleset makes of them. How much XP a level takes, and whether a new level
    goes to the same class or another, depend on the character and the ruleset, so the GM decides; the server keeps
    the numbers."""

    level: int  # the character's overall level, which the GM works out by the ruleset (a total, or the highest)
    xp: int = 0
    classes: dict[str, int] = field(default_factory=dict)  # level in each class the GM has recorded


def _read_heroes(raw: Any) -> dict[str, Hero]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CorruptSave("heroes must be an object")
    out = {}
    for name, h in raw.items():
        level, xp = (h.get("level"), h.get("xp")) if isinstance(h, dict) else (None, None)
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= MAX_CHARACTER_LEVEL:
            raise CorruptSave(f"the level of {name!r} must be an integer from 1 to {MAX_CHARACTER_LEVEL}")
        if isinstance(xp, bool) or not isinstance(xp, int) or xp < 0:
            raise CorruptSave(f"the XP of {name!r} must be a non-negative integer")
        classes = h.get("classes", {})
        if not isinstance(classes, dict) or not all(
            isinstance(c, str) and isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 20
            for c, v in classes.items()
        ):
            raise CorruptSave(f"the classes of {name!r} must map class names to levels from 1 to 20")
        out[str(name)] = Hero(level, xp, dict(classes))
    return out


@dataclass
class GameState:
    """What the save file and the live session carry besides the message history.

    `campaign` is filled in by the `begin_adventure` tool at the end of Session 0 and holds
    the keys `setting`, `party`, `party_size`, `level` and (optionally) `gm_notes`. `ruleset` is an id from aigm.rulesets. `world` is
    the persistent knowledge base (docs/WORLD.md); it stays empty in Session 0."""

    phase: Phase = Phase.SESSION_ZERO
    campaign: dict[str, Any] | None = None
    world: World = field(default_factory=World)
    # The rules the game is played under: chosen in Session 0 (set_ruleset), fixed once the adventure begins.
    ruleset: str = DEFAULT_RULESET
    # The current turn number (player messages so far, including this one), set by the turn loop. Not saved: facts record it.
    turn: int = field(default=0, compare=False)
    # Set when the GM looked up something unrecorded: ask for a curator pass soon. Not saved.
    pass_requested: bool = field(default=False, compare=False)
    # How the game is shaped (docs/STORY.md): "endless", or the length of a structured story. Chosen in Session 0
    # (set_structure); None there means the player has not been asked yet, and begin_adventure waits for an answer.
    structure: str | None = None
    # The story plan of a structured game; None while the plotter has not written it, and always None when endless.
    story: Story | None = None
    # Each character's advancement, by name; kept by the server and changed with the `award` tool (docs/PROGRESSION.md).
    # A character with no entry is at the party's starting level with no XP (see `hero`).
    heroes: dict[str, Hero] = field(default_factory=dict)

    @property
    def party_names(self) -> list[str]:
        party = (self.campaign or {}).get("party")
        return [m["name"] for m in party if isinstance(m, dict) and isinstance(m.get("name"), str)] if party else []

    @property
    def start_level(self) -> int:
        start = (self.campaign or {}).get("level")
        return start if isinstance(start, int) and not isinstance(start, bool) else 1

    def find_hero(self, name: str) -> str | None:
        """The party member a name refers to (case and spacing aside), or None."""
        wanted = " ".join(str(name).lower().split())
        return next((n for n in self.party_names if " ".join(n.lower().split()) == wanted), None)

    def hero(self, name: str) -> Hero:
        return self.heroes.get(name) or Hero(self.start_level, 0)

    @property
    def average_level(self) -> float:
        names = self.party_names
        return sum(self.hero(n).level for n in names) / len(names) if names else float(self.start_level)

    def __post_init__(self) -> None:
        if self.phase is Phase.ADVENTURE and self.structure is None:
            self.structure = ENDLESS  # a game in play always has one; older saves and tests never chose

    def copy(self) -> "GameState":
        return GameState(
            self.phase,
            copy.deepcopy(self.campaign),
            self.world.copy(),
            self.ruleset,
            self.turn,
            self.pass_requested,
            self.structure,
            self.story.copy() if self.story else None,
            {n: Hero(h.level, h.xp, dict(h.classes)) for n, h in self.heroes.items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "campaign": self.campaign,
            "world": self.world.to_dict(),
            "ruleset": self.ruleset,
            "structure": self.structure,
            "story": self.story.to_dict() if self.story else None,
            "heroes": {n: {"level": h.level, "xp": h.xp, "classes": dict(h.classes)} for n, h in self.heroes.items()},
        }

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
        ruleset = data.get("ruleset", DEFAULT_RULESET)  # saves from before rulesets were all D&D 2024
        if ruleset not in BY_ID:
            raise CorruptSave(f"unknown ruleset {ruleset!r}")
        structure = data.get("structure")  # saves from before stories were all endless (see __post_init__)
        if structure is not None and structure not in STRUCTURES:
            raise CorruptSave(f"unknown game structure {structure!r}")
        story = Story.from_dict(data["story"]) if data.get("story") is not None else None
        if story is not None and story.length != structure:
            raise CorruptSave(f"a {structure} game cannot have a {story.length} story")
        if phase is Phase.SESSION_ZERO and story is not None:
            raise CorruptSave("a session_zero save cannot have a story")
        heroes = _read_heroes(data.get("heroes"))  # saves before version 5 have none
        return cls(phase, campaign, world, ruleset, structure=structure, story=story, heroes=heroes)
