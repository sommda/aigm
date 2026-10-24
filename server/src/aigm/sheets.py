"""Character sheets as the server keeps them (docs/STATUS.md 3).

Deliberately minimal: a headline, optional hit points, conditions, and ordered sections of plain lines. The model
decides what sections a character of this ruleset and class needs (abilities, saves, spells, powers, gear...), so no
ruleset is built into the server. The free-text sheet in the campaign record stays what the GM reads each turn; this
is what the player sees and what the status table reads."""

from dataclasses import dataclass, field
from typing import Any

from aigm.errors import CorruptSave

MAX_HEADLINE = 120
MAX_SECTIONS = 16
MAX_TITLE = 60
MAX_LINES = 60
MAX_LINE = 240
MAX_CONDITIONS = 12
MAX_CONDITION = 40
MAX_HP = 9999


@dataclass
class Section:
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class Sheet:
    headline: str = ""  # e.g. "Human Rogue 3"
    hp: int | None = None
    max_hp: int | None = None
    conditions: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)

    def copy(self) -> "Sheet":
        return Sheet(
            self.headline, self.hp, self.max_hp, list(self.conditions), [Section(s.title, list(s.lines)) for s in self.sections]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "conditions": list(self.conditions),
            "sections": [{"title": s.title, "lines": list(s.lines)} for s in self.sections],
        }


def _text(value: Any, limit: int) -> str:
    return " ".join(value.split())[:limit].strip() if isinstance(value, str) else ""


def _count(value: Any, low: int) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= MAX_HP else None


def clean(raw: Any) -> Sheet:
    """A sheet from loose data (a model's answer), trimmed to the limits. Raises ValueError if nothing usable is left,
    so a caller can fall back to the free-text sheet."""
    if not isinstance(raw, dict):
        raise ValueError("a sheet must be an object")
    sections = []
    for s in raw.get("sections") if isinstance(raw.get("sections"), list) else []:
        if not isinstance(s, dict):
            continue
        title = _text(s.get("title"), MAX_TITLE)
        lines = [t for t in (_text(x, MAX_LINE) for x in s.get("lines") if isinstance(s.get("lines"), list)) if t]
        if title and lines:
            sections.append(Section(title, lines[:MAX_LINES]))
    if not sections:
        raise ValueError("the sheet has no sections")
    max_hp, hp = _count(raw.get("max_hp"), 1), _count(raw.get("hp"), 0)
    if max_hp is None:
        hp = None  # a current figure with no maximum is not shown
    elif hp is None:
        hp = max_hp
    conditions = [t for t in (_text(c, MAX_CONDITION) for c in raw.get("conditions") if isinstance(raw.get("conditions"), list)) if t]
    return Sheet(_text(raw.get("headline"), MAX_HEADLINE), hp, max_hp, list(dict.fromkeys(conditions))[:MAX_CONDITIONS], sections[:MAX_SECTIONS])


def read_sheets(raw: Any) -> dict[str, Sheet]:
    """The sheets of a save file; a file from before sheets existed has none."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CorruptSave("sheets must be an object")
    out = {}
    for name, data in raw.items():
        try:
            out[str(name)] = clean(data)
        except ValueError as exc:
            raise CorruptSave(f"the sheet of {name!r} is invalid: {exc}") from None
    return out
