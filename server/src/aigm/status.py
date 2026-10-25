"""The status page: where the party is, who and what is there, and how everyone is doing (docs/STATUS.md).

Like the compendium it is a read-only view that is pulled when asked, built from stored data only: no model is called
here. What the player may see of the world goes through the compendium's filter, so an entity the player has not
discovered, and a fact that is not known, never appear."""

from typing import Any

from aigm.characters import hp_text
from aigm.combat import ALLY
from aigm.compendium import _path, _ref, _summary, _visible, known_facts
from aigm.session.state import GameState
from aigm.world import World
from aigm.world.briefing import time_of_day

ROUTE_ASPECTS = ("approach", "connections")  # what to say about the way to a neighbouring place
MAX_ROUTE_CHARS = 120
TABLE_COLUMNS = ["Name", "HP", "Conditions", "Who"]
COMBAT_COLUMNS = ["Name", "Side", "Health", "Conditions"]


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
        sheet = state.sheets.get(name)
        hp = hp_text(sheet.hp, sheet.max_hp) if sheet else ""
        conditions = ", ".join(sheet.conditions) if sheet else ""
        rows.append([name, hp or "-", conditions or "-", f"Party, level {state.hero(name).level}"])
    return rows


def _combat_rows(state: GameState, here: list[dict[str, Any]]) -> list[list[str]]:
    """In a fight the table is by side: the party, its allies, the foes, and bystanders the scene lists. Foes show a
    health word (the GM wrote only what the player can see)."""
    combat = state.combat
    assert combat is not None
    rows = []
    for name in state.party_names:
        sheet = state.sheets.get(name)
        hp = hp_text(sheet.hp, sheet.max_hp) if sheet else ""
        rows.append([name, "Party", hp or "-", ", ".join(sheet.conditions) if sheet and sheet.conditions else "-"])
    for side, label in ((ALLY, "Ally"), ("foe", "Foe")):
        rows += [[c.label, label, c.health, ", ".join(c.conditions) or "-"] for c in combat.combatants if c.side == side]
    named = {c.name.lower() for c in combat.combatants}
    rows += [[e["name"], "Bystander", "-", "-"] for e in here if e["name"].lower() not in named]
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
    if state.combat is not None:
        columns, rows = COMBAT_COLUMNS, _combat_rows(state, here)
    else:
        columns, rows = TABLE_COLUMNS, _party_rows(state) + [[e["name"], "-", "-", e["summary"]] for e in here]
    return {
        "location": location,
        "here": here,
        "items": items,
        "inside": inside,
        "exits": exits,
        "combat": {"foes": sum(c.count for c in state.combat.combatants if c.side != ALLY)} if state.combat else None,
        "table": {"columns": columns, "rows": rows},
    }
