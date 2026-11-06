"""The world knowledge base: entities, the facts about them, the clock and the scene.

Pure data and rules, no I/O and no LLM. Every mutating method validates first and changes
nothing if it raises `WorldError`, so a caller (for instance the `establish` tool) can hand the
message straight back to the model. Facts are never edited or deleted, only superseded.
See docs/WORLD.md section 2."""

import copy
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

from aigm import attempts as attempt_kinds
from aigm.errors import CorruptSave
from aigm.looks import Look, LookError, look_kind, validate
from aigm.portraits import Portrait
from aigm.world.digest import Digest
from aigm.world.text import normalize_name, normalize_text, tokens, word_count

KINDS = ("location", "npc", "faction", "concept", "item")
CURATOR_KINDS = ("location", "npc", "faction", "concept")  # the curator never makes key items (docs/KEY_ITEMS.md 5.1)
DISCLOSURES = ("hidden", "hinted", "known")
SOURCES = ("seed", "play", "generated", "improvised", "background")
STATUSES = ("active", "superseded")

# Checklist slots a fact can fill (docs/WORLD.md 5.3). "location" is the union of the site and
# settlement lists; the curator's frontier logic refines which apply.
ASPECTS: dict[str, tuple[str, ...]] = {
    "location": (
        "overview", "items", "approach", "discovery", "entry", "interior", "inhabitants", "history", "hazards",
        "connections", "secret", "layout", "leaders", "economy", "notable_places", "tensions",
    ),
    "npc": ("role", "appearance", "manner", "motivation", "relationships", "knowledge", "location"),
    "faction": ("goals", "leaders", "resources", "methods", "rivals", "presence", "history"),
    "concept": ("nature", "origin", "who_believes_it", "effects"),
    "item": ("appearance", "purpose", "whereabouts", "origin", "contents", "powers", "history", "secret", "custody"),
}  # fmt: skip

# Aspects only the server writes: a fact with one is valid about any kind of entity but is never a checklist slot for
# the curator (docs/ATTEMPTS.md 4.2).
SERVER_ASPECTS = ("attempts",)

# Aspects the party can plainly see on arriving at a place: a fact with one of these about the place the party is
# in is known to the player from the moment it exists, or from the moment the party gets there (docs/STATUS.md 5).
# `items` is not one: what lies in a place is written ahead of play with its true nature, and the party has seen it
# only when the narration shows it, and knows what it is only when the narration says so.
ARRIVAL_ASPECTS = ("overview",)

# Motives (docs/ROLEPLAY.md 7): what an NPC wants or fears. GM-only state, never shown to the player as such.
MOTIVE_SCOPES = ("underlying", "scene")
MOTIVE_KINDS = ("want", "fear", "loyalty", "grudge", "vice", "belief")
MOTIVE_STRENGTHS = ("leaning", "driven", "absolute")  # absolute: fixed for the life of the game, underlying only
MOTIVE_STATUSES = ("active", "satisfied", "frustrated", "superseded")  # "expired" is computed, never stored
MOTIVE_SOURCES = ("seed", "generated", "improvised", "play")
ABSOLUTE_SOURCES = ("seed", "generated")  # an absolute motive is written ahead of play, never in it
MAX_UNDERLYING_MOTIVES = 2  # live motives per person: two lasting and one for the scene
MAX_SCENE_MOTIVES = 1
SCENE_MOTIVE_HOURS = 2  # a scene motive lapses this many in-world hours after it was set
MAX_MOTIVE_WORDS = 40
MOTIVE_WORDS_LIMIT = 60
MIN_MOTIVE_WORDS = 3
MAX_MOTIVE_PHRASES = 4  # moved_by, resists and tells: at most this many of each
MAX_PHRASE_CHARS = 140

MAX_FACT_WORDS = 40  # what the prompts ask for
FACT_WORDS_LIMIT = 60  # what is refused: a fact a little over the ask is kept, since a refusal costs the GM a whole round
MIN_FACT_WORDS = 3
MAX_ENTITY_FACTS = 40  # active facts per entity (counting facts where it is the subject)
MAX_ABOUT = 4
MAX_NAME_CHARS = 80
MAX_ALIASES = 8

# Places and the ways between them (docs/TIME.md 5).
SCALES = ("room", "site", "settlement", "region")
BLOCK_KINDS = ("locked", "barred", "guarded", "collapsed", "flooded", "hidden", "other")
ROUTE_SOURCES = ("seed", "plotter", "generated", "improvised", "play")
MAX_ROUTE_MINUTES = 24 * 60 * 365
MAX_ROUTE_HOW = 80
MAX_BLOCK_TEXT = 120
MAX_ATTEMPT_TASK = 80  # docs/ATTEMPTS.md 4.1
MAX_ATTEMPT_TEXT = 200  # failure and reopens_if
MAX_ROUTES_PER_PLACE = 12
HOURS_PER_DAY = 24
MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = HOURS_PER_DAY * MINUTES_PER_HOUR

_FACT_ID = re.compile(r"^f\d+$")
_MOTIVE_ID = re.compile(r"^m\d+$")
_ENTITY_ID = re.compile(r"^e\d+$")
LOOK_KINDS = ("npc", "location", "item")  # the kinds of entity that have a Look

# A key item's relationship to the party (docs/KEY_ITEMS.md 4.2): the statuses, and the events that move between them.
HOLDING_STATUSES = ("unfound", "known", "held", "used", "lost")
HOLDING_EVENTS: dict[str, tuple[tuple[str, ...], str]] = {  # event -> (statuses it may start from, status it ends in)
    "learned": (("unfound",), "known"),
    "acquired": (("unfound", "known", "used", "lost"), "held"),
    "used": (("held",), "used"),
    "lost": (("held",), "lost"),
}
MAX_HOLDING_NOTE_WORDS = 25
VISIBLE_HOLDINGS = ("known", "held", "used", "lost")  # every status but unfound shows in the compendium
REVEALED_ON_ACQUIRING = ("appearance", "purpose")  # what the party can see once an item is in hand

class WorldError(ValueError):
    """A change the world rules reject. The message is written to be shown to the model."""


def duration_text(minutes: int) -> str:
    """A length of in-world time in words: "45 minutes", "2 hours 30 minutes", "1 day 3 hours"."""
    days, rest = divmod(minutes, MINUTES_PER_DAY)
    hours, mins = divmod(rest, MINUTES_PER_HOUR)
    parts = [(days, "day"), (hours, "hour"), (mins, "minute")]
    words = [f"{n} {unit}{'' if n == 1 else 's'}" for n, unit in parts if n]
    return " ".join(words[:2]) if words else "no time"


@dataclass(frozen=True, order=True)
class WorldTime:
    """A moment on the in-world clock: day 1 is the first day of the adventure, hour is 0-23, minute 0-59."""

    day: int = 1
    hour: int = 8
    minute: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.day, bool) or not isinstance(self.day, int) or self.day < 1:
            raise WorldError(f"day must be an integer of at least 1, got {self.day!r}")
        if isinstance(self.hour, bool) or not isinstance(self.hour, int) or not 0 <= self.hour < HOURS_PER_DAY:
            raise WorldError(f"hour must be an integer from 0 to 23, got {self.hour!r}")
        if isinstance(self.minute, bool) or not isinstance(self.minute, int) or not 0 <= self.minute < MINUTES_PER_HOUR:
            raise WorldError(f"minute must be an integer from 0 to 59, got {self.minute!r}")

    @property
    def total_minutes(self) -> int:
        return ((self.day - 1) * HOURS_PER_DAY + self.hour) * MINUTES_PER_HOUR + self.minute

    @property
    def total_hours(self) -> int:
        """Whole hours since the start of day 1 (a part hour does not count)."""
        return self.total_minutes // MINUTES_PER_HOUR

    @classmethod
    def from_minutes(cls, total: int) -> "WorldTime":
        day, rest = divmod(total, MINUTES_PER_DAY)
        hour, minute = divmod(rest, MINUTES_PER_HOUR)
        return cls(day + 1, hour, minute)

    def plus_minutes(self, minutes: int) -> "WorldTime":
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
            raise WorldError(f"time can only move forward by whole minutes, got {minutes!r}")
        return WorldTime.from_minutes(self.total_minutes + minutes)

    def plus(self, hours: int) -> "WorldTime":
        if isinstance(hours, bool) or not isinstance(hours, int) or hours < 0:
            raise WorldError(f"time can only move forward by whole hours, got {hours!r}")
        return self.plus_minutes(hours * MINUTES_PER_HOUR)

    def rounded(self, step: int = 5) -> "WorldTime":
        """The nearest multiple of `step` minutes, for what the GM and the player are shown."""
        return WorldTime.from_minutes(round(self.total_minutes / step) * step)

    def to_dict(self) -> dict[str, int]:
        return {"day": self.day, "hour": self.hour, "minute": self.minute}

    @classmethod
    def from_dict(cls, data: Any) -> "WorldTime":
        if not isinstance(data, dict):
            raise WorldError("time must be an object with day and hour")
        return cls(data.get("day"), data.get("hour"), data.get("minute", 0))  # type: ignore[arg-type]

    def __str__(self) -> str:
        return f"Day {self.day}, {self.hour:02d}:{self.minute:02d}"


@dataclass
class HoldingChange:
    """One step in a key item's history (docs/KEY_ITEMS.md 4.2)."""

    turn: int
    status: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"turn": self.turn, "status": self.status, "note": self.note}


