"""A character's Look: how they appear, written once and kept stable (docs/LOOKS.md).

A Look is a short summary, a detailed description for an image model, and a few tags. It belongs to a party member
(`GameState.looks`) or to an NPC entity (`Entity.look`), never to a fact or a sheet. This module is the record and its
rules; writing Looks is the describer's job (docs/LOOKS.md 5)."""

import re
from dataclasses import dataclass, field
from typing import Any

from aigm.errors import CorruptSave

# Controlled tags (docs/LOOKS.md 3.2): the filter a similarity search runs on, so only these values are accepted.
CONTROLLED_TAGS: dict[str, tuple[str, ...]] = {
    "ancestry": (
        "human", "elf", "dwarf", "halfling", "gnome", "half-elf", "half-orc", "orc", "tiefling", "dragonborn",
        "goblinoid", "beastfolk", "construct", "undead", "other",
    ),
    "age": ("child", "youth", "adult", "middle-aged", "elderly", "ageless"),
    "gender": ("feminine", "masculine", "androgynous"),
    "build": ("slight", "lean", "average", "sturdy", "heavy", "towering"),
    "height": ("short", "average", "tall"),
}  # fmt: skip
TEXT_TAGS = ("skin", "hair", "eyes", "clothing", "archetype", "expression")  # short free text
LIST_TAGS = ("marks", "carries")  # short lists of short free text

# The tags of a place's Look (docs/PLACES.md 4.1). A Look is either a person's or a place's, by the kind of entity.
PLACE_CONTROLLED_TAGS: dict[str, tuple[str, ...]] = {
    "scale": ("room", "building", "site", "district", "settlement", "region"),
    "setting": ("urban", "rural", "wilderness", "underground", "waterside", "sea", "interior", "other"),
    "climate": ("temperate", "cold", "hot", "arid", "wet", "magical", "unknown"),
}
PLACE_TEXT_TAGS = ("architecture", "terrain", "flora", "light", "mood")
PLACE_LIST_TAGS = ("features",)
PERSON, PLACE = "person", "place"


def look_kind(entity_kind: str) -> str:
    """Which kind of Look an entity has: a person's (a party member or an npc) or a place's (a location)."""
    return PLACE if entity_kind == "location" else PERSON


def tag_sets(kind: str) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...], tuple[str, ...]]:
    """The controlled, free-text and list tags of a kind of Look."""
    if kind == PLACE:
        return PLACE_CONTROLLED_TAGS, PLACE_TEXT_TAGS, PLACE_LIST_TAGS
    return CONTROLLED_TAGS, TEXT_TAGS, LIST_TAGS
STATES = ("provisional", "fixed")
SOURCES = ("generated", "session_zero", "narration")

MAX_SUMMARY_WORDS = 25
MIN_DESCRIPTION_WORDS = 80
MAX_DESCRIPTION_WORDS = 160
MAX_TAG_WORDS = 12
MAX_LIST_ITEMS = 5
SEARCH_TEXT_VERSION = 1  # bump when the search text format changes, so stored embeddings can be redone in bulk

# Names the product must not use (docs/LAUNCH_RULESETS.md 5.3). A starting list; the describer prompt carries the rest.
PRODUCT_TERMS = (
    "dungeons & dragons", "dungeons and dragons", "d&d", "forgotten realms", "golarion", "greyhawk", "eberron",
    "pathfinder", "beholder", "mind flayer", "illithid", "drow", "githyanki", "owlbear",
)  # fmt: skip
_SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself|the party|the adventurers?)\b", re.I)
_GAME_TERMS = re.compile(
    r"\b(hp|hit points?|armou?r class|saving throws?|d20|xp|experience points?|level \d+|"
    r"(?:\d+(?:st|nd|rd|th)|first|second|third)[- ]level)\b",
    re.I,
)


class LookError(ValueError):
    """A Look the rules reject. The message lists every problem and is written to be shown to the model."""


def _words(text: str) -> int:
    return len(text.split())


@dataclass
class Look:
    summary: str
    description: str
    tags: dict[str, Any] = field(default_factory=dict)
    rev: int = 1  # bumped whenever the text changes (docs/LOOKS.md 7)
    state: str = "provisional"  # provisional | fixed
    source: str = "generated"  # generated | session_zero | narration

    def copy(self) -> "Look":
        return Look(
            self.summary, self.description, {k: list(v) if isinstance(v, list) else v for k, v in self.tags.items()},
            self.rev, self.state, self.source,
        )  # fmt: skip

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "description": self.description,
            "tags": {k: list(v) if isinstance(v, list) else v for k, v in self.tags.items()},
            "rev": self.rev,
            "state": self.state,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Look":
        """Read a Look from a save. Checks the shape, not the content rules: a save must still load if they were
        tightened after it was written. Raises ValueError for a malformed Look."""
        if not isinstance(data, dict):
            raise ValueError("a look must be an object")
        summary, description, tags = data.get("summary"), data.get("description"), data.get("tags")
        if not isinstance(summary, str) or not isinstance(description, str) or not isinstance(tags, dict):
            raise ValueError("a look needs a summary, a description and tags")
        clean: dict[str, Any] = {}
        for key, value in tags.items():
            if isinstance(value, str):
                clean[str(key)] = value
            elif isinstance(value, list) and all(isinstance(v, str) for v in value):
                clean[str(key)] = list(value)
            else:
                raise ValueError(f"tag {key!r} must be text or a list of text")
        rev = data.get("rev", 1)
        if isinstance(rev, bool) or not isinstance(rev, int) or rev < 1:
            raise ValueError("a look's rev must be a positive integer")
        state, source = data.get("state", "provisional"), data.get("source", "generated")
        if state not in STATES or source not in SOURCES:
            raise ValueError("a look has an unknown state or source")
        return cls(summary, description, clean, rev, state, source)

    def search_text(self, kind: str = PERSON) -> str:
        """The canonical text a similarity search is run on (docs/LOOKS.md 6 and docs/PLACES.md 4.3): a fixed order, so
        it is stable. It is derived, never stored. The format has a version, `SEARCH_TEXT_VERSION`."""
        if kind == PLACE:
            head = " ".join(str(self.tags.get(k, "")).strip() for k in PLACE_CONTROLLED_TAGS).split()
            details = []
            for key in PLACE_TEXT_TAGS:
                value = str(self.tags.get(key) or "").strip()
                if value:
                    details.append(value)
            features = self.tags.get("features")
            return " | ".join(
                p for p in (" ".join(head), self.summary.strip(), "; ".join(details),
                            ", ".join(features) if isinstance(features, list) else "") if p
            )  # fmt: skip
        parts = [str(self.tags.get(k, "")).strip() for k in CONTROLLED_TAGS]
        for key in ("hair", "eyes", "marks", "archetype"):
            value = self.tags.get(key)
            text = "; ".join(value) if isinstance(value, list) else str(value or "").strip()
            if text:
                parts.append(f"{key}: {text}")
        parts.append(self.summary.strip())
        return " | ".join(p for p in parts if p)


