"""The compendium: what the player has learned about the world (docs/COMPENDIUM.md).

A filtered, read-only view of the world knowledge base, plus the player's reading state. This is the only code that
turns world data into something a client may see, so the rule lives here and nowhere else: a fact is shown only if it
is `known` and `active`, an entity only if it has such a fact (or, for a person the player has met, a Look). Hidden
and hinted facts, undiscovered entities, aliases the player has not met and every internal field never leave this
module."""

import re
from dataclasses import dataclass, field
from typing import Any

from aigm.errors import CorruptSave
from aigm.world import ASPECTS, Entity, Fact, World

CATEGORIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "locations": ("Locations", ("location",)),
    "characters": ("Characters", ("npc",)),
    "other": ("Other", ("faction", "concept")),
}
STATUSES = ("new", "updated", "unseen")
SORTS = ("name", "recent", "tree")
SUMMARY_ASPECTS = ("overview", "role", "nature", "goals", "approach", "discovery", "history")
SUMMARY_CHARS = 140
MAX_RELATED = 12


@dataclass
class Compendium:
    """What the player has already looked at. Facts learned up to `all_through`, or up to an entity's own mark in
    `seen`, count as seen on that entity's page. Marks only ever go up."""

    all_through: int = 0
    seen: dict[str, int] = field(default_factory=dict)

    def copy(self) -> "Compendium":
        return Compendium(self.all_through, dict(self.seen))

    def mark(self, entity_id: str) -> int:
        return max(self.all_through, self.seen.get(entity_id, 0))

    def mark_seen(self, world: World, entity_ids: list[str]) -> None:
        for eid in entity_ids:
            if _visible(world, eid):
                self.seen[eid] = max(self.seen.get(eid, 0), world.learn_seq)

    def mark_all(self, world: World) -> None:
        self.all_through = max(self.all_through, world.learn_seq)

    def to_dict(self) -> dict[str, Any]:
        return {"all_through": self.all_through, "seen": dict(self.seen)}

    @classmethod
    def from_dict(cls, data: Any) -> "Compendium":
        if data is None:  # saves from before the compendium
            return cls()
        if not isinstance(data, dict):
            raise CorruptSave("compendium must be an object")
        through, seen = data.get("all_through", 0), data.get("seen", {})
        if not _count(through) or not isinstance(seen, dict) or not all(
            isinstance(k, str) and _count(v) for k, v in seen.items()
        ):
            raise CorruptSave("compendium must hold non-negative whole numbers")
        return cls(through, dict(seen))


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


# ---- the filter ----------------------------------------------------------------------------


def known_facts(world: World, entity_id: str) -> list[Fact]:
    """The facts a player may see about an entity: known and not superseded, oldest learned first."""
    facts = world.facts_about(entity_id, disclosure="known")
    return sorted(facts, key=lambda f: (f.learned_seq, f.id))


def _visible(world: World, entity_id: str) -> bool:
    ent = world.entities.get(entity_id)
    return ent is not None and ent.discovered and (bool(known_facts(world, entity_id)) or _look_only(ent))


def _look_only(entity: Entity) -> bool:
    """A person who has been met but about whom nothing is known yet still has an entry: their description."""
    return entity.kind == "npc" and entity.look is not None


def _look(entity: Entity) -> dict[str, str] | None:
    look = entity.look
    return {"summary": look.summary, "description": look.description} if look else None


def category_of(entity: Entity) -> str | None:
    return next((cid for cid, (_, kinds) in CATEGORIES.items() if entity.kind in kinds), None)


def visible_aliases(entity: Entity, facts: list[Fact]) -> list[str]:
    """Aliases the player has met: those that appear in one of the entity's known facts."""
    text = " ".join(f.text for f in facts).casefold()
    return [a for a in entity.aliases if re.search(rf"(?<!\w){re.escape(a.casefold())}(?!\w)", text)]


def _ref(world: World, entity_id: str) -> dict[str, str]:
    return {"id": entity_id, "name": world.entities[entity_id].name}


def _parent(world: World, entity: Entity) -> dict[str, str] | None:
    return _ref(world, entity.parent) if entity.parent and _visible(world, entity.parent) else None


def _path(world: World, entity: Entity) -> list[dict[str, str]]:
    """The discovered ancestors, outermost first; it stops at the first one the player does not know."""
    out = []
    cur = entity.parent
    while cur and _visible(world, cur):
        out.append(_ref(world, cur))
        cur = world.entities[cur].parent
    return out[::-1]


def _status(facts: list[Fact], mark: int) -> tuple[str | None, int]:
    unseen = sum(1 for f in facts if f.learned_seq > mark)
    if not unseen:
        return None, 0
    return ("new" if unseen == len(facts) else "updated"), unseen


def _learned_turn(fact: Fact) -> int:
    return fact.revealed_turn if fact.revealed_turn is not None else fact.turn


def _aspect_label(aspect: str | None) -> str | None:
    return aspect.replace("_", " ").capitalize() if aspect else None