@dataclass
class Holding:
    """Where a key item stands with the party: `unfound` (not in play, hidden from the player), `known` (the party has
    heard of it), `held`, `used` or `lost`, since which turn, and every change so far, oldest first."""

    status: str = "unfound"
    since: int = 0
    history: list[HoldingChange] = field(default_factory=list)
    # The turn the party first got the item, while no award has been made for it (docs/KEY_ITEMS.md 6.3).
    owed: int | None = None

    def copy(self) -> "Holding":
        return Holding(
            self.status, self.since, [HoldingChange(h.turn, h.status, h.note) for h in self.history], self.owed
        )

    @property
    def acquired(self) -> bool:
        """Has the party ever had it in hand?"""
        return any(h.status == "held" for h in self.history)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "since": self.since, "history": [h.to_dict() for h in self.history], "owed": self.owed,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "Holding":
        if not isinstance(raw, dict) or raw.get("status") not in HOLDING_STATUSES:
            raise WorldError("holding must be an object with a valid status")
        history = raw.get("history", [])
        if not isinstance(history, list):
            raise WorldError("holding history must be a list")
        steps = []
        for h in history:
            if not isinstance(h, dict) or h.get("status") not in HOLDING_STATUSES or not isinstance(h.get("note", ""), str):
                raise WorldError("holding history entries need a status and a note")
            steps.append(HoldingChange(_count(h.get("turn", 0), "holding turn"), h["status"], h.get("note", "")))
        owed = raw.get("owed")
        return cls(
            raw["status"], _count(raw.get("since", 0), "holding since"), steps,
            None if owed is None else _count(owed, "holding owed"),
        )


@dataclass
class Entity:
    id: str
    name: str
    kind: str
    aliases: list[str] = field(default_factory=list)
    parent: str | None = None
    discovered: bool = False  # has the player been told anything about it (cached from its facts)
    look: Look | None = None  # how a person or place appears (docs/LOOKS.md, docs/PLACES.md); npcs and locations
    portrait: Portrait | None = None  # their generated headshot (docs/PORTRAITS.md), likewise
    holding: Holding | None = None  # a key item's standing with the party (docs/KEY_ITEMS.md); items only
    scale: str | None = None  # a place's size: room, site, settlement or region (docs/TIME.md 5.1); locations only
    visited: bool = False  # the party has been to this place (docs/TIME.md 5.4.3); locations only

    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "aliases": list(self.aliases),
            "parent": self.parent, "discovered": self.discovered,
            "look": self.look.to_dict() if self.look else None,
            "portrait": self.portrait.to_dict() if self.portrait else None,
            "holding": self.holding.to_dict() if self.holding else None,
            "scale": self.scale, "visited": self.visited,
        }  # fmt: skip


@dataclass
class Block:
    """What stops the party on a route (docs/TIME.md 5.4.2). `opens_by` is a note for the GM alone."""

    kind: str
    text: str
    opens_by: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "text": self.text, "opens_by": self.opens_by}

    @classmethod
    def from_dict(cls, raw: Any) -> "Block":
        if not isinstance(raw, dict) or raw.get("kind") not in BLOCK_KINDS or not isinstance(raw.get("text"), str):
            raise WorldError("a block needs a kind and a text")
        opens = raw.get("opens_by", "")
        return cls(raw["kind"], raw["text"], opens if isinstance(opens, str) else "")


@dataclass
class Route:
    """A way between two places, symmetric, with the minutes it takes (docs/TIME.md 5.2)."""

    id: str
    a: str
    b: str
    minutes: int
    how: str = ""
    source: str = "improvised"
    block: Block | None = None

    def other(self, place: str) -> str:
        return self.b if place == self.a else self.a

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "a": self.a, "b": self.b, "minutes": self.minutes, "how": self.how, "source": self.source,
            "block": self.block.to_dict() if self.block else None,
        }  # fmt: skip


@dataclass
class Attempt:
    """A task the party tried and failed at (docs/ATTEMPTS.md 4.1). One record covers all the tries of a task: `tries`
    counts them. `reopens_if` and `reopens_at` are for the GM only."""

    id: str
    who: str  # the party member
    kind: str  # an action type (aigm.attempts.TYPES)
    task: str  # "pick the vault lock"
    about: str  # entity id
    status: str = "open"
    tries: int = 1
    scope: str = "character"
    failure: str = ""  # what failing cost or showed, completing "...and failed; ___"
    reopens_if: str = ""
    reopens_at: WorldTime | None = None
    fact: str | None = None  # the fact written about it
    turn: int = 0
    at: WorldTime = field(default_factory=WorldTime)

    @property
    def unresolved(self) -> bool:
        return self.status != "resolved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "who": self.who, "kind": self.kind, "task": self.task, "about": self.about,
            "status": self.status, "tries": self.tries, "scope": self.scope, "failure": self.failure,
            "reopens_if": self.reopens_if, "reopens_at": self.reopens_at.to_dict() if self.reopens_at else None,
            "fact": self.fact, "turn": self.turn, "at": self.at.to_dict(),
        }  # fmt: skip


@dataclass
class Fact:
    id: str
    text: str
    about: list[str]  # entity ids; the first is the subject
    disclosure: str = "hidden"
    source: str = "generated"
    turn: int = 0
    created_at: WorldTime = field(default_factory=WorldTime)
    aspect: str | None = None
    revealed_turn: int | None = None
    from_time: WorldTime | None = None  # reserved: nothing reads these yet
    until_time: WorldTime | None = None
    status: str = "active"
    superseded_by: str | None = None
    # Order in which the player learned it (World.learn_seq), for the compendium's "new" marks; 0 for facts the
    # player knew from the start of the adventure and for those saved before the compendium existed.
    learned_seq: int = 0
    # Party members whose starting knowledge this is (source "background"); empty for everything else.
    via: tuple[str, ...] = ()

    @property
    def subject(self) -> str:
        return self.about[0]

    @property
    def active(self) -> bool:
        return self.status == "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "text": self.text, "about": list(self.about), "aspect": self.aspect,
            "disclosure": self.disclosure, "source": self.source, "turn": self.turn,
            "created_at": self.created_at.to_dict(), "revealed_turn": self.revealed_turn,
            "learned_seq": self.learned_seq, "via": list(self.via),
            "from_time": self.from_time.to_dict() if self.from_time else None,
            "until_time": self.until_time.to_dict() if self.until_time else None,
            "status": self.status, "superseded_by": self.superseded_by,
        }  # fmt: skip


@dataclass
class Motive:
    """One thing an NPC wants, fears or holds to (docs/ROLEPLAY.md 7.1). Hidden from the player until disclosed.

    A `scene` motive belongs to the place and the moment it was set (`scene_location`, `set_at`); it lapses when the
    party leaves or SCENE_MOTIVE_HOURS pass, which `World.motive_live` works out from these, so nothing has to expire it.
    """

    id: str
    owner: str  # an npc entity id
    text: str
    scope: str = "underlying"
    kind: str = "want"
    strength: str = "leaning"
    moved_by: tuple[str, ...] = ()  # kinds of argument that engage it
    resists: tuple[str, ...] = ()  # kinds that bounce off
    tells: tuple[str, ...] = ()  # behavior that hints at it
    disclosure: str = "hidden"
    status: str = "active"
    superseded_by: str | None = None
    source: str = "generated"
    turn: int = 0
    scene_location: str | None = None  # scene motives only
    set_at: WorldTime = field(default_factory=WorldTime)

    @property
    def active(self) -> bool:
        return self.status == "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "owner": self.owner, "text": self.text, "scope": self.scope, "kind": self.kind,
            "strength": self.strength, "moved_by": list(self.moved_by), "resists": list(self.resists),
            "tells": list(self.tells), "disclosure": self.disclosure, "status": self.status,
            "superseded_by": self.superseded_by, "source": self.source, "turn": self.turn,
            "scene_location": self.scene_location, "set_at": self.set_at.to_dict(),
        }  # fmt: skip


@dataclass
class Scene:
    """Where the party is and who is with them (entity ids). Drives retrieval."""

    location: str | None = None
    present: list[str] = field(default_factory=list)


TITLES = frozenset({"sister", "brother", "father", "mother", "lord", "lady", "sir", "dame", "captain", "master", "ser"})


