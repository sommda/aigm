"""The status page: where the party is, who and what is there, and how everyone is doing (docs/STATUS.md).

Like the compendium it is a read-only view that is pulled when asked, built from stored data only: no model is called
here. What the player may see of the world goes through the compendium's filter, so an entity the player has not
discovered, and a fact that is not known, never appear."""

from typing import Any

from aigm.compendium import _path, _ref, _summary, _visible, known_facts
from aigm.session.state import GameState
from aigm.world import World
from aigm.world.briefing import time_of_day

ROUTE_ASPECTS = ("approach", "connections")  # what to say about the way to a neighbouring place
MAX_ROUTE_CHARS = 120
TABLE_COLUMNS = ["Name", "Who"]


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _own(world: World, entity_id: str, aspect: str) -> list[str]:
    return [f.text for f in known_facts(world, entity_id) if f.subject == entity_id and f.aspect == aspect]


def _route(world: World, entity_id: str) -> str | None:
    for aspect in ROUTE_ASPECTS:
        texts = _own(world, entity_id, aspect)
        if texts:
            return _clip(texts[0], MAX_ROUTE_CHARS)
    return None


def _entry(world: World, entity_id: str) -> dict[str, Any]:
    ent = world.entities[entity_id]
    return {**_ref(world, entity_id), "kind": ent.kind, "summary": _summary(ent, known_facts(world, entity_id))}


def _location(world: World) -> dict[str, Any] | None:
    loc_id = world.scene.location
    if loc_id is None or loc_id not in world.entities:
        return None
    ent = world.entities[loc_id]
    overview = _own(world, loc_id, "overview")
    return {
        **_ref(world, loc_id),
        "path": _path(world, ent),
        "overview": overview[-1] if overview else None,
        "time": str(world.time),
        "period": time_of_day(world.time.hour),
    }


def _party_rows(state: GameState) -> list[list[str]]:
    rows = []
    for name in state.party_names:
        hero = state.hero(name)
        rows.append([name, f"Party, level {hero.level}"])
    return rows


def build(state: GameState) -> dict[str, Any]:
    """The status page for the game as it stands."""
    world = state.world
    location = _location(world)
    here, items, inside, exits = [], [], [], []
    if location:
        loc_id = location["id"]
        here = [_entry(world, eid) for eid in world.scene.present if _visible(world, eid)]
        items = _own(world, loc_id, "items")
        inside = [_entry(world, e.id) for e in world.children(loc_id) if _visible(world, e.id)]
        inside_ids = {e["id"] for e in inside}
        for eid in sorted(world.neighbors(loc_id), key=lambda i: world.entities[i].name):
            ent = world.entities[eid]
            if ent.kind == "location" and eid not in inside_ids and eid != world.entities[loc_id].parent and _visible(world, eid):
                exits.append({**_ref(world, eid), "route": _route(world, eid)})
    rows = _party_rows(state) + [[e["name"], e["summary"]] for e in here]
    return {
        "location": location,
        "here": here,
        "items": items,
        "inside": inside,
        "exits": exits,
        "table": {"columns": TABLE_COLUMNS, "rows": rows},
    }
