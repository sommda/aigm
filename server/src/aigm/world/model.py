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
from aigm.world.digest import Digest
from aigm.world.text import normalize_name, normalize_text, tokens, word_count

KINDS = ("location", "npc", "faction", "concept")
DISCLOSURES = ("hidden", "hinted", "known")
SOURCES = ("seed", "play", "generated", "improvised")
STATUSES = ("active", "superseded")

# Checklist slots a fact can fill (docs/WORLD.md 5.3). "location" is the union of the site and
# settlement lists; the curator's frontier logic refines which apply.
ASPECTS: dict[str, tuple[str, ...]] = {
    "location": (
        "approach", "discovery", "entry", "interior", "inhabitants", "history", "hazards",
        "connections", "secret", "layout", "leaders", "economy", "notable_places", "tensions",
    ),
    "npc": ("role", "appearance", "manner", "motivation", "relationships", "knowledge", "location"),
    "faction": ("goals", "leaders", "resources", "methods", "rivals", "presence", "history"),
    "concept": ("nature", "origin", "who_believes_it", "effects"),
}  # fmt: skip

MAX_FACT_WORDS = 40
MIN_FACT_WORDS = 3
MAX_ENTITY_FACTS = 40  # active facts per entity (counting facts where it is the subject)
MAX_ABOUT = 4
MAX_NAME_CHARS = 80
MAX_ALIASES = 8
HOURS_PER_DAY = 24

_FACT_ID = re.compile(r"^f\d+$")
_ENTITY_ID = re.compile(r"^e\d+$")


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

    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "aliases": list(self.aliases),
            "parent": self.parent, "discovered": self.discovered,
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
            "from_time": self.from_time.to_dict() if self.from_time else None,
            "until_time": self.until_time.to_dict() if self.until_time else None,
            "status": self.status, "superseded_by": self.superseded_by,
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
        self.next_id = {"f": 1, "e": 1}
        self.entities: dict[str, Entity] = {}
        self.facts: dict[str, Fact] = {}
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

    def add_fact(
        self,
        text: str,
        about: Iterable[str],
        *,
        aspect: str | None = None,
        disclosure: str = "hidden",
        source: str = "generated",
        turn: int = 0,
    ) -> Fact:
        text, about_ids = self._check_fact(text, about, aspect, disclosure, source)
        self._check_duplicate_and_cap(text, about_ids[0], replacing=None)
        return self._insert_fact(text, about_ids, aspect, disclosure, source, turn)

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
        self._mark_discovered(fact)
        self._touch()
        return True

    def set_scene(self, location: str | None, present: Iterable[str] = ()) -> None:
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

    def add_digest(self, digest: Digest) -> bool:
        """Record the digest of a turn. A turn keeps the first digest it gets; returns whether this one was added."""
        if digest.start in self.digests or any(d.start < digest.end and digest.start < d.end for d in self.digests.values()):
            return False
        self.digests[digest.start] = digest
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
        if words > MAX_FACT_WORDS:
            raise WorldError(f"fact is {words} words; keep each fact to one claim of at most {MAX_FACT_WORDS} words")
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
        self.facts[fact.id] = fact
        self._index_fact(fact)
        self._mark_discovered(fact)
        self._touch()
        return fact

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
            "entities": [e.to_dict() for e in self.entities.values()],
            "facts": [f.to_dict() for f in self.facts.values()],
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
            if not _ENTITY_ID.match(str(ent.id)) or ent.id in world.entities:
                raise WorldError(f"bad or repeated entity id {ent.id!r}")
            if ent.kind not in KINDS or not isinstance(ent.name, str) or not ent.name.strip():
                raise WorldError(f"entity {ent.id} has a bad name or kind")
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

        next_id = data["next_id"]
        for prefix, ids in (("f", world.facts), ("e", world.entities)):
            n = next_id[prefix]
            if isinstance(n, bool) or not isinstance(n, int) or n <= max((int(i[1:]) for i in ids), default=0):
                raise WorldError(f"next_id.{prefix} must be above every existing id")
            world.next_id[prefix] = n
        world._reindex()
        return world


def _clean_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorldError(f"{label} must be a non-empty string")
    value = " ".join(value.split())
    if len(value) > MAX_NAME_CHARS:
        raise WorldError(f"{label} is longer than {MAX_NAME_CHARS} characters")
    return value
