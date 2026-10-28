"""Declarative changes to a world, as produced by a curator pass.

A pass works on a snapshot and emits these; the same ops are then applied to the live world,
which may have moved on meanwhile (the GM's `establish` calls). Ops name entities rather than
using ids, and applying one that no longer makes sense (a duplicate, an entity that has been
merged) skips it instead of failing, so replaying them is safe."""

from dataclasses import dataclass, field

from aigm.world.digest import Digest
from aigm.world.model import World, WorldError
from aigm.world.text import normalize_text


@dataclass
class AddEntity:
    name: str
    kind: str
    aliases: tuple[str, ...] = ()
    parent: str | None = None  # name or id


@dataclass
class AddAlias:
    entity: str  # name or id
    alias: str


@dataclass
class AddFact:
    text: str
    about: tuple[str, ...]  # names or ids; the first is the subject
    aspect: str | None = None
    disclosure: str = "hidden"
    source: str = "play"
    turn: int = 0
    via: tuple[str, ...] = ()  # party members whose starting knowledge it is


@dataclass
class Supersede:
    old_id: str
    text: str
    aspect: str | None = None
    disclosure: str | None = None
    source: str = "play"
    turn: int = 0
    allow_known: bool = False


@dataclass
class Reveal:
    fact_id: str
    turn: int = 0


@dataclass
class SetScene:
    location: str | None  # name or id
    present: tuple[str, ...] | None = None  # None: leave who is present alone, unless the place changed
    turn: int = 0


@dataclass
class SettleTime:
    """The narration covered `hours` of in-world time, of which the GM may have reported some."""

    hours: int


@dataclass
class StartClock:
    """Set the opening hour of day 1, before anything has been recorded."""

    hour: int


@dataclass
class Correct:
    text: str
    turn: int = 0


@dataclass
class MarkProcessed:
    count: int


@dataclass
class AddDigest:
    digest: Digest
    replace_stale: bool = False  # drop digests that overlap this turn but no longer cover its messages


@dataclass
class AddMotive:
    owner: str  # name or id of a person
    text: str
    scope: str = "underlying"
    kind: str = "want"
    strength: str = "leaning"
    moved_by: tuple[str, ...] = ()
    resists: tuple[str, ...] = ()
    tells: tuple[str, ...] = ()
    source: str = "generated"
    turn: int = 0


@dataclass
class ShiftMotive:
    motive_id: str
    text: str | None = None
    kind: str | None = None
    strength: str | None = None
    moved_by: tuple[str, ...] | None = None
    resists: tuple[str, ...] | None = None
    tells: tuple[str, ...] | None = None
    source: str = "play"
    turn: int = 0


@dataclass
class ResolveMotive:
    motive_id: str
    outcome: str  # satisfied | frustrated


@dataclass
class DiscloseMotive:
    motive_id: str
    level: str = "hinted"


Op = (
    AddEntity | AddAlias | AddFact | Supersede | Reveal | SetScene | SettleTime | StartClock | Correct | MarkProcessed
    | AddDigest | AddMotive | ShiftMotive | ResolveMotive | DiscloseMotive
)


@dataclass
class Applied:
    ops: list[Op] = field(default_factory=list)  # the ones that took effect
    skipped: list[str] = field(default_factory=list)  # why the others did not


def apply_ops(world: World, ops: list[Op]) -> Applied:
    """Apply ops in order, skipping any that cannot apply. Mutates `world`."""
    result = Applied()
    for op in ops:
        try:
            if _apply(world, op):
                result.ops.append(op)
        except WorldError as exc:
            result.skipped.append(f"{type(op).__name__}: {exc}")
    return result


def _ids(world: World, refs: tuple[str, ...]) -> list[str]:
    ids = []
    for ref in refs:
        ent = world.resolve(ref)
        if ent is None:
            raise WorldError(f"unknown entity {ref!r}")
        ids.append(ent.id)
    return ids


