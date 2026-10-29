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

from aigm.errors import CorruptSave
from aigm.looks import Look, LookError, look_kind, validate
from aigm.portraits import Portrait
from aigm.world.digest import Digest
from aigm.world.text import normalize_name, normalize_text, tokens, word_count

KINDS = ("location", "npc", "faction", "concept")
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
}  # fmt: skip

# Aspects the party can plainly see on arriving at a place: a fact with one of these about the place the party is
# in is known to the player from the moment it exists, or from the moment the party gets there (docs/STATUS.md 5).
ARRIVAL_ASPECTS = ("overview", "items")

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
HOURS_PER_DAY = 24

_FACT_ID = re.compile(r"^f\d+$")
_MOTIVE_ID = re.compile(r"^m\d+$")
_ENTITY_ID = re.compile(r"^e\d+$")
LOOK_KINDS = ("npc", "location")  # the kinds of entity that have a Look


class WorldError(ValueError):
    """A change the world rules reject. The message is written to be shown to the model."""


@dataclass(frozen=True, order=True)
class WorldTime:
    """A moment on the in-world clock: day 1 is the first day of the adventure, hour is 0-23."""

    day: int = 1
    hour: int = 8

    def __post_init__(self) -> None:
        if isinstance(self.day, bool) or not isinstance(self.day, int) or self.day < 1:
            raise WorldError(f"day must be an integer of at least 1, got {self.day!r}")
        if isinstance(self.hour, bool) or not isinstance(self.hour, int) or not 0 <= self.hour < HOURS_PER_DAY:
            raise WorldError(f"hour must be an integer from 0 to 23, got {self.hour!r}")

    @property
    def total_hours(self) -> int:
        return (self.day - 1) * HOURS_PER_DAY + self.hour

    def plus(self, hours: int) -> "WorldTime":
        if isinstance(hours, bool) or not isinstance(hours, int) or hours < 0:
            raise WorldError(f"time can only move forward by whole hours, got {hours!r}")
        day, hour = divmod(self.total_hours + hours, HOURS_PER_DAY)
        return WorldTime(day + 1, hour)

    def to_dict(self) -> dict[str, int]:
        return {"day": self.day, "hour": self.hour}

    @classmethod
    def from_dict(cls, data: Any) -> "WorldTime":
        if not isinstance(data, dict):
            raise WorldError("time must be an object with day and hour")
        return cls(data.get("day"), data.get("hour"))  # type: ignore[arg-type]

    def __str__(self) -> str:
        return f"Day {self.day}, {self.hour:02d}:00"


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

    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "aliases": list(self.aliases),
            "parent": self.parent, "discovered": self.discovered,
            "look": self.look.to_dict() if self.look else None,
            "portrait": self.portrait.to_dict() if self.portrait else None,
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


