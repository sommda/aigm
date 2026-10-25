"""The fight in progress, as the player may know it (docs/STATUS.md 4).

A small record the GM keeps with `set_combat`. Foes carry a health word, never numbers: the player is not told a
monster's hit points, so the status page must not say them, and since the GM writes only what the player may see,
nothing hidden can leak from here. The party is implied; its numbers come from the sheets."""

from dataclasses import dataclass, field
from typing import Any

from aigm.errors import CorruptSave

FOE, ALLY = "foe", "ally"
SIDES = (FOE, ALLY)
HEALTH_WORDS = ("unhurt", "scratched", "bloodied", "near death", "down")
MAX_COMBATANTS = 20
MAX_COUNT = 99
MAX_NAME = 60
MAX_HEALTH = 20
MAX_CONDITIONS = 6
MAX_CONDITION = 30


@dataclass
class Combatant:
    name: str
    side: str = FOE
    count: int = 1  # a pack of four wolves is one row with count 4
    health: str = "unhurt"  # a word from HEALTH_WORDS for foes; allies may show numbers ("9/12")
    conditions: list[str] = field(default_factory=list)

    def copy(self) -> "Combatant":
        return Combatant(self.name, self.side, self.count, self.health, list(self.conditions))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "side": self.side, "count": self.count, "health": self.health,
                "conditions": list(self.conditions)}

    @property
    def label(self) -> str:
        return f"{self.name} x{self.count}" if self.count > 1 else self.name


@dataclass
class Combat:
    combatants: list[Combatant] = field(default_factory=list)

    def copy(self) -> "Combat":
        return Combat([c.copy() for c in self.combatants])

    def to_dict(self) -> dict[str, Any]:
        return {"combatants": [c.to_dict() for c in self.combatants]}

    def find(self, name: str) -> Combatant | None:
        wanted = " ".join(name.lower().split())
        return next((c for c in self.combatants if " ".join(c.name.lower().split()) == wanted), None)


def read_combat(raw: Any) -> Combat | None:
    if raw is None:
        return None
    rows = raw.get("combatants") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise CorruptSave("combat must be an object with a list of combatants")
    out = []
    for r in rows:
        ok = (
            isinstance(r, dict) and isinstance(r.get("name"), str) and r.get("side") in SIDES
            and isinstance(r.get("count"), int) and not isinstance(r.get("count"), bool) and r["count"] >= 1
            and isinstance(r.get("health"), str) and isinstance(r.get("conditions"), list)
        )
        if not ok:
            raise CorruptSave("a combatant is invalid")
        out.append(Combatant(r["name"], r["side"], r["count"], r["health"], [str(c) for c in r["conditions"]]))
    return Combat(out)


def notes(combat: Combat | None) -> str:
    """The GM's reminder of what the player's table says, so `set_combat` updates start from it."""
    if combat is None:
        return ""
    who = "; ".join(f"{c.label} [{c.side}] {c.health}" + (f" ({', '.join(c.conditions)})" if c.conditions else "") for c in combat.combatants)
    return f"Fight in progress (shown to the player; change it with set_combat): {who}."