def _summary(entity: Entity, facts: list[Fact]) -> str:
    if not facts and entity.look:
        return entity.look.summary
    own = [f for f in facts if f.subject == entity.id] or facts
    pick = next((f for a in SUMMARY_ASPECTS for f in own if f.aspect == a), own[0])
    text = pick.text
    if len(text) > SUMMARY_CHARS:
        text = text[:SUMMARY_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


# ---- responses -----------------------------------------------------------------------------


def _visible_in(world: World, category: str) -> list[Entity]:
    kinds = CATEGORIES[category][1]
    return [e for e in world.entities.values() if e.kind in kinds and _visible(world, e.id)]


def _row(world: World, comp: Compendium, entity: Entity) -> dict[str, Any]:
    facts = known_facts(world, entity.id)
    status, unseen = _status(facts, comp.mark(entity.id))
    return {
        "id": entity.id,
        "name": entity.name,
        "kind": entity.kind,
        "category": category_of(entity),
        "summary": _summary(entity, facts),
        "parent": _parent(world, entity),
        "depth": 0,
        "fact_count": len(facts),
        "status": status,
        "unseen_count": unseen,
        "learned_turn": min((_learned_turn(f) for f in facts), default=0),
    }


def summary(world: World, comp: Compendium) -> dict[str, Any]:
    """Counts per category, and the totals of entities with something unseen."""
    categories = []
    for cid, (title, _) in CATEGORIES.items():
        rows = [_row(world, comp, e) for e in _visible_in(world, cid)]
        categories.append(
            {
                "id": cid,
                "title": title,
                "count": len(rows),
                "new": sum(r["status"] == "new" for r in rows),
                "updated": sum(r["status"] == "updated" for r in rows),
            }
        )
    return {
        "categories": categories,
        "new": sum(c["new"] for c in categories),
        "updated": sum(c["updated"] for c in categories),
    }


def unseen_totals(world: World, comp: Compendium) -> dict[str, int]:
    """The small object `message_end` and the history calls carry."""
    s = summary(world, comp)
    return {"new": s["new"], "updated": s["updated"]}


def entries(
    world: World,
    comp: Compendium,
    category: str,
    *,
    q: str | None = None,
    status: str | None = None,
    sort: str = "name",
) -> list[dict[str, Any]]:
    rows = []
    needle = (q or "").strip().casefold()
    for entity in _visible_in(world, category):
        row = _row(world, comp, entity)
        if status == "unseen" and row["status"] is None or status in ("new", "updated") and row["status"] != status:
            continue
        if needle:
            names = [entity.name, *visible_aliases(entity, known_facts(world, entity.id))]
            if not any(needle in n.casefold() for n in names):
                continue
        rows.append(row)
    if sort == "recent":
        newest = {e["id"]: max((f.learned_seq for f in known_facts(world, e["id"])), default=0) for e in rows}
        rows.sort(key=lambda r: (-newest[r["id"]], r["name"].casefold()))
    elif sort == "tree":
        return _tree(rows)
    else:
        rows.sort(key=lambda r: r["name"].casefold())
    return rows


def _tree(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parents before their children, siblings by name. A row whose parent is not in the list is a root."""
    ids = {r["id"] for r in rows}
    children: dict[str | None, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda r: r["name"].casefold()):
        parent = row["parent"]["id"] if row["parent"] and row["parent"]["id"] in ids else None
        children.setdefault(parent, []).append(row)
    out: list[dict[str, Any]] = []

    def walk(parent: str | None, depth: int) -> None:
        for row in children.get(parent, []):
            out.append({**row, "depth": depth})
            walk(row["id"], depth + 1)

    walk(None, 0)
    return out


def detail(world: World, comp: Compendium, entity_id: str) -> dict[str, Any] | None:
    """One entity, or None when it is unknown or the player has not discovered it (the two look the same)."""
    if not _visible(world, entity_id):
        return None
    entity = world.entities[entity_id]
    facts = known_facts(world, entity_id)
    mark = comp.mark(entity_id)
    status, _ = _status(facts, mark)
    order = {a: i for i, a in enumerate(ASPECTS.get(entity.kind, ()))}

    def reading_order(f: Fact) -> tuple[bool, int, int]:
        return (f.subject != entity_id, order.get(f.aspect or "", len(order)), f.learned_seq)

    children = [c for c in world.children(entity_id) if _visible(world, c.id)]
    related = _related(world, entity, facts)
    return {
        "id": entity.id,
        "name": entity.name,
        "kind": entity.kind,
        "category": category_of(entity),
        "aliases": visible_aliases(entity, facts),
        "status": status,
        "parent": _parent(world, entity),
        "path": _path(world, entity),
        "children": [
            {**_ref(world, c.id), "kind": c.kind, "status": _status(known_facts(world, c.id), comp.mark(c.id))[0]}
            for c in children
        ],
        "facts": [
            {
                "id": f.id,
                "text": f.text,
                "aspect": f.aspect,
                "label": _aspect_label(f.aspect),
                "learned_turn": _learned_turn(f),
                "new": f.learned_seq > mark,
                "via": list(f.via),
            }
            for f in sorted(facts, key=reading_order)
        ],
        "related": related,
        "look": _look(entity),
        "learned_turn": min((_learned_turn(f) for f in facts), default=0),
        "updated_turn": max((_learned_turn(f) for f in facts), default=0),
    }


def _related(world: World, entity: Entity, facts: list[Fact]) -> list[dict[str, Any]]:
    skip = {entity.id, entity.parent, *(c.id for c in world.children(entity.id))}
    latest: dict[str, int] = {}
    for fact in facts:
        for eid in fact.about:
            if eid not in skip and _visible(world, eid):
                latest[eid] = max(latest.get(eid, 0), fact.learned_seq)
    ranked = sorted(latest, key=lambda e: (-latest[e], e))[:MAX_RELATED]
    return [
        {**_ref(world, e), "kind": world.entities[e].kind, "category": category_of(world.entities[e])}
        for e in ranked
    ]