class World:
    """The knowledge base of one game. Plain data in `entities` and `facts` (insertion ordered);
    the dictionaries beginning with an underscore are indexes rebuilt by `_reindex`."""

    def __init__(self) -> None:
        self.time = WorldTime()
        self.scene = Scene()
        self.processed_through = 0  # number of history messages the curator has digested
        self.version = 0  # bumped on every change; lets a background pass detect interference
        self.reported_hours = 0  # hours the GM moved the clock itself (set_scene) since the last pass
        self.corrections: list[dict[str, Any]] = []  # notes for the GM's next briefing: {"text", "turn"}
        self.digests: dict[int, Digest] = {}  # turn digests by the index of the turn's first message
        self.next_id = {"f": 1, "e": 1, "m": 1}
        self.learn_seq = 0  # last number given to a fact the player learned; only goes up
        self.entities: dict[str, Entity] = {}
        self.facts: dict[str, Fact] = {}
        self.motives: dict[str, Motive] = {}
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
        for ent in self.entities.values():
            self._index_entity(ent)
        for fact in self.facts.values():
            self._index_fact(fact)

    def _index_entity(self, ent: Entity) -> None:
        for name in ent.names():
            self._by_name[normalize_name(name)] = ent.id
        if ent.parent:
            self._children.setdefault(ent.parent, []).append(ent.id)

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
        ent = Entity(self._new_id("e"), name, kind, alias_list, parent)
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

    def set_look(self, entity_id: str, look: Look) -> Look:
        """Give a person their Look, or replace it (docs/LOOKS.md). The Look must pass the content rules."""
        ent = self._entity_or_error(entity_id)
        if ent.kind not in LOOK_KINDS:
            raise WorldError(f"{ent.name} is a {ent.kind}; only people and places have a look")
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
            raise WorldError(f"{ent.name} is a {ent.kind}; only people and places have a portrait")
        ent.portrait = portrait.copy()
        self._touch()
        return ent.portrait

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
            if eid != location and eid not in present_ids:
                present_ids.append(eid)
        self.scene = Scene(location, present_ids)
        for eid in present_ids:  # the player can see who is there, so a person has been met even with no facts yet
            if self.entities[eid].kind == "npc":
                self.entities[eid].discovered = True
        if location is not None:  # arriving: what can be seen there is now known
            for fact in self.facts_about(location):
                if fact.aspect in ARRIVAL_ASPECTS and fact.subject == location:
                    self.reveal(fact.id, turn)
        self._touch()

    def advance_time(self, hours: int, *, reported: bool = False) -> WorldTime:
        """Move the clock forward. `reported` marks time the GM declared itself, so the curator
        does not count the same hours again when it reads the narration."""
        self.time = self.time.plus(hours)
        if reported:
            self.reported_hours += hours
        self._touch()
        return self.time

    def start_clock(self, hour: int) -> WorldTime:
        """Set the time of day the adventure opens at (day 1). Only possible before anything is recorded."""
        if self.facts:
            raise WorldError("the clock can only be started before anything is recorded")
        self.time = WorldTime(1, hour)
        self._touch()
        return self.time

    def settle_reported_hours(self, narrated_hours: int) -> int:
        """The curator read `narrated_hours` of elapsed time in the narration. Advance the clock
        by whatever the GM has not already reported, then start counting afresh."""
        extra = max(0, narrated_hours - self.reported_hours)
        self.reported_hours = 0
        if extra:
            self.advance_time(extra)
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
        elapsed = self.time.total_hours - motive.set_at.total_hours
        return motive.scene_location == self.scene.location and elapsed < SCENE_MOTIVE_HOURS

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
        if aspect is not None and aspect not in ASPECTS[self.entities[about_ids[0]].kind]:
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
            "reported_hours": self.reported_hours,
            "corrections": [dict(c) for c in self.corrections],
            "digests": [d.to_dict() for d in sorted(self.digests.values(), key=lambda d: d.start)],
            "next_id": dict(self.next_id),
            "learn_seq": self.learn_seq,
            "entities": [e.to_dict() for e in self.entities.values()],
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
        reported = data.get("reported_hours", 0)
        if isinstance(reported, bool) or not isinstance(reported, int) or reported < 0:
            raise WorldError("reported_hours must be a non-negative integer")
        world.reported_hours = reported
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

        next_id = data["next_id"]
        for prefix, ids in (("f", world.facts), ("e", world.entities), ("m", world.motives)):
            n = next_id.get(prefix, 1) if prefix == "m" else next_id[prefix]
            if isinstance(n, bool) or not isinstance(n, int) or n <= max((int(i[1:]) for i in ids), default=0):
                raise WorldError(f"next_id.{prefix} must be above every existing id")
            world.next_id[prefix] = n
        world.learn_seq = _count(data.get("learn_seq", 0), "learn_seq")
        if world.learn_seq < max((f.learned_seq for f in world.facts.values()), default=0):
            raise WorldError("learn_seq must be at least every fact's learned_seq")
        world._reindex()
        return world


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