class World:
    """The knowledge base of one game. Plain data in `entities` and `facts` (insertion ordered);
    the dictionaries beginning with an underscore are indexes rebuilt by `_reindex`."""

    def __init__(self) -> None:
        self.time = WorldTime()
        self.scene = Scene()
        self.processed_through = 0  # number of history messages the curator has digested
        self.version = 0  # bumped on every change; lets a background pass detect interference
        self.reported_minutes = 0  # minutes the GM moved the clock itself (set_scene) since the last pass
        self.time_log: list[dict[str, Any]] = []  # why the clock moved in the last two turns: {"turn", "minutes", "why"}
        self.corrections: list[dict[str, Any]] = []  # notes for the GM's next briefing: {"text", "turn"}
        self.digests: dict[int, Digest] = {}  # turn digests by the index of the turn's first message
        self.next_id = {"f": 1, "e": 1, "m": 1, "r": 1, "a": 1}
        self.routes: dict[str, Route] = {}
        self.attempts: dict[str, Attempt] = {}  # failed tries, by id (docs/ATTEMPTS.md)
        # The one place that contains every other (docs/TIME.md 5.1). A new world has one from its bootstrap, so any two
        # places share an ancestor; a world made before this has none, and its places may lie in separate trees.
        self.root: str | None = None
        self.learn_seq = 0  # last number given to a fact the player learned; only goes up
        self.entities: dict[str, Entity] = {}
        self.facts: dict[str, Fact] = {}
        self.motives: dict[str, Motive] = {}
        # The player characters, as sets of name words. Not saved: the game state keeps it in step with the campaign.
        # A PC is never a person the party meets, so it has no compendium entry and is never "here" (see `is_party`).
        self._party: list[frozenset[str]] = []
        self._reindex()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, World) and self.to_dict() == other.to_dict()

    __hash__ = None  # type: ignore[assignment]  # mutable

    # ---- indexes -----------------------------------------------------------------------

    def _reindex(self) -> None:
        self._by_name: dict[str, str] = {}
        self._children: dict[str, list[str]] = {}
        self._facts_by_entity: dict[str, list[str]] = {}
        self._token_index: dict[str, set[str]] = {}  # token -> ids of active facts
        self._text_keys: dict[tuple[str, str], str] = {}  # (subject, normalized text) -> active fact id
        self._routes_by_place: dict[str, list[str]] = {}
        for ent in self.entities.values():
            self._index_entity(ent)
        for route in self.routes.values():
            self._index_route(route)
        for fact in self.facts.values():
            self._index_fact(fact)

    def _index_entity(self, ent: Entity) -> None:
        for name in ent.names():
            self._by_name[normalize_name(name)] = ent.id
        if ent.parent:
            self._children.setdefault(ent.parent, []).append(ent.id)

    def _index_route(self, route: Route) -> None:
        for place in (route.a, route.b):
            self._routes_by_place.setdefault(place, []).append(route.id)

    def _index_fact(self, fact: Fact) -> None:
        for eid in fact.about:
            self._facts_by_entity.setdefault(eid, []).append(fact.id)
        if fact.active:
            for tok in tokens(fact.text):
                self._token_index.setdefault(tok, set()).add(fact.id)
            self._text_keys[(fact.subject, normalize_text(fact.text))] = fact.id

    def _unindex_active(self, fact: Fact) -> None:
        for tok in tokens(fact.text):
            ids = self._token_index.get(tok)
            if ids:
                ids.discard(fact.id)
        self._text_keys.pop((fact.subject, normalize_text(fact.text)), None)

    def _touch(self) -> None:
        self.version += 1

    def _new_id(self, prefix: str) -> str:
        n = self.next_id[prefix]
        self.next_id[prefix] = n + 1
        return f"{prefix}{n:04d}" if prefix == "f" else f"{prefix}{n:03d}"

    # ---- lookup ------------------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        return not self.entities and not self.facts

    def entity(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    def fact(self, fact_id: str) -> Fact | None:
        return self.facts.get(fact_id)

    def find(self, name: str) -> Entity | None:
        """The entity with this name or alias (ignoring case, punctuation and a leading "the")."""
        eid = self._by_name.get(normalize_name(name))
        return self.entities[eid] if eid else None

    def set_party(self, names: Iterable[str]) -> None:
        """Say who the player characters are; any of them recorded as present leaves the scene."""
        self._party = [frozenset(normalize_name(n).split()) for n in names if normalize_name(n)]
        self.scene.present = [e for e in self.scene.present if not self.is_party(self.entities[e])]

    def is_party(self, ent: Entity) -> bool:
        """Is this entity a player character under a shorter or fuller name ("Brannoc" for "Brannoc Ironhale")? The
        curator records them as people from the narration; the words of a name must all be in a PC's name, and a
        single word must be one of theirs that is not a title."""
        if ent.kind != "npc" or not self._party:
            return False
        for name in (ent.name, *ent.aliases):
            words = normalize_name(name).split()
            if not words:
                continue
            for pc in self._party:
                if set(words) <= pc and (len(words) > 1 or words[0] not in TITLES or len(pc) == 1):
                    return True
        return False

    def resolve(self, ref: str) -> Entity | None:
        """An entity by id or by name/alias."""
        return self.entities.get(ref) or self.find(ref)

    def facts_about(
        self, entity_id: str, *, include_superseded: bool = False, disclosure: str | None = None
    ) -> list[Fact]:
        out = []
        for fid in self._facts_by_entity.get(entity_id, ()):
            fact = self.facts[fid]
            if (include_superseded or fact.active) and (disclosure is None or fact.disclosure == disclosure):
                out.append(fact)
        return out

    def children(self, entity_id: str) -> list[Entity]:
        return [self.entities[c] for c in self._children.get(entity_id, ())]

    def parent_chain(self, entity_id: str) -> list[Entity]:
        """Containing locations, nearest first (settlement, then region...)."""
        chain: list[Entity] = []
        ent = self.entities.get(entity_id)
        while ent and ent.parent:
            ent = self.entities[ent.parent]
            chain.append(ent)
        return chain

    def neighbors(self, entity_id: str) -> set[str]:
        """Entities one hop away: parent, children, and anything sharing an active fact."""
        out: set[str] = set()
        ent = self.entities.get(entity_id)
        if ent is None:
            return out
        if ent.parent:
            out.add(ent.parent)
        out.update(self._children.get(entity_id, ()))
        for fact in self.facts_about(entity_id):
            out.update(fact.about)
        out.discard(entity_id)
        return out

    def distances(self, start: str) -> dict[str, int]:
        """Graph distance (in hops) from `start` to every reachable entity."""
        if start not in self.entities:
            return {}
        dist = {start: 0}
        queue = deque([start])
        while queue:
            cur = queue.popleft()
            for nxt in self.neighbors(cur):
                if nxt not in dist:
                    dist[nxt] = dist[cur] + 1
                    queue.append(nxt)
        return dist

    def coverage(self, entity_id: str) -> set[str]:
        """Checklist aspects the entity's active facts (as subject) already fill."""
        return {f.aspect for f in self.facts_about(entity_id) if f.aspect and f.subject == entity_id}

    def mentioned(self, text: str) -> list[Entity]:
        """Entities whose name or alias appears in the text, in order of first appearance."""
        haystack = f" {normalize_text(text)} "
        hits: list[tuple[int, str]] = []
        for norm, eid in self._by_name.items():
            if not norm:
                continue
            pos = haystack.find(f" {norm} ")
            if pos >= 0:
                hits.append((pos, eid))
        seen: set[str] = set()
        out = []
        for _, eid in sorted(hits):
            if eid not in seen:
                seen.add(eid)
                out.append(self.entities[eid])
        return out

    def search(self, query: str, limit: int = 10) -> list[Fact]:
        """Active facts ranked by how many query words they share (ties: newest first)."""
        scores: dict[str, int] = {}
        for tok in tokens(query):
            for fid in self._token_index.get(tok, ()):
                scores[fid] = scores.get(fid, 0) + 1
        ranked = sorted(scores, key=lambda fid: (-scores[fid], -int(fid[1:])))
        return [self.facts[fid] for fid in ranked[:limit]]

    def similar_fact(self, text: str, subject: str, threshold: float = 0.8) -> Fact | None:
        """An active fact about `subject` that says nearly the same thing (shared-word overlap)."""
        mine = tokens(text)
        if not mine:
            return None
        best, best_score = None, 0.0
        for fact in self.facts_about(subject):
            theirs = tokens(fact.text)
            score = len(mine & theirs) / len(mine | theirs) if theirs else 0.0
            if score >= threshold and score > best_score:
                best, best_score = fact, score
        return best

    def counts(self) -> dict[str, int]:
        active = sum(1 for f in self.facts.values() if f.active)
        return {"entities": len(self.entities), "facts": active, "superseded": len(self.facts) - active}

    # ---- changes -----------------------------------------------------------------------

    def add_entity(
        self, name: str, kind: str, *, aliases: Iterable[str] = (), parent: str | None = None
    ) -> Entity:
        name = _clean_name(name, "name")
        if kind not in KINDS:
            raise WorldError(f"kind must be one of {', '.join(KINDS)}, got {kind!r}")
        alias_list: list[str] = []
        for alias in aliases:
            alias = _clean_name(alias, "alias")
            if normalize_name(alias) != normalize_name(name) and alias not in alias_list:
                alias_list.append(alias)
        if len(alias_list) > MAX_ALIASES:
            raise WorldError(f"at most {MAX_ALIASES} aliases per entity")
        self._check_names_free([name, *alias_list], owner=None)
        if parent is not None:
            parent_ent = self.entities.get(parent)
            if parent_ent is None:
                raise WorldError(f"unknown parent {parent!r}")
            if kind != "location" or parent_ent.kind != "location":
                raise WorldError("only locations can be inside other locations (parent must be a location)")
        ent = Entity(self._new_id("e"), name, kind, alias_list, parent, holding=Holding() if kind == "item" else None)
        self.entities[ent.id] = ent
        self._index_entity(ent)
        self._touch()
        return ent

    def add_alias(self, entity_id: str, alias: str) -> None:
        ent = self._entity_or_error(entity_id)
        alias = _clean_name(alias, "alias")
        if normalize_name(alias) in {normalize_name(n) for n in ent.names()}:
            return
        if len(ent.aliases) >= MAX_ALIASES:
            raise WorldError(f"{ent.name} already has {MAX_ALIASES} aliases")
        self._check_names_free([alias], owner=ent.id)
        ent.aliases.append(alias)
        self._by_name[normalize_name(alias)] = ent.id
        self._touch()

    # ---- scales and routes (docs/TIME.md 5) --------------------------------------------

    def set_scale(self, entity_id: str, scale: str) -> None:
        ent = self._entity_or_error(entity_id)
        if ent.kind != "location":
            raise WorldError(f"only a place has a scale, and {ent.name} is a {ent.kind}")
        if scale not in SCALES:
            raise WorldError(f"scale must be one of {', '.join(SCALES)}, got {scale!r}")
        if ent.scale != scale:
            ent.scale = scale
            self._touch()

    def set_root(self, entity_id: str) -> None:
        """Make a place the top of the world: it scales as a region, and every other place that had no parent is now
        inside it. From then on a new place with no parent goes inside it (`default_parent`)."""
        ent = self._entity_or_error(entity_id)
        if ent.kind != "location" or ent.parent is not None:
            raise WorldError(f"{ent.name} cannot be the root: it must be a place with nothing above it")
        self.root = ent.id
        if ent.scale is None:
            ent.scale = "region"
        for other in self.entities.values():
            if other.kind == "location" and other.parent is None and other.id != ent.id:
                self.set_parent(other.id, ent.id)
        self._touch()

    def default_parent(self, kind: str, parent: str | None) -> str | None:
        """The parent a new entity gets: the one given, or the root for a place that was given none."""
        return parent if parent is not None or kind != "location" else self.root

    def set_parent(self, entity_id: str, parent: str) -> None:
        """Move a place inside another (never inside itself or anything it contains)."""
        ent = self._entity_or_error(entity_id)
        new = self._entity_or_error(parent)
        if ent.kind != "location" or new.kind != "location":
            raise WorldError("only places can be inside other places")
        if ent.id == new.id or ent.id in {p.id for p in self.parent_chain(new.id)}:
            raise WorldError(f"{ent.name} cannot be inside {new.name}: that would make a loop")
        if ent.parent == new.id:
            return
        if ent.parent in self._children and entity_id in self._children[ent.parent]:
            self._children[ent.parent].remove(entity_id)
        ent.parent = new.id
        self._children.setdefault(new.id, []).append(entity_id)
        self._touch()

    def routes_of(self, place: str) -> list[Route]:
        """The routes that start or end at a place, in the order they were recorded."""
        return [self.routes[r] for r in self._routes_by_place.get(place, ())]

    def find_route(self, a: str, b: str, how: str = "") -> Route | None:
        """The route between two places with this description (case and spacing aside), if there is one."""
        wanted = normalize_text(how)
        for route in self.routes_of(a):
            if route.other(a) == b and normalize_text(route.how) == wanted:
                return route
        return None

    def set_route(
        self, a: str, b: str, minutes: int, how: str = "", *, source: str = "improvised", block: "Block | None | str" = "keep"
    ) -> tuple[Route, bool]:
        """Record a way between two places, or update the one with the same description. `block` is a Block to set,
        None to clear, or "keep" (the default) to leave an existing one alone. Returns the route and whether it is new."""
        for end in (a, b):
            ent = self._entity_or_error(end)
            if ent.kind != "location":
                raise WorldError(f"a route joins places, and {ent.name} is a {ent.kind}")
        if a == b:
            raise WorldError("a route needs two different places")
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= MAX_ROUTE_MINUTES:
            raise WorldError(f"a route takes a whole number of minutes from 1 to {MAX_ROUTE_MINUTES}")
        how = " ".join(str(how or "").split())
        if len(how) > MAX_ROUTE_HOW:
            raise WorldError(f"`how` is {len(how)} characters; at most {MAX_ROUTE_HOW}")
        if source not in ROUTE_SOURCES:
            raise WorldError(f"route source must be one of {', '.join(ROUTE_SOURCES)}")
        if isinstance(block, Block):
            if block.kind not in BLOCK_KINDS:
                raise WorldError(f"block kind must be one of {', '.join(BLOCK_KINDS)}")
            block = Block(block.kind, " ".join(block.text.split()), " ".join(block.opens_by.split()))
            if not 3 <= len(block.text) <= MAX_BLOCK_TEXT:
                raise WorldError(f"a block's text must be 3 to {MAX_BLOCK_TEXT} characters")
            if len(block.opens_by) > MAX_BLOCK_TEXT:
                raise WorldError(f"`opens_by` is longer than {MAX_BLOCK_TEXT} characters")
        existing = self.find_route(a, b, how)
        if existing is not None:
            existing.minutes = minutes
            if block != "keep":
                existing.block = block  # type: ignore[assignment]
            self._touch()
            return existing, False
        for end in (a, b):
            if len(self._routes_by_place.get(end, ())) >= MAX_ROUTES_PER_PLACE:
                raise WorldError(f"{self.entities[end].name} already has {MAX_ROUTES_PER_PLACE} routes")
        route = Route(self._new_id("r"), a, b, minutes, how, source, None if block == "keep" else block)  # type: ignore[arg-type]
        self.routes[route.id] = route
        self._index_route(route)
        self._touch()
        return route, True

    # ---- attempts (docs/ATTEMPTS.md) ---------------------------------------------------------

    def add_attempt(
        self,
        who: str,
        kind: str,
        task: str,
        about: str,
        *,
        status: str = "open",
        scope: str = "character",
        failure: str = "",
        reopens_if: str = "",
        reopens_at: WorldTime | None = None,
        turn: int = 0,
    ) -> Attempt:
        """Record a failed task. `about` is an entity id; one record is kept for all the tries of a task, so use
        `find_attempt` first and `retry_attempt` for a later try."""
        self._entity_or_error(about)
        who, task = " ".join(str(who).split()), " ".join(str(task).split())
        failure, reopens_if = " ".join(str(failure).split()), " ".join(str(reopens_if).split())
        if not who:
            raise WorldError("an attempt needs the character who tried it")
        if kind not in attempt_kinds.KINDS:
            raise WorldError(f"attempt kind must be one of {', '.join(attempt_kinds.KINDS)}")
        if status not in (attempt_kinds.OPEN, attempt_kinds.CLOSED):
            raise WorldError("a new attempt is open or closed")
        if scope not in attempt_kinds.SCOPES:
            raise WorldError(f"attempt scope must be one of {', '.join(attempt_kinds.SCOPES)}")
        if not 3 <= len(task) <= MAX_ATTEMPT_TASK:
            raise WorldError(f"an attempt's task must be 3 to {MAX_ATTEMPT_TASK} characters")
        if len(failure) > MAX_ATTEMPT_TEXT or len(reopens_if) > MAX_ATTEMPT_TEXT:
            raise WorldError(f"`failure` and `reopens_if` are at most {MAX_ATTEMPT_TEXT} characters")
        attempt = Attempt(
            self._new_id("a"), who, kind, task, about, status, 1, scope, failure, reopens_if, reopens_at, None, turn, self.time
        )  # fmt: skip
        self.attempts[attempt.id] = attempt
        self._touch()
        return attempt

    def find_attempt(self, who: str, kind: str, about: str) -> Attempt | None:
        """The unresolved attempt of this kind on this target that applies to this character: their own, or one closed
        to everyone. A closed one whose clock has run out counts as open again (`reopen_due`)."""
        self.reopen_due()
        wanted = normalize_name(who)
        for attempt in reversed(list(self.attempts.values())):
            if attempt.unresolved and attempt.kind == kind and attempt.about == about and (
                attempt.scope == "anyone" or normalize_name(attempt.who) == wanted
            ):
                return attempt
        return None

    def attempts_about(self, entity_ids: Iterable[str], *, unresolved_only: bool = True) -> list[Attempt]:
        """Attempts on these entities, newest first."""
        wanted = set(entity_ids)
        found = [a for a in self.attempts.values() if a.about in wanted and (a.unresolved or not unresolved_only)]
        return sorted(found, key=lambda a: a.id, reverse=True)

    def reopen_due(self) -> list[Attempt]:
        """Open again every closed attempt whose clock (`reopens_at`) has run out. Returns those it opened."""
        opened = [
            a for a in self.attempts.values()
            if a.status == attempt_kinds.CLOSED and a.reopens_at is not None and a.reopens_at <= self.time
        ]  # fmt: skip
        for a in opened:
            a.status, a.reopens_at = attempt_kinds.OPEN, None
        if opened:
            self._touch()
        return opened

    def set_attempt_status(self, attempt_id: str, status: str, *, reopens_if: str | None = None, reopens_at: WorldTime | None = None) -> Attempt:
        """Close, reopen or resolve an attempt. Closing may say what reopens it, and when."""
        attempt = self.attempts.get(attempt_id)
        if attempt is None:
            raise WorldError(f"unknown attempt {attempt_id!r}")
        if status not in attempt_kinds.STATUSES:
            raise WorldError(f"attempt status must be one of {', '.join(attempt_kinds.STATUSES)}")
        attempt.status = status
        attempt.reopens_at = reopens_at if status == attempt_kinds.CLOSED else None
        if reopens_if is not None:
            text = " ".join(reopens_if.split())
            if len(text) > MAX_ATTEMPT_TEXT:
                raise WorldError(f"`reopens_if` is at most {MAX_ATTEMPT_TEXT} characters")
            attempt.reopens_if = text
        self._touch()
        return attempt

    def retry_attempt(self, attempt_id: str, *, failure: str = "", turn: int = 0) -> Attempt:
        """Another failed try of the same task: the count goes up and the failure is what the latest try cost."""
        attempt = self.attempts.get(attempt_id)
        if attempt is None:
            raise WorldError(f"unknown attempt {attempt_id!r}")
        attempt.tries += 1
        text = " ".join(str(failure).split())
        if text:
            if len(text) > MAX_ATTEMPT_TEXT:
                raise WorldError(f"`failure` is at most {MAX_ATTEMPT_TEXT} characters")
            attempt.failure = text
        attempt.turn, attempt.at = turn, self.time
        self._touch()
        return attempt

    def set_look(self, entity_id: str, look: Look) -> Look:
        """Give a person their Look, or replace it (docs/LOOKS.md). The Look must pass the content rules."""
        ent = self._entity_or_error(entity_id)
        if ent.kind not in LOOK_KINDS:
            raise WorldError(f"{ent.name} is a {ent.kind}; only people, places and key items have a look")
        try:
            validate(look, ent.name, look_kind(ent.kind))
        except LookError as exc:
            raise WorldError(str(exc)) from None
        ent.look = look.copy()
        self._touch()
        return ent.look

    def set_portrait(self, entity_id: str, portrait: Portrait) -> Portrait:
        """Give a person their portrait record, or replace it (docs/PORTRAITS.md 6.2)."""
        ent = self._entity_or_error(entity_id)
        if ent.kind not in LOOK_KINDS:
            raise WorldError(f"{ent.name} is a {ent.kind}; only people, places and key items have a portrait")
        ent.portrait = portrait.copy()
        self._touch()
        return ent.portrait

    def set_holding(self, entity_id: str, event: str, note: str = "", turn: int = 0, source: str = "play") -> bool:
        """Move a key item between `unfound`, `known`, `held`, `used` and `lost` (docs/KEY_ITEMS.md 4.2). Returns False
        when the item is already where the event would put it. The change is written as a known `custody` fact, and
        the first time the party has the item in hand its appearance and purpose become known."""
        ent = self._entity_or_error(entity_id)
        if ent.kind != "item" or ent.holding is None:
            raise WorldError(f"{ent.name} is a {ent.kind}, not a key item")
        if event not in HOLDING_EVENTS:
            raise WorldError(f"event must be one of {', '.join(HOLDING_EVENTS)}, got {event!r}")
        starts, end = HOLDING_EVENTS[event]
        hold = ent.holding
        if hold.status == end:
            return False
        if hold.status not in starts:
            raise WorldError(f"{ent.name} is {hold.status}, so it cannot be {event}")
        note = " ".join(str(note or "").split())
        if word_count(note) > MAX_HOLDING_NOTE_WORDS:
            raise WorldError(f"the note is {word_count(note)} words; at most {MAX_HOLDING_NOTE_WORDS}")
        first_time = end == "held" and not hold.acquired
        text = _custody_text(ent.name, event, end, hold.acquired, note)
        old = next((f for f in self.facts_about(ent.id) if f.subject == ent.id and f.aspect == "custody"), None)
        if old is None:
            self.add_fact(text, [ent.id], aspect="custody", disclosure="known", source=source, turn=turn)
        else:
            self.supersede(old.id, text, disclosure="known", source=source, turn=turn, allow_known=True)
        hold.status, hold.since = end, turn
        hold.history.append(HoldingChange(turn, end, note))
        if first_time and source != "seed":  # what the party starts with earns nothing
            hold.owed = turn
        ent.discovered = True
        if first_time:
            for fact in self.facts_about(ent.id):
                if fact.subject == ent.id and fact.aspect in REVEALED_ON_ACQUIRING:
                    self.reveal(fact.id, turn)
        self._touch()
        return True

    def add_fact(
        self,
        text: str,
        about: Iterable[str],
        *,
        aspect: str | None = None,
        disclosure: str = "hidden",
        source: str = "generated",
        turn: int = 0,
        via: Iterable[str] = (),
    ) -> Fact:
        text, about_ids = self._check_fact(text, about, aspect, disclosure, source)
        self._check_duplicate_and_cap(text, about_ids[0], replacing=None)
        fact = self._insert_fact(text, about_ids, aspect, disclosure, source, turn)
        fact.via = tuple(dict.fromkeys(v.strip() for v in via if isinstance(v, str) and v.strip()))
        if fact.aspect in ARRIVAL_ASPECTS and fact.subject == self.scene.location:
            self.reveal(fact.id, turn)  # the party is standing in it
        return fact

    def supersede(
        self,
        old_id: str,
        text: str,
        *,
        about: Iterable[str] | None = None,
        aspect: str | None = None,
        disclosure: str | None = None,
        source: str = "play",
        turn: int = 0,
        allow_known: bool = False,
    ) -> Fact:
        """Replace a fact with a new one that points back at it. The old fact stays on record.

        Known facts are canon the player has heard, so they can only be replaced when the caller
        says so explicitly (`allow_known`)."""
        old = self.facts.get(old_id)
        if old is None:
            raise WorldError(f"unknown fact {old_id!r}")
        if not old.active:
            raise WorldError(f"fact {old_id} was already superseded by {old.superseded_by}")
        if old.disclosure == "known" and not allow_known:
            raise WorldError(f"fact {old_id} is known to the player and cannot be replaced")
        about_ids_in = list(about) if about is not None else old.about
        new_disclosure = disclosure or old.disclosure
        new_aspect = aspect if aspect is not None else old.aspect
        text, about_ids = self._check_fact(text, about_ids_in, new_aspect, new_disclosure, source)
        self._check_duplicate_and_cap(text, about_ids[0], replacing=old)
        self._unindex_active(old)
        new = self._insert_fact(text, about_ids, new_aspect, new_disclosure, source, turn)
        old.status, old.superseded_by = "superseded", new.id
        return new

    def reveal(self, fact_id: str, turn: int) -> bool:
        """The player has now been told this fact. Returns False if it was already known."""
        fact = self.facts.get(fact_id)
        if fact is None:
            raise WorldError(f"unknown fact {fact_id!r}")
        if not fact.active:
            raise WorldError(f"fact {fact_id} was superseded and cannot be revealed")
        if fact.disclosure == "known":
            return False
        fact.disclosure, fact.revealed_turn = "known", turn
        fact.learned_seq = self._next_learned()
        self._mark_discovered(fact)
        self._touch()
        return True

    def set_scene(self, location: str | None, present: Iterable[str] = (), turn: int = 0) -> None:
        if location is not None:
            loc = self.entities.get(location)
            if loc is None or loc.kind != "location":
                raise WorldError(f"scene location must be a known location, got {location!r}")
        present_ids: list[str] = []
        for eid in present:
            if eid not in self.entities:
                raise WorldError(f"unknown entity {eid!r} in scene")
            if eid != location and eid not in present_ids and not self.is_party(self.entities[eid]):
                present_ids.append(eid)
        self.scene = Scene(location, present_ids)
        if location is not None:  # the party is standing in it, so it is known, whatever has been said about it yet
            self.entities[location].visited = True
            self.entities[location].discovered = True
        for eid in present_ids:  # the player can see who is there, so a person has been met even with no facts yet
            if self.entities[eid].kind == "npc":
                self.entities[eid].discovered = True
        if location is not None:  # arriving: what can be seen there is now known
            for fact in self.facts_about(location):
                if fact.aspect in ARRIVAL_ASPECTS and fact.subject == location:
                    self.reveal(fact.id, turn)
        self._touch()

    def advance_minutes(
        self, minutes: int, *, reported: bool = False, turn: int | None = None, why: str | None = None
    ) -> WorldTime:
        """Move the clock forward. `reported` marks time the GM declared itself, so the curator
        does not count the same minutes again when it reads the narration. With `turn` and `why` the passage is
        logged, so the next briefing can tell the GM how long the turn took (docs/TIME.md 4.1)."""
        self.time = self.time.plus_minutes(minutes)
        if reported:
            self.reported_minutes += minutes
        if minutes and why and turn is not None:
            self.time_log = [e for e in self.time_log if e["turn"] >= turn - 1]
            self.time_log.append({"turn": turn, "minutes": minutes, "why": why})
        self._touch()
        return self.time

    def time_spent(self, turn: int) -> list[dict[str, Any]]:
        """The logged passages of time of one turn."""
        return [e for e in self.time_log if e["turn"] == turn]

    def advance_time(self, hours: int, *, reported: bool = False) -> WorldTime:
        """`advance_minutes` for whole hours."""
        if isinstance(hours, bool) or not isinstance(hours, int) or hours < 0:
            raise WorldError(f"time can only move forward by whole hours, got {hours!r}")
        return self.advance_minutes(hours * MINUTES_PER_HOUR, reported=reported)

    def start_clock(self, hour: int) -> WorldTime:
        """Set the time of day the adventure opens at (day 1). Only possible before anything is recorded."""
        if self.facts:
            raise WorldError("the clock can only be started before anything is recorded")
        self.time = WorldTime(1, hour)
        self._touch()
        return self.time

    def settle_reported_minutes(self, narrated_minutes: int) -> int:
        """The curator read `narrated_minutes` of elapsed time in the narration. Advance the clock
        by whatever the GM has not already reported, then start counting afresh."""
        extra = max(0, narrated_minutes - self.reported_minutes)
        self.reported_minutes = 0
        if extra:
            self.advance_minutes(extra)
        else:
            self._touch()
        return extra

    def add_correction(self, text: str, turn: int) -> None:
        """Queue a note for the GM's next briefing (the GM contradicted something the player knows)."""
        if all(c["text"] != text for c in self.corrections):
            self.corrections.append({"text": text, "turn": turn})
            self._touch()

    def clear_corrections(self, shown: list[dict[str, Any]]) -> None:
        """Drop corrections the GM has now seen; ones queued meanwhile stay."""
        keep = [c for c in self.corrections if c not in shown]
        if len(keep) != len(self.corrections):
            self.corrections = keep
            self._touch()

    def set_time(self, when: WorldTime) -> WorldTime:
        """Move the clock to a later moment; it never goes backward."""
        if when < self.time:
            raise WorldError(f"the clock cannot go back from {self.time} to {when}")
        self.time = when
        self._touch()
        return self.time

    def reset_time(self, when: WorldTime) -> WorldTime:
        """Set the clock to any moment, earlier ones too (playtest mode only: the story's clock never goes back)."""
        self.time = when
        self.time_log.clear()
        self._touch()
        return self.time

    def mark_processed(self, message_count: int) -> None:
        if isinstance(message_count, bool) or not isinstance(message_count, int) or message_count < 0:
            raise WorldError("processed_through must be a non-negative integer")
        if message_count < self.processed_through:
            raise WorldError("processed_through cannot move backward")
        self.processed_through = message_count
        self._touch()

    def add_digest(self, digest: Digest, replace_stale: bool = False) -> bool:
        """Record the digest of a turn. A turn keeps the first digest it gets; returns whether this one was added.

        `replace_stale` is for a turn whose messages changed after it was digested (a save was edited, so the
        digest no longer covers the turn's messages): the digests it overlaps are dropped in favor of this one.
        A digest for exactly the same messages is never replaced."""
        overlapping = [d for d in self.digests.values() if d.start < digest.end and digest.start < d.end]
        if replace_stale and not any(d.start == digest.start and d.end == digest.end for d in overlapping):
            for d in overlapping:
                del self.digests[d.start]
            overlapping = []
        if overlapping:
            return False
        self.digests[digest.start] = digest
        self._touch()
        return True

    # ---- motives -----------------------------------------------------------------------

    def motive_live(self, motive: Motive) -> bool:
        """Does it count right now? An underlying motive does while it is active. A scene motive also needs the party
        to still be where it was set and fewer than SCENE_MOTIVE_HOURS in-world hours to have passed."""
        if not motive.active:
            return False
        if motive.scope == "underlying":
            return True
        elapsed = self.time.total_minutes - motive.set_at.total_minutes
        return motive.scene_location == self.scene.location and elapsed < SCENE_MOTIVE_HOURS * MINUTES_PER_HOUR

    def motive_state(self, motive: Motive) -> str:
        """The stored status, or "expired" for an active scene motive whose moment has passed."""
        return "active" if self.motive_live(motive) else "expired" if motive.active else motive.status

    def motives_of(self, owner: str, *, live_only: bool = True) -> list[Motive]:
        """An entity's motives, lasting ones first and the strongest of each first. By default only those that count
        now; otherwise also scene motives that have lapsed (but not resolved or superseded ones)."""
        rank = {s: i for i, s in enumerate(reversed(MOTIVE_STRENGTHS))}
        found = [m for m in self.motives.values() if m.owner == owner and (self.motive_live(m) or (not live_only and m.active))]
        return sorted(found, key=lambda m: (m.scope != "underlying", rank[m.strength], m.id))

    def add_motive(
        self,
        owner: str,
        text: str,
        *,
        scope: str = "underlying",
        kind: str = "want",
        strength: str = "leaning",
        moved_by: Iterable[str] = (),
        resists: Iterable[str] = (),
        tells: Iterable[str] = (),
        disclosure: str = "hidden",
        source: str = "generated",
        turn: int = 0,
    ) -> Motive:
        """Record a motive. A person has at most two lasting motives and one scene motive at a time, and at most one
        `absolute` one (fixed for the life of the game: underlying, and written ahead of play)."""
        ent = self._entity_or_error(owner)
        if ent.kind != "npc":
            raise WorldError(f"only people have motives, and {ent.name} is a {ent.kind}")
        for label, value, allowed in (
            ("scope", scope, MOTIVE_SCOPES), ("kind", kind, MOTIVE_KINDS), ("strength", strength, MOTIVE_STRENGTHS),
            ("disclosure", disclosure, DISCLOSURES), ("source", source, MOTIVE_SOURCES),
        ):  # fmt: skip
            if value not in allowed:
                raise WorldError(f"motive {label} must be one of {', '.join(allowed)}, got {value!r}")
        text = _clean_motive_text(text)
        if strength == "absolute":
            if scope != "underlying":
                raise WorldError("an absolute motive must be underlying: a scene motive passes, an absolute one never does")
            if source not in ABSOLUTE_SOURCES:
                raise WorldError("an absolute motive is written ahead of play and cannot be added in play")
            if any(m.strength == "absolute" for m in self.motives_of(owner, live_only=False)):
                raise WorldError(f"{ent.name} already has an absolute motive; a person has at most one")
        live = self.motives_of(owner)
        limit = MAX_UNDERLYING_MOTIVES if scope == "underlying" else MAX_SCENE_MOTIVES
        if sum(m.scope == scope for m in live) >= limit:
            raise WorldError(f"{ent.name} already has {limit} {scope} motive{'s' if limit > 1 else ''}")
        if scope == "scene" and self.scene.location is None:
            raise WorldError("a scene motive needs a recorded scene location; set the scene first")
        motive = Motive(
            self._new_id("m"), owner, text, scope, kind, strength,
            _clean_phrases(moved_by, "moved_by"), _clean_phrases(resists, "resists"), _clean_phrases(tells, "tells"),
            disclosure, "active", None, source, turn,
            self.scene.location if scope == "scene" else None, self.time,
        )  # fmt: skip
        self.motives[motive.id] = motive
        self._touch()
        return motive

    def _changeable_motive(self, motive_id: str) -> Motive:
        """The motive to change, or the reason it cannot be: unknown, finished, or absolute (fixed for the game)."""
        motive = self.motives.get(motive_id)
        if motive is None:
            raise WorldError(f"unknown motive {motive_id!r}")
        if motive.strength == "absolute":
            raise WorldError(
                f"motive {motive_id} is absolute: it is a deep property of the person and nothing the party does "
                "changes it. Play it as it is"
            )
        if not motive.active:
            raise WorldError(f"motive {motive_id} is already {motive.status}")
        return motive

    def shift_motive(
        self,
        motive_id: str,
        *,
        text: str | None = None,
        kind: str | None = None,
        strength: str | None = None,
        moved_by: Iterable[str] | None = None,
        resists: Iterable[str] | None = None,
        tells: Iterable[str] | None = None,
        source: str = "play",
        turn: int = 0,
    ) -> Motive:
        """Change a motive because of what happened: the old one is kept as superseded and a new one takes its place
        (same person, scope and moment, and what the player has learned of it). Absolute motives cannot change."""
        old = self._changeable_motive(motive_id)
        if not self.motive_live(old):
            raise WorldError(f"motive {motive_id} was for a scene that is over")
        if strength == "absolute":
            raise WorldError("a motive cannot become absolute in play")
        for label, value, allowed in (("kind", kind, MOTIVE_KINDS), ("strength", strength, MOTIVE_STRENGTHS)):
            if value is not None and value not in allowed:
                raise WorldError(f"motive {label} must be one of {', '.join(allowed)}, got {value!r}")
        if source not in MOTIVE_SOURCES:
            raise WorldError(f"motive source must be one of {', '.join(MOTIVE_SOURCES)}, got {source!r}")
        fields = {
            "text": old.text if text is None else _clean_motive_text(text),
            "kind": kind or old.kind,
            "strength": strength or old.strength,
            "moved_by": old.moved_by if moved_by is None else _clean_phrases(moved_by, "moved_by"),
            "resists": old.resists if resists is None else _clean_phrases(resists, "resists"),
            "tells": old.tells if tells is None else _clean_phrases(tells, "tells"),
        }
        if all(getattr(old, name) == value for name, value in fields.items()):
            raise WorldError(f"motive {motive_id} would not change: give a new text, kind, strength or levers")
        new = Motive(
            self._new_id("m"), old.owner, scope=old.scope, disclosure=old.disclosure, source=source, turn=turn,
            scene_location=old.scene_location, set_at=old.set_at, **fields,
        )  # fmt: skip
        old.status, old.superseded_by = "superseded", new.id
        self.motives[new.id] = new
        self._touch()
        return new

    def resolve_motive(self, motive_id: str, outcome: str) -> Motive:
        """The motive is over: the person got what they wanted (`satisfied`) or can no longer have it (`frustrated`)."""
        if outcome not in ("satisfied", "frustrated"):
            raise WorldError(f"outcome must be satisfied or frustrated, got {outcome!r}")
        motive = self._changeable_motive(motive_id)
        motive.status = outcome
        self._touch()
        return motive

    def disclose_motive(self, motive_id: str, level: str = "hinted") -> bool:
        """The player has seen a tell of this motive. Returns False if it was already hinted or known. (Turning a
        motive into something the player knows comes with the compendium, docs/ROLEPLAY.md 8.)"""
        if level != "hinted":
            raise WorldError(f"disclosure can only be set to hinted for now, got {level!r}")
        motive = self.motives.get(motive_id)
        if motive is None:
            raise WorldError(f"unknown motive {motive_id!r}")
        if not motive.active:
            raise WorldError(f"motive {motive_id} is already {motive.status}")
        if motive.disclosure != "hidden":
            return False
        motive.disclosure = "hinted"
        self._touch()
        return True

    # ---- change helpers ----------------------------------------------------------------

    def _entity_or_error(self, entity_id: str) -> Entity:
        ent = self.entities.get(entity_id)
        if ent is None:
            raise WorldError(f"unknown entity {entity_id!r}")
        return ent

    def _check_names_free(self, names: list[str], owner: str | None) -> None:
        seen: set[str] = set()
        for name in names:
            norm = normalize_name(name)
            if not norm:
                raise WorldError(f"{name!r} is not a usable name")
            existing = self._by_name.get(norm)
            if norm in seen or (existing and existing != owner):
                who = self.entities[existing].name if existing else name
                raise WorldError(f"the name {name!r} is already used by {who!r}; use that entity instead")
            seen.add(norm)

    def _check_fact(
        self, text: str, about: Iterable[str], aspect: str | None, disclosure: str, source: str
    ) -> tuple[str, list[str]]:
        text = " ".join(str(text).split()) if isinstance(text, str) else ""
        if not text:
            raise WorldError("fact text is empty")
        words = word_count(text)
        if words > FACT_WORDS_LIMIT:
            raise WorldError(
                f"fact is {words} words; keep each fact to one claim of about {MAX_FACT_WORDS} words "
                f"(never more than {FACT_WORDS_LIMIT}); split it into two facts"
            )
        if words < MIN_FACT_WORDS:
            raise WorldError("fact must be a full declarative sentence")
        if disclosure not in DISCLOSURES:
            raise WorldError(f"disclosure must be one of {', '.join(DISCLOSURES)}, got {disclosure!r}")
        if source not in SOURCES:
            raise WorldError(f"source must be one of {', '.join(SOURCES)}, got {source!r}")
        about_ids: list[str] = []
        for eid in about:
            if eid not in self.entities:
                raise WorldError(f"unknown entity {eid!r}; create it before recording facts about it")
            if eid not in about_ids:
                about_ids.append(eid)
        if not about_ids:
            raise WorldError("a fact must be about at least one entity")
        if len(about_ids) > MAX_ABOUT:
            raise WorldError(f"a fact can mention at most {MAX_ABOUT} entities")
        if aspect is not None and aspect not in ASPECTS[self.entities[about_ids[0]].kind] + SERVER_ASPECTS:
            kind = self.entities[about_ids[0]].kind
            raise WorldError(f"aspect {aspect!r} is not valid for a {kind}; use one of {', '.join(ASPECTS[kind])}")
        return text, about_ids

    def _check_duplicate_and_cap(self, text: str, subject: str, replacing: Fact | None) -> None:
        dup = self._text_keys.get((subject, normalize_text(text)))
        if dup and (replacing is None or dup != replacing.id):
            raise WorldError(f"that is already recorded as fact {dup}")
        if replacing is None:
            active = sum(1 for f in self.facts_about(subject) if f.subject == subject)
            if active >= MAX_ENTITY_FACTS:
                name = self.entities[subject].name
                raise WorldError(f"{name} already has {MAX_ENTITY_FACTS} facts; supersede or refine an existing one")

    def _insert_fact(
        self, text: str, about: list[str], aspect: str | None, disclosure: str, source: str, turn: int
    ) -> Fact:
        fact = Fact(
            self._new_id("f"), text, about, disclosure, source, turn, self.time, aspect,
            revealed_turn=turn if disclosure == "known" else None,
        )  # fmt: skip
        if disclosure == "known" and source != "seed":  # what the player set up in Session 0 is never "new"
            fact.learned_seq = self._next_learned()
        self.facts[fact.id] = fact
        self._index_fact(fact)
        self._mark_discovered(fact)
        self._touch()
        return fact

    def _next_learned(self) -> int:
        self.learn_seq += 1
        return self.learn_seq

    def _mark_discovered(self, fact: Fact) -> None:
        if fact.disclosure == "known":
            for eid in fact.about:
                if self.entities[eid].kind != "item":  # a key item is discovered by learning of it or having it
                    self.entities[eid].discovered = True

    # ---- copying and saving ------------------------------------------------------------

    def copy(self) -> "World":
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time.to_dict(),
            "scene": {"location": self.scene.location, "present": list(self.scene.present)},
            "processed_through": self.processed_through,
            "version": self.version,
            "reported_minutes": self.reported_minutes,
            "time_log": [dict(e) for e in self.time_log],
            "corrections": [dict(c) for c in self.corrections],
            "digests": [d.to_dict() for d in sorted(self.digests.values(), key=lambda d: d.start)],
            "next_id": dict(self.next_id),
            "learn_seq": self.learn_seq,
            "entities": [e.to_dict() for e in self.entities.values()],
            "routes": [r.to_dict() for r in self.routes.values()],
            "attempts": [a.to_dict() for a in self.attempts.values()],
            "root": self.root,
            "facts": [f.to_dict() for f in self.facts.values()],
            "motives": [m.to_dict() for m in self.motives.values()],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "World":
        """Rebuild a world from a save. Checks structure and references, but not the content caps
        (a save must still load if the caps were tightened since it was written)."""
        if data is None:
            return cls()
        try:
            return cls._load(data)
        except WorldError as exc:
            raise CorruptSave(f"world: {exc}") from None
        except (KeyError, TypeError, AttributeError) as exc:
            raise CorruptSave(f"world: malformed ({type(exc).__name__}: {exc})") from None

    @classmethod
    def _load(cls, data: Any) -> "World":
        if not isinstance(data, dict):
            raise WorldError("must be an object or null")
        world = cls()
        world.time = WorldTime.from_dict(data["time"])
        processed, version = data["processed_through"], data["version"]
        for label, value in (("processed_through", processed), ("version", version)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise WorldError(f"{label} must be a non-negative integer")
        world.processed_through, world.version = processed, version
        reported = data["reported_minutes"] if "reported_minutes" in data else data.get("reported_hours", 0) * MINUTES_PER_HOUR
        if isinstance(reported, bool) or not isinstance(reported, int) or reported < 0:
            raise WorldError("reported_minutes must be a non-negative integer")
        world.reported_minutes = reported
        for entry in data.get("time_log", []):
            if not (
                isinstance(entry, dict) and isinstance(entry.get("turn"), int) and isinstance(entry.get("minutes"), int)
                and isinstance(entry.get("why"), str)
            ):
                raise WorldError("time_log must be a list of objects with turn, minutes and why")
            world.time_log.append({"turn": entry["turn"], "minutes": entry["minutes"], "why": entry["why"]})
        for note in data.get("corrections", []):
            if not isinstance(note, dict) or not isinstance(note["text"], str) or not isinstance(note["turn"], int):
                raise WorldError("corrections must be objects with text and turn")
            world.corrections.append({"text": note["text"], "turn": note["turn"]})
        last_end = 0
        for raw in data.get("digests", []):  # saves from before digests have none
            try:
                digest = Digest.from_dict(raw)
            except ValueError as exc:
                raise WorldError(str(exc)) from None
            if digest.start < last_end:
                raise WorldError("digests must not overlap")
            world.digests[digest.start] = digest
            last_end = digest.end

        for raw in data["entities"]:
            ent = Entity(
                raw["id"], raw["name"], raw["kind"], list(raw["aliases"]), raw["parent"], bool(raw["discovered"])
            )
            if raw.get("look") is not None:  # saves from before looks have none
                try:
                    ent.look = Look.from_dict(raw["look"])
                except ValueError as exc:
                    raise WorldError(f"entity {ent.id} has a bad look: {exc}") from None
            if raw.get("portrait") is not None:  # saves from before portraits have none
                try:
                    ent.portrait = Portrait.from_dict(raw["portrait"])
                except CorruptSave as exc:
                    raise WorldError(f"entity {ent.id} has a bad portrait: {exc}") from None
            if raw.get("holding") is not None:  # saves from before key items have none
                ent.holding = Holding.from_dict(raw["holding"])
            if raw.get("scale") is not None:  # saves from before the clock counted minutes have none
                if raw["scale"] not in SCALES or ent.kind != "location":
                    raise WorldError(f"entity {ent.id} has a bad scale {raw['scale']!r}")
                ent.scale = raw["scale"]
            # Before the map existed nothing recorded where the party had been: a place it had been told about counts.
            ent.visited = bool(raw["visited"]) if "visited" in raw else ent.kind == "location" and ent.discovered
            if ent.kind == "item" and ent.holding is None:
                ent.holding = Holding()
            if ent.holding is not None and ent.kind != "item":
                raise WorldError(f"entity {ent.id} is a {ent.kind} but has a holding")
            if not _ENTITY_ID.match(str(ent.id)) or ent.id in world.entities:
                raise WorldError(f"bad or repeated entity id {ent.id!r}")
            if ent.kind not in KINDS or not isinstance(ent.name, str) or not ent.name.strip():
                raise WorldError(f"entity {ent.id} has a bad name or kind")
            if ent.look is not None and ent.kind not in LOOK_KINDS:
                raise WorldError(f"entity {ent.id} is a {ent.kind} but has a look")
            if ent.portrait is not None and ent.kind not in LOOK_KINDS:
                raise WorldError(f"entity {ent.id} is a {ent.kind} but has a portrait")
            world.entities[ent.id] = ent
        for ent in world.entities.values():
            if ent.parent is not None and ent.parent not in world.entities:
                raise WorldError(f"entity {ent.id} has unknown parent {ent.parent!r}")
            seen, cur = {ent.id}, ent.parent
            while cur:  # a parent chain must end
                if cur in seen:
                    raise WorldError(f"parent loop at entity {ent.id}")
                seen.add(cur)
                cur = world.entities[cur].parent
        names: set[str] = set()
        for ent in world.entities.values():
            for name in ent.names():
                norm = normalize_name(name)
                if norm in names:
                    raise WorldError(f"name {name!r} is used by more than one entity")
                names.add(norm)

        for raw in data["facts"]:
            fact = Fact(
                raw["id"], raw["text"], list(raw["about"]), raw["disclosure"], raw["source"], raw["turn"],
                WorldTime.from_dict(raw["created_at"]), raw["aspect"], raw["revealed_turn"],
                WorldTime.from_dict(raw["from_time"]) if raw["from_time"] else None,
                WorldTime.from_dict(raw["until_time"]) if raw["until_time"] else None,
                raw["status"], raw["superseded_by"],
            )  # fmt: skip
            fact.learned_seq = _count(raw.get("learned_seq", 0), f"fact {fact.id} learned_seq")
            via = raw.get("via", [])
            if not isinstance(via, list) or not all(isinstance(v, str) and v.strip() for v in via):
                raise WorldError(f"fact {fact.id} has a bad via")
            fact.via = tuple(via)
            if not _FACT_ID.match(str(fact.id)) or fact.id in world.facts:
                raise WorldError(f"bad or repeated fact id {fact.id!r}")
            if not isinstance(fact.text, str) or not fact.text.strip():
                raise WorldError(f"fact {fact.id} has no text")
            if fact.disclosure not in DISCLOSURES or fact.source not in SOURCES or fact.status not in STATUSES:
                raise WorldError(f"fact {fact.id} has a bad disclosure, source or status")
            if not fact.about or any(e not in world.entities for e in fact.about):
                raise WorldError(f"fact {fact.id} is about an unknown or missing entity")
            world.facts[fact.id] = fact
        for fact in world.facts.values():
            if (fact.status == "superseded") != (fact.superseded_by is not None):
                raise WorldError(f"fact {fact.id} has inconsistent superseded state")
            if fact.superseded_by is not None and fact.superseded_by not in world.facts:
                raise WorldError(f"fact {fact.id} is superseded by unknown {fact.superseded_by!r}")

        scene = data["scene"]
        for eid in [scene["location"] or "", *scene["present"]]:
            if eid and eid not in world.entities:
                raise WorldError(f"scene refers to unknown entity {eid!r}")
        world.scene = Scene(scene["location"], list(scene["present"]))

        for raw in data.get("motives", []):  # saves from before motives have none
            motive = _load_motive(raw, world)
            if motive.id in world.motives:
                raise WorldError(f"repeated motive id {motive.id!r}")
            world.motives[motive.id] = motive
        for motive in world.motives.values():
            if (motive.status == "superseded") != (motive.superseded_by is not None) or (
                motive.superseded_by is not None and motive.superseded_by not in world.motives
            ):
                raise WorldError(f"motive {motive.id} has inconsistent superseded state")

        for raw in data.get("routes", []):  # saves from before routes have none
            route = _load_route(raw, world)
            if route.id in world.routes:
                raise WorldError(f"repeated route id {route.id!r}")
            world.routes[route.id] = route
        for raw in data.get("attempts", []):  # saves from before attempts have none
            attempt = _load_attempt(raw, world)
            if attempt.id in world.attempts:
                raise WorldError(f"repeated attempt id {attempt.id!r}")
            world.attempts[attempt.id] = attempt
        root = data.get("root")  # saves from before the world had a single top have none
        if root is not None:
            if root not in world.entities or world.entities[root].kind != "location" or world.entities[root].parent:
                raise WorldError("root must be a place with nothing above it")
            world.root = root
        if world.scene.location in world.entities:
            world.entities[world.scene.location].visited = True
        next_id = data["next_id"]
        for prefix, ids in (
            ("f", world.facts), ("e", world.entities), ("m", world.motives), ("r", world.routes), ("a", world.attempts)
        ):
            n = next_id.get(prefix, 1) if prefix in ("m", "r", "a") else next_id[prefix]
            if isinstance(n, bool) or not isinstance(n, int) or n <= max((int(i[1:]) for i in ids), default=0):
                raise WorldError(f"next_id.{prefix} must be above every existing id")
            world.next_id[prefix] = n
        world.learn_seq = _count(data.get("learn_seq", 0), "learn_seq")
        if world.learn_seq < max((f.learned_seq for f in world.facts.values()), default=0):
            raise WorldError("learn_seq must be at least every fact's learned_seq")
        world._reindex()
        return world


def _load_attempt(raw: Any, world: "World") -> Attempt:
    """One attempt from a save: structure and references are checked, the content caps are not."""
    if not isinstance(raw, dict) or not re.match(r"^a\d+$", str(raw.get("id"))):
        raise WorldError("an attempt needs an id like a001")
    text = {k: raw.get(k, "") for k in ("who", "kind", "task", "failure", "reopens_if")}
    if not all(isinstance(v, str) for v in text.values()) or not text["who"].strip() or not text["task"].strip():
        raise WorldError(f"attempt {raw['id']} needs a character and a task")
    if text["kind"] not in attempt_kinds.KINDS or raw.get("status") not in attempt_kinds.STATUSES:
        raise WorldError(f"attempt {raw['id']} has a bad kind or status")
    if raw.get("scope", "character") not in attempt_kinds.SCOPES:
        raise WorldError(f"attempt {raw['id']} has a bad scope")
    if raw.get("about") not in world.entities:
        raise WorldError(f"attempt {raw['id']} is about an unknown entity")
    fact = raw.get("fact")
    if fact is not None and fact not in world.facts:
        raise WorldError(f"attempt {raw['id']} refers to an unknown fact")
    tries = _count(raw.get("tries", 1), f"attempt {raw['id']} tries")
    if tries < 1:
        raise WorldError(f"attempt {raw['id']} needs at least one try")
    return Attempt(
        raw["id"], text["who"], text["kind"], text["task"], raw["about"], raw["status"], tries,
        raw.get("scope", "character"), text["failure"], text["reopens_if"],
        WorldTime.from_dict(raw["reopens_at"]) if raw.get("reopens_at") else None, fact,
        _count(raw.get("turn", 0), f"attempt {raw['id']} turn"), WorldTime.from_dict(raw["at"]),
    )  # fmt: skip


def _load_route(raw: Any, world: "World") -> Route:
    """One route from a save: structure and references are checked, the content caps are not."""
    if not isinstance(raw, dict) or not re.match(r"^r\d+$", str(raw.get("id"))):
        raise WorldError("a route needs an id like r001")
    a, b, minutes = raw.get("a"), raw.get("b"), raw.get("minutes")
    if a not in world.entities or b not in world.entities or a == b:
        raise WorldError(f"route {raw['id']} must join two recorded places")
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1:
        raise WorldError(f"route {raw['id']} needs a positive number of minutes")
    how, source = raw.get("how", ""), raw.get("source", "improvised")
    if not isinstance(how, str) or source not in ROUTE_SOURCES:
        raise WorldError(f"route {raw['id']} has a bad description or source")
    block = Block.from_dict(raw["block"]) if raw.get("block") is not None else None
    return Route(raw["id"], a, b, minutes, how, source, block)


def _load_motive(raw: Any, world: "World") -> Motive:
    """One motive from a save: structure and references are checked, the content caps are not."""
    if not isinstance(raw, dict):
        raise WorldError("a motive must be an object")
    motive = Motive(
        raw["id"], raw["owner"], raw["text"], raw["scope"], raw["kind"], raw["strength"],
        tuple(raw["moved_by"]), tuple(raw["resists"]), tuple(raw["tells"]), raw["disclosure"], raw["status"],
        raw["superseded_by"], raw["source"], raw["turn"], raw["scene_location"], WorldTime.from_dict(raw["set_at"]),
    )  # fmt: skip
    label = f"motive {motive.id}"
    if not _MOTIVE_ID.match(str(motive.id)):
        raise WorldError(f"bad motive id {motive.id!r}")
    owner = world.entities.get(motive.owner)
    if owner is None or owner.kind != "npc":
        raise WorldError(f"{label} belongs to an unknown entity or one that is not a person")
    if not isinstance(motive.text, str) or not motive.text.strip():
        raise WorldError(f"{label} has no text")
    for value, allowed, name in (
        (motive.scope, MOTIVE_SCOPES, "scope"), (motive.kind, MOTIVE_KINDS, "kind"),
        (motive.strength, MOTIVE_STRENGTHS, "strength"), (motive.disclosure, DISCLOSURES, "disclosure"),
        (motive.status, MOTIVE_STATUSES, "status"), (motive.source, MOTIVE_SOURCES, "source"),
    ):  # fmt: skip
        if value not in allowed:
            raise WorldError(f"{label} has a bad {name}")
    for phrases in (motive.moved_by, motive.resists, motive.tells):
        if not all(isinstance(p, str) and p.strip() for p in phrases):
            raise WorldError(f"{label} has a bad list of phrases")
    if motive.strength == "absolute" and motive.scope != "underlying":
        raise WorldError(f"{label} is absolute but not underlying")
    if motive.scene_location is not None and motive.scene_location not in world.entities:
        raise WorldError(f"{label} refers to an unknown scene location")
    if motive.scope == "scene" and motive.scene_location is None:
        raise WorldError(f"{label} is a scene motive with no scene location")
    _count(motive.turn, f"{label} turn")
    return motive


def _clean_motive_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorldError("motive text must be a non-empty string")
    value = " ".join(value.split())
    n = word_count(value)
    if n < MIN_MOTIVE_WORDS:
        raise WorldError(f"motive text needs at least {MIN_MOTIVE_WORDS} words")
    if n > MOTIVE_WORDS_LIMIT:
        raise WorldError(f"motive text is {n} words; keep it to about {MAX_MOTIVE_WORDS}")
    return value


def _clean_phrases(values: Iterable[str], label: str) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise WorldError(f"{label} entries must be non-empty strings")
        value = " ".join(value.split())
        if len(value) > MAX_PHRASE_CHARS:
            raise WorldError(f"each {label} entry must be at most {MAX_PHRASE_CHARS} characters")
        if value not in out:
            out.append(value)
    if len(out) > MAX_MOTIVE_PHRASES:
        raise WorldError(f"at most {MAX_MOTIVE_PHRASES} {label} entries per motive")
    return tuple(out)


def _custody_text(name: str, event: str, end: str, had_before: bool, note: str) -> str:
    """The sentence that records a change of holding as a fact (docs/KEY_ITEMS.md 4.4)."""
    base = {
        "learned": f"The party has heard of {name}.",
        "acquired": f"The party has {name}{' again' if had_before else ''}.",
        "used": f"The party used up {name}.",
        "lost": f"The party lost {name}.",
    }[event]
    return f"{base} {note.rstrip('.')}." if note else base


def _count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorldError(f"{label} must be a non-negative integer")
    return value


def _clean_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorldError(f"{label} must be a non-empty string")
    value = " ".join(value.split())
    if len(value) > MAX_NAME_CHARS:
        raise WorldError(f"{label} is longer than {MAX_NAME_CHARS} characters")
    return value