_NAME_FILLER = frozenset("the of a an and in on at to above below beyond".split())


def _uses_name(description: str, name: str, kind: str = PERSON) -> bool:
    """Does the description name the character? A title the model drops ("Aggie Fenn" for "Saltwife Aggie Fenn")
    is fine, so the name without its first word counts when it has three or more. A place may be named loosely ("the
    pass above the old quarry" for "Pass above the old quarry"): all of the name's own words are enough."""
    text, words = description.lower(), name.strip().lower().split()
    if " ".join(words) in text or (kind == PERSON and len(words) >= 3 and " ".join(words[1:]) in text):
        return True
    if kind == PLACE:
        own = [w.strip(".,'\"") for w in words if w.strip(".,'\"") not in _NAME_FILLER]
        return bool(own) and all(w in text for w in own)
    return False


def problems(look: Look, name: str, kind: str = PERSON) -> list[str]:
    """Everything wrong with a Look under the content rules (docs/LOOKS.md 3 and 5.3, docs/PLACES.md 4), or an empty
    list. `kind` is `PERSON` or `PLACE`: the tags and a few of the messages differ."""
    controlled, text_tags, list_tags = tag_sets(kind)
    noun = "place" if kind == PLACE else "character"
    out: list[str] = []
    summary_words = _words(look.summary)
    if not look.summary.strip():
        out.append("'summary' is empty")
    elif summary_words > MAX_SUMMARY_WORDS:
        out.append(f"'summary' has {summary_words} words; at most {MAX_SUMMARY_WORDS}")
    words = _words(look.description)
    if not MIN_DESCRIPTION_WORDS <= words <= MAX_DESCRIPTION_WORDS:
        out.append(
            f"'description' has {words} words; it must have {MIN_DESCRIPTION_WORDS} to {MAX_DESCRIPTION_WORDS}"
        )
    if name.strip() and not _uses_name(look.description, name, kind):
        out.append(f"'description' must use the {noun}'s name, {name!r}")
    unknown = sorted(set(look.tags) - set(controlled) - set(text_tags) - set(list_tags))
    if unknown:
        out.append(f"unknown tags: {', '.join(unknown)}")
    for tag, allowed in controlled.items():
        value = look.tags.get(tag)
        if value not in allowed:
            out.append(f"tag '{tag}' must be one of {', '.join(allowed)}; got {value!r}")
    for tag in text_tags:
        value = look.tags.get(tag)
        if value is not None and (not isinstance(value, str) or _words(value) > MAX_TAG_WORDS):
            out.append(f"tag '{tag}' must be text of at most {MAX_TAG_WORDS} words")
    for tag in list_tags:
        value = look.tags.get(tag)
        if value is None:
            continue
        if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS or not all(
            isinstance(v, str) and 0 < _words(v) <= MAX_TAG_WORDS for v in value
        ):
            out.append(f"tag '{tag}' must be a list of at most {MAX_LIST_ITEMS} short items")
    text = " ".join([look.summary, look.description, *(str(v) for v in look.tags.values())])
    if (m := _SECOND_PERSON.search(text)) is not None:
        out.append(f"do not write {m.group(0)!r}: describe the {noun}, not the player or the party")
    if (m := _GAME_TERMS.search(text)) is not None:
        out.append(f"do not use game terms such as {m.group(0)!r}: describe only what can be seen")
    lower = text.lower()
    for term in PRODUCT_TERMS:
        if term in lower:
            out.append(f"do not use the product name {term!r}; use a generic description")
    return out


def validate(look: Look, name: str, kind: str = PERSON) -> None:
    """Raise LookError listing every problem, if there are any."""
    found = problems(look, name, kind)
    if found:
        raise LookError("Invalid look:\n- " + "\n- ".join(found))


def read_looks(raw: Any) -> dict[str, Look]:
    """The party members' Looks in a save file; a file from before Looks existed has none."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CorruptSave("looks must be an object")
    out = {}
    for name, data in raw.items():
        try:
            out[str(name)] = Look.from_dict(data)
        except ValueError as exc:
            raise CorruptSave(f"the look of {name!r} is invalid: {exc}") from None
    return out