def _apply(world: World, op: Op) -> bool:
    """Returns whether the op changed anything."""
    if isinstance(op, AddEntity):
        existing = world.find(op.name)
        if existing:
            if existing.kind != op.kind:
                raise WorldError(f"{op.name!r} already exists as a {existing.kind}")
            changed = False
            for alias in op.aliases:
                if world.find(alias) is None:
                    world.add_alias(existing.id, alias)
                    changed = True
            return changed
        parent = None
        if op.parent:
            parent_ent = world.resolve(op.parent)
            parent = parent_ent.id if parent_ent else None  # a vanished parent is not fatal
        aliases = [a for a in op.aliases if world.find(a) is None]
        world.add_entity(op.name, op.kind, aliases=aliases, parent=parent)
        return True
    if isinstance(op, AddAlias):
        ent = world.resolve(op.entity)
        if ent is None:
            raise WorldError(f"unknown entity {op.entity!r}")
        if world.find(op.alias) is not None:
            return False
        world.add_alias(ent.id, op.alias)
        return True
    if isinstance(op, AddFact):
        about = _ids(world, op.about)
        if not about:
            raise WorldError("fact has no entities")
        if world.similar_fact(op.text, about[0]):
            return False
        world.add_fact(
            op.text, about, aspect=op.aspect, disclosure=op.disclosure, source=op.source, turn=op.turn, via=op.via
        )
        return True
    if isinstance(op, Supersede):
        old = world.fact(op.old_id)
        if old is None or not old.active:
            raise WorldError(f"fact {op.old_id} is gone or already replaced")
        world.supersede(
            op.old_id, op.text, aspect=op.aspect, disclosure=op.disclosure, source=op.source, turn=op.turn,
            allow_known=op.allow_known,
        )  # fmt: skip
        return True
    if isinstance(op, Reveal):
        return world.reveal(op.fact_id, op.turn)
    if isinstance(op, SetScene):
        loc = None
        if op.location is not None:
            ent = world.resolve(op.location)
            if ent is None:
                raise WorldError(f"unknown place {op.location!r}")
            loc = ent.id
        moved = loc != world.scene.location
        if op.present is not None:
            present = [e for e in (world.resolve(r) for r in op.present) if e is not None]
            ids = [e.id for e in present]
        else:
            ids = [] if moved else list(world.scene.present)
        world.set_scene(loc, ids, op.turn)
        return True
    if isinstance(op, SettleTime):
        world.settle_reported_hours(op.hours)
        return True
    if isinstance(op, StartClock):
        world.start_clock(op.hour)
        return True
    if isinstance(op, Correct):
        world.add_correction(op.text, op.turn)
        return True
    if isinstance(op, MarkProcessed):
        if op.count > world.processed_through:
            world.mark_processed(op.count)
            return True
        return False
    if isinstance(op, AddDigest):
        return world.add_digest(op.digest, op.replace_stale)
    if isinstance(op, AddMotive):
        owner = world.resolve(op.owner)
        if owner is None:
            raise WorldError(f"unknown entity {op.owner!r}")
        key = normalize_text(op.text)
        if any(normalize_text(m.text) == key for m in world.motives_of(owner.id, live_only=False)):
            return False  # the same motive again
        world.add_motive(
            owner.id, op.text, scope=op.scope, kind=op.kind, strength=op.strength, moved_by=op.moved_by,
            resists=op.resists, tells=op.tells, source=op.source, turn=op.turn,
        )  # fmt: skip
        return True
    if isinstance(op, ShiftMotive):
        world.shift_motive(
            op.motive_id, text=op.text, kind=op.kind, strength=op.strength, moved_by=op.moved_by, resists=op.resists,
            tells=op.tells, source=op.source, turn=op.turn,
        )  # fmt: skip
        return True
    if isinstance(op, ResolveMotive):
        world.resolve_motive(op.motive_id, op.outcome)
        return True
    if isinstance(op, DiscloseMotive):
        return world.disclose_motive(op.motive_id, op.level)
    raise WorldError(f"unknown op {op!r}")
