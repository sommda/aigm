"""The debug-only "hidden" view of the world (docs/COMPENDIUM.md 11): the entities that have facts the player has
not been told, and those facts. It is the opposite of `compendium.py`, which exists to keep these from leaving the
server, so it is only reachable through the debug router (registered with `--debug`) and nothing else imports it."""

from typing import Any

from aigm.world import ASPECTS, Fact, World

HIDDEN = ("hidden", "hinted")  # the disclosure levels the player has not been told in full


def _unknown_facts(world: World, entity_id: str) -> list[Fact]:
    facts = [f for f in world.facts_about(entity_id) if f.disclosure in HIDDEN]
    return sorted(facts, key=lambda f: f.id)


def _motives(world: World, entity_id: str) -> list[dict[str, Any]]:
    """Active motives of an entity, with their type (want, fear, ...). A scene motive whose moment has passed is
    still listed, as `expired`, so a debugger can see why the GM is no longer shown it."""
    return [
        {
            "id": m.id,
            "text": m.text,
            "kind": m.kind,
            "scope": m.scope,
            "strength": m.strength,
            "disclosure": m.disclosure,
            "status": world.motive_state(m),
            "moved_by": list(m.moved_by),
            "resists": list(m.resists),
            "tells": list(m.tells),
            "source": m.source,
            "turn": m.turn,
        }
        for m in world.motives_of(entity_id, live_only=False)
    ]


def _row(world: World, entity_id: str) -> dict[str, Any]:
    entity = world.entities[entity_id]
    facts = _unknown_facts(world, entity_id)
    return {
        "id": entity.id,
        "name": entity.name,
        "kind": entity.kind,
        "discovered": entity.discovered,
        "holding": entity.holding.status if entity.holding else None,
        "hidden_count": sum(f.disclosure == "hidden" for f in facts),
        "hinted_count": sum(f.disclosure == "hinted" for f in facts),
        "motive_count": len(_motives(world, entity_id)),
        "parent": {"id": entity.parent, "name": world.entities[entity.parent].name} if entity.parent else None,
    }


def _has_secrets(world: World, entity_id: str) -> bool:
    return bool(_unknown_facts(world, entity_id) or _motives(world, entity_id))


def entries(world: World, *, q: str | None = None) -> list[dict[str, Any]]:
    """Every entity, of any kind and discovered or not, that has a hidden or hinted fact, by name."""
    needle = (q or "").strip().casefold()
    rows = []
    for entity in world.entities.values():
        if not _has_secrets(world, entity.id):
            continue
        if needle and not any(needle in n.casefold() for n in entity.names()):
            continue
        rows.append(_row(world, entity.id))
    return sorted(rows, key=lambda r: (r["name"].casefold(), r["id"]))


def detail(world: World, entity_id: str) -> dict[str, Any] | None:
    """One entity with its hidden and hinted facts, or None when it has none (or does not exist)."""
    if entity_id not in world.entities or not _has_secrets(world, entity_id):
        return None
    entity = world.entities[entity_id]
    order = {a: i for i, a in enumerate(ASPECTS.get(entity.kind, ()))}

    def reading_order(f: Fact) -> tuple[bool, int, str]:
        return (f.subject != entity_id, order.get(f.aspect or "", len(order)), f.id)

    return {
        **_row(world, entity_id),
        "aliases": list(entity.aliases),
        "facts": [
            {
                "id": f.id,
                "text": f.text,
                "aspect": f.aspect,
                "label": f.aspect.replace("_", " ").capitalize() if f.aspect else None,
                "disclosure": f.disclosure,
                "source": f.source,
                "turn": f.turn,
                "about": [{"id": e, "name": world.entities[e].name} for e in f.about],
            }
            for f in sorted(_unknown_facts(world, entity_id), key=reading_order)
        ],
        "motives": _motives(world, entity_id),
    }
