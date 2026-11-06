"""The GM's world tools: `recall` reads the knowledge base, `establish` and `set_scene` write to it.

They work on the turn's working copy of the game state, so what they record only becomes real if
the turn succeeds. Descriptions live in prompts/tools/*.md. See docs/WORLD.md section 6."""

import re
from typing import Any

from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm import story as story_rules
from aigm.story import addition_allowed
from aigm.tools.story import STORY_PROPERTY, check_story_report
from aigm.travel import PACES, paced, plan_move, way_text
from aigm.world import DISCLOSURES, KINDS, Entity, Fact, World, WorldError
from aigm.world.model import (
    BLOCK_KINDS, HOLDING_EVENTS, MAX_BLOCK_TEXT, MAX_HOLDING_NOTE_WORDS, MAX_ROUTE_HOW, MAX_ROUTE_MINUTES, SCALES, Block,
    duration_text,
)
from aigm.world.briefing import LABELS, motive_line, route_line
from aigm.world.text import normalize_name

ADVENTURE = frozenset({Phase.ADVENTURE})
RECALL_FACTS = 25  # facts listed for one entity
RECALL_HITS = 8  # facts listed for a text query
MAX_NEW_FACTS = 12
MAX_NEW_ENTITIES = 6
MAX_ELAPSED_MINUTES = 24 * 60 * 30
MAX_LOOK_NOTE_WORDS = 40
MAX_ITEM_EVENTS = 6
MAX_NEW_ITEMS = 2  # key items created by one `establish` call (docs/KEY_ITEMS.md 5.1)
MAX_ITEM_NOTE_WORDS = 30
MAX_NEW_ROUTES = 8  # routes one entity may bring in an `establish` call (docs/TIME.md 5.2)


def _fact_line(fact: Fact) -> str:
    return f"- ({fact.id}) [{LABELS[fact.disclosure]}] {fact.text}"


def _names(entities: list[Entity]) -> str:
    return ", ".join(e.name for e in entities)


# ---- recall -----------------------------------------------------------------------------

RECALL_SCHEMA: dict[str, Any] = {
    "name": "recall",
    "input_schema": {
        "type": "object",
        "properties": {
            "about": {
                "type": "string",
                "description": "The name (or alias) of a person, place, group or concept to look up.",
            },
            "query": {
                "type": "string",
                "description": "Words to search the recorded facts for, e.g. 'who controls the toll road'.",
            },
        },
    },
}


def _describe(world: World, ent: Entity) -> list[str]:
    head = f"{ent.name} ({ent.kind}, {ent.id}" + (f"; also called {', '.join(ent.aliases)}" if ent.aliases else "") + ")"
    chain = world.parent_chain(ent.id)
    if chain:
        head += f", in {_names(chain)}"
    lines = [head]
    kids = world.children(ent.id)
    if kids:
        lines.append(f"Contains: {_names(kids)}")
    if ent.kind == "location":
        if ent.scale:
            lines[0] += f"; a {ent.scale}"
        ways = world.routes_of(ent.id)
        if ways:
            lines.append("Ways from here: " + "; ".join(route_line(world, r, ent.id) for r in ways))
    for a in world.attempts_about([ent.id], unresolved_only=False):
        lines.append(
            f"Attempt {a.id} ({a.status}): {a.who} tried to {a.task}, {a.tries} {'try' if a.tries == 1 else 'tries'}"
            + (f"; {a.failure}" if a.failure else "")
            + (f". Reopens if: {a.reopens_if.rstrip('.')}" if a.status == "closed" and a.reopens_if else "")
        )
    if ent.look:
        lines.append(f"Look (what anyone can see; stay within it): {ent.look.summary} {ent.look.description}")
    facts = sorted(world.facts_about(ent.id), key=lambda f: (f.disclosure != "known", int(f.id[1:])))
    for fact in facts[:RECALL_FACTS]:
        lines.append(_fact_line(fact))
    if len(facts) > RECALL_FACTS:
        lines.append(f"(+{len(facts) - RECALL_FACTS} more facts not shown)")
    if not facts:
        lines.append("No facts recorded yet.")
    motives = world.motives_of(ent.id) if ent.kind == "npc" else []
    if motives:
        lines.append("Motives (GM only, never state them):")
        lines += [motive_line(ent, m) for m in motives]
    linked = [world.entities[e] for e in sorted(world.neighbors(ent.id))]
    if linked:
        lines.append(f"Connected to: {_names(linked)}")
    return lines


def recall(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    world = state.world
    about, query = tool_input.get("about"), tool_input.get("query")
    about = about.strip() if isinstance(about, str) else ""
    query = query.strip() if isinstance(query, str) else ""
    if not about and not query:
        return ToolOutcome("Give either `about` (a name) or `query` (words to search for).", is_error=True)
    lines: list[str] = []
    found = False
    if about:
        ent = world.resolve(about)
        if ent:
            found = True
            lines += _describe(world, ent)
        else:
            lines.append(f"No person, place, group or concept named {about!r} is recorded.")
            query = query or about  # fall back to a text search
    if query:
        hits = world.search(query, limit=RECALL_HITS)
        if hits:
            found = True
            lines += ([""] if lines else []) + [f"Facts matching {query!r}:", *(_fact_line(f) for f in hits)]
        elif about != query:
            lines.append(f"No recorded facts match {query!r}.")
    if not found:
        state.pass_requested = state.pass_requested or bool(about)  # the party may be ahead of the world
        lines.append("Nothing is recorded about this. If you improvise it, record it with `establish` so it stays true.")
    return ToolOutcome("\n".join(lines))


# ---- establish --------------------------------------------------------------------------

ESTABLISH_SCHEMA: dict[str, Any] = {
    "name": "establish",
    "input_schema": {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "description": f"New people, places, groups, concepts or key items you have introduced (at most {MAX_NEW_ENTITIES}). Skip ones already recorded.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "parent": {
                            "type": "string",
                            "description": "For a place: the recorded place that contains it (a town for a tavern).",
                        },
                        "look_notes": {
                            "type": "string",
                            "description": f"For a person: the visible traits you are about to narrate, at most {MAX_LOOK_NOTE_WORDS} words ('tall, one-eyed, in a guard's tabard'). They become part of the person's recorded description. Required for a key item: what it is and looks like, as a phrase that completes 'It is ...', at most {MAX_ITEM_NOTE_WORDS} words ('a thick green-bound ledger with brass corners').",
                        },
                        "scale": {
                            "type": "string",
                            "enum": list(SCALES),
                            "description": "For a place: its size. room (a room, cave chamber, stall), site (a building, dungeon, ruin, camp), settlement (village, town, city) or region (forest, valley, coast).",
                        },
                        "routes": {
                            "type": "array",
                            "description": f"For a place: the ways to places already recorded (at most {MAX_NEW_ROUTES}), including its exits. Naming a way again updates it.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "to": {"type": "string", "description": "A recorded place, or one in this call."},
                                    "minutes": {"type": "integer", "description": "How long the way takes on foot."},
                                    "hours": {"type": "integer", "description": "The same, in whole hours (give minutes or hours)."},
                                    "how": {"type": "string", "description": f"The way, in a few words ('down the cellar steps', 'over the Harrow Pass'), up to {MAX_ROUTE_HOW} characters. Tells two ways between the same places apart."},
                                    "block": {
                                        "type": ["object", "null"],
                                        "description": "What stops the party on this way, or null to clear one that was there.",
                                        "properties": {
                                            "kind": {"type": "string", "enum": list(BLOCK_KINDS)},
                                            "text": {"type": "string", "description": f"What the party meets ('a locked oak door'), up to {MAX_BLOCK_TEXT} characters."},
                                            "opens_by": {"type": "string", "description": "For you alone: what would open it."},
                                        },
                                        "required": ["kind", "text"],
                                    },
                                },
                                "required": ["to"],
                            },
                        },
                    },
                    "required": ["name", "kind"],
                },
            },
            "facts": {
                "type": "array",
                "description": f"Facts you have invented or established (at most {MAX_NEW_FACTS}).",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "One self-contained declarative sentence of about 40 words or fewer, using names rather than pronouns.",
                        },
                        "about": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Names of the entities it concerns (1-4); the first is the subject.",
                        },
                        "disclosure": {
                            "type": "string",
                            "enum": list(DISCLOSURES),
                            "description": "known (default): the player has been told. hidden: true but the player has not been told. hinted: the player has only heard hints.",
                        },
                        "aspect": {
                            "type": "string",
                            "enum": ["items"],
                            "description": "`items`: a notable object lying in view at a place, as the party sees it. It is listed on the status page when known.",
                        },
                        "replaces": {
                            "type": "string",
                            "description": "Id of a known `items` fact this one improves on, when the party learns more about the object (an unmarked vial turns out to be a healing potion).",
                        },
                    },
                    "required": ["text", "about"],
                },
            },
            "reveal": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ids of recorded GM-only facts (like f0042) that your narration has now told the player.",
            },
        },
    },
}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _look_note(raw: dict[str, Any], name: str, hints: dict[str, str], ignored: list[str]) -> None:
    """Keep a person's `look_notes` for the describer (docs/LOOKS.md 4.4). Raises WorldError if it is too long."""
    note = raw.get("look_notes")
    if note is None or (isinstance(note, str) and not note.strip()):
        return
    if not isinstance(note, str):
        ignored.append(f"`look_notes` of {name!r} (not text)")
    elif len(note.split()) > MAX_LOOK_NOTE_WORDS:
        raise WorldError(f"look_notes is {len(note.split())} words; at most {MAX_LOOK_NOTE_WORDS}")
    else:
        hints[normalize_name(name)] = " ".join(note.split())


def _item_note(raw: dict[str, Any], name: str, out: dict[str, str]) -> None:
    """A key item must come with what it looks like, since a picture cannot be made from nothing."""
    note = raw.get("look_notes")
    words = len(note.split()) if isinstance(note, str) else 0
    if words < 2:
        raise WorldError(f"a key item needs `look_notes`: a phrase completing 'It is ...' that says what {name} looks like")
    if words > MAX_ITEM_NOTE_WORDS:
        raise WorldError(f"look_notes is {words} words; at most {MAX_ITEM_NOTE_WORDS}")
    out[name] = " ".join(note.split())


def _read_block(raw: Any) -> Block | None:
    if not isinstance(raw, dict):
        raise WorldError("`block` must be an object with a kind and a text, or null to clear it")
    opens = raw.get("opens_by", "")
    return Block(str(raw.get("kind")), str(raw.get("text") or ""), opens if isinstance(opens, str) else "")


def _geography(world: World, ent: Entity, raw: dict[str, Any], routed: list[str], ignored: list[str]) -> None:
    """A place's `scale` and `routes` from an `establish` entity (docs/TIME.md 5.1 and 5.2). Raises WorldError."""
    if raw.get("scale") is not None:
        if not isinstance(raw["scale"], str):
            raise WorldError(f"scale must be one of {', '.join(SCALES)}")
        world.set_scale(ent.id, raw["scale"])
    ways = raw.get("routes")
    if ways is None:
        return
    if not isinstance(ways, list) or not all(isinstance(w, dict) for w in ways):
        raise WorldError("`routes` must be a list of objects with `to` and `minutes` or `hours`")
    if len(ways) > MAX_NEW_ROUTES:
        raise WorldError(f"at most {MAX_NEW_ROUTES} routes per place per call")
    for way in ways:
        other = world.resolve(way["to"]) if isinstance(way.get("to"), str) else None
        if other is None:
            raise WorldError(f"route to {way.get('to')!r}: that place is not recorded; add it under `entities` first")
        minutes, hours = way.get("minutes"), way.get("hours")
        if minutes is not None and hours is not None:
            raise WorldError(f"route to {other.name}: give `minutes` or `hours`, not both")
        if minutes is None and hours is None:
            raise WorldError(f"route to {other.name}: say how long it takes, with `minutes` or `hours`")
        if hours is not None:
            if isinstance(hours, bool) or not isinstance(hours, int):
                raise WorldError(f"route to {other.name}: `hours` must be a whole number")
            minutes = hours * 60
        block: Block | None | str = "keep"
        if "block" in way:
            block = None if way["block"] is None else _read_block(way["block"])
        try:
            route, _ = world.set_route(ent.id, other.id, minutes, way.get("how") or "", block=block)
        except WorldError as exc:
            raise WorldError(f"route to {other.name}: {exc}") from None
        routed.append(f"{ent.name} to {other.name} ({duration_text(route.minutes)}{', blocked' if route.block else ''})")


def _off_the_map(before: World, world: World, places: list[Entity]) -> list[str]:
    """New places that neither have a route nor lie inside the place the party is in (docs/TIME.md 5.2)."""
    here = world.scene.location
    out: list[str] = []
    for ent in places:
        if before.find(ent.name) is not None or world.routes_of(ent.id):
            continue  # not new in this call, or already joined to the map
        inside = ent.id == here or here in {p.id for p in world.parent_chain(ent.id)}
        if not inside and ent.name not in out:
            out.append(ent.name)
    return out


def establish(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    entities, facts, reveals = (_as_list(tool_input.get(k)) for k in ("entities", "facts", "reveal"))
    if not (entities or facts or reveals):
        return ToolOutcome("Nothing to record: give `entities`, `facts` or `reveal`.", is_error=True)
    if len(entities) > MAX_NEW_ENTITIES or len(facts) > MAX_NEW_FACTS:
        return ToolOutcome(
            f"Too much at once: at most {MAX_NEW_ENTITIES} entities and {MAX_NEW_FACTS} facts per call.", is_error=True
        )
    before = state.world
    world = state.world.copy()  # all or nothing: only replaces the real world if everything is accepted
    problems: list[str] = []
    done: list[str] = []
    reused: list[str] = []
    ignored: list[str] = []
    hints: dict[str, str] = {}  # person's name -> look_notes, kept only if the whole call is accepted
    appearance: dict[str, str] = {}  # key item's name -> what it looks like, recorded as a hidden fact below
    items_made: list[str] = []
    placed: list[str] = []  # new places given no `parent`, put inside the world's top place
    new_items = sum(1 for r in entities if isinstance(r, dict) and r.get("kind") == "item" and world.find(str(r.get("name"))) is None)
    if new_items > MAX_NEW_ITEMS:
        problems.append(f"at most {MAX_NEW_ITEMS} new key items per call: only quest objects are key items")
    for raw in entities:
        label = f"entity {raw.get('name')!r}" if isinstance(raw, dict) else "entity"
        try:
            if not isinstance(raw, dict):
                raise WorldError("each entity must be an object with a name and kind")
            name, kind = raw.get("name"), raw.get("kind")
            aliases = [a for a in _as_list(raw.get("aliases")) if isinstance(a, str)]
            names = [n for n in (name, *aliases) if isinstance(n, str)]
            if any(state.find_hero(n) for n in names):
                raise WorldError(
                    "that is a party member. Player characters are never recorded in the world: they are always "
                    "with the party, so leave them out of `entities` and `present`"
                )
            existing = next((e for e in map(world.find, names) if e is not None), None)
            if existing:
                if existing.kind != kind:
                    raise WorldError(f"already recorded as a {existing.kind} (id {existing.id}), not a {kind}")
                if kind == "location" and raw.get("parent") and existing.parent in (None, world.root):
                    new_parent = world.resolve(str(raw["parent"]))  # a place put in the top by default can be moved
                    if new_parent is None:
                        raise WorldError(f"parent {raw['parent']!r} is not recorded")
                    world.set_parent(existing.id, new_parent.id)
                for other in names:
                    if world.find(other) is None:
                        world.add_alias(existing.id, other)  # a new name for something recorded, not a second entity
                if normalize_name(str(name)) != normalize_name(existing.name):
                    reused.append(f"{name!r} is the already recorded {existing.name!r}")
                if existing.kind == "npc" and existing.look is None:
                    _look_note(raw, existing.name, hints, ignored)
                continue
            parent = None
            if raw.get("parent") and kind != "location":
                ignored.append(f"`parent` of {name!r} (only places have one)")
            elif raw.get("parent"):
                parent_ent = world.resolve(str(raw["parent"]))
                if parent_ent is None:
                    raise WorldError(f"parent {raw['parent']!r} is not recorded")
                parent = parent_ent.id
            auto_placed = kind == "location" and parent is None and world.root is not None
            parent = world.default_parent(kind, parent)
            allowed, why = addition_allowed(state.story, world, kind, parent)
            if not allowed:
                raise WorldError(f"{why}. This is the road to the goal: use what is already recorded")
            ent = world.add_entity(name, kind, aliases=aliases, parent=parent)
            done.append(f"{ent.name} ({ent.id})")
            if auto_placed:
                placed.append(ent.name)
            if kind == "npc":
                _look_note(raw, ent.name, hints, ignored)
            elif kind == "item":
                items_made.append(ent.id)
                _item_note(raw, ent.name, appearance)
            elif raw.get("look_notes"):
                ignored.append(f"`look_notes` of {name!r} (only people have a look)")
        except WorldError as exc:
            problems.append(f"{label}: {exc}")
    routed: list[str] = []
    made_places = [world.find(str(r.get("name"))) for r in entities if isinstance(r, dict) and r.get("kind") == "location"]
    for raw in entities:
        if not isinstance(raw, dict):
            continue
        ent = world.find(str(raw.get("name")))
        if ent is None:
            continue
        if ent.kind != "location":
            for key in ("scale", "routes"):
                if raw.get(key) is not None:
                    ignored.append(f"`{key}` of {ent.name!r} (only places have one)")
            continue
        try:
            _geography(world, ent, raw, routed, ignored)
        except WorldError as exc:
            problems.append(f"entity {ent.name!r}: {exc}")
    recorded: list[str] = []
    skipped: list[str] = []
    for name, note in appearance.items():  # until the party has the item, how it looks is the GM's alone
        try:
            ent = world.find(name)
            assert ent is not None
            fact = world.add_fact(
                f"{ent.name} is {note.rstrip('.')}.", [ent.id], aspect="appearance", disclosure="hidden",
                source="improvised", turn=state.turn,
            )
            recorded.append(fact.id)
        except WorldError as exc:
            problems.append(f"look_notes of {name!r}: {exc}")
    for i, raw in enumerate(facts, 1):
        label = f"fact {i}"
        try:
            if not isinstance(raw, dict):
                raise WorldError("each fact must be an object with text and about")
            refs = _as_list(raw.get("about"))
            about_ids = []
            for ref in refs:
                ent = world.resolve(ref) if isinstance(ref, str) else None
                if ent is None:
                    raise WorldError(f"{ref!r} is not recorded; add it under `entities` (with its kind) first")
                about_ids.append(ent.id)
            text = raw.get("text")
            aspect, replaces = raw.get("aspect"), raw.get("replaces")
            if aspect not in (None, "items"):
                raise WorldError("`aspect` can only be `items`")
            if replaces is not None:
                old = world.fact(str(replaces))
                if old is None or not old.active or old.aspect != "items":
                    raise WorldError(f"`replaces` {replaces!r} must be a recorded `items` fact that still stands")
                fact = world.supersede(
                    old.id, text, about=about_ids, aspect=old.aspect, disclosure=raw.get("disclosure") or "known",
                    source="improvised", turn=state.turn, allow_known=True,
                )
                recorded.append(fact.id)
                continue
            if about_ids and isinstance(text, str):
                twin = world.similar_fact(text, about_ids[0])
                if twin:
                    skipped.append(f"fact {i} repeats {twin.id}")
                    continue
            fact = world.add_fact(
                text,
                about_ids,
                aspect=aspect,
                disclosure=raw.get("disclosure") or "known",
                source="improvised",
                turn=state.turn,
            )
            recorded.append(fact.id)
        except WorldError as exc:
            problems.append(f"{label}: {exc}")
    revealed: list[str] = []
    for fid in reveals:
        try:
            if world.reveal(str(fid), state.turn):
                revealed.append(str(fid))
        except WorldError as exc:
            problems.append(f"reveal {fid}: {exc}")
    if problems:
        return ToolOutcome(
            "Nothing was recorded:\n- " + "\n- ".join(problems) + "\nFix these and call establish again.",
            is_error=True,
        )
    state.world = world
    state.look_hints.update(hints)
    parts = []
    if done:
        parts.append("new: " + ", ".join(done))
    if recorded:
        parts.append("facts: " + ", ".join(recorded))
    if revealed:
        parts.append("now known to the player: " + ", ".join(revealed))
    if skipped:
        parts.append("skipped (already recorded): " + "; ".join(skipped))
    if placed:
        parts.append(
            "placed directly in " + world.entities[world.root].name + ": " + ", ".join(placed)
            + ". If any lies inside a town, a building or another place, name it again with `parent` to move it there"
        )
    if routed:
        parts.append("routes: " + ", ".join(routed))
    unmapped = _off_the_map(before, world, [p for p in made_places if p is not None])
    if unmapped:
        parts.append(
            "not on the map yet: " + ", ".join(unmapped) + ". Give each `routes` to a recorded place (how long it takes "
            "and how you get there), so travel can take the time it should"
        )
    if reused:
        parts.append("not added again: " + "; ".join(reused))
    if ignored:
        parts.append("ignored: " + "; ".join(ignored))
    return ToolOutcome("Recorded. " + ("; ".join(parts) if parts else "Everything was already recorded."))


# ---- set_scene --------------------------------------------------------------------------

SET_SCENE_SCHEMA: dict[str, Any] = {
    "name": "set_scene",
    "input_schema": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "The recorded place where the party now is. Omit if the party has not moved.",
            },
            "present": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Recorded people or groups with the party now (replaces the previous list). Omit to keep it, unless the location changed, which clears it.",
            },
            "elapsed_minutes": {
                "type": "integer",
                "description": "Whole in-world minutes that have passed since your last reply, if any (0 if none).",
            },
            "pace": {
                "type": "string",
                "enum": list(PACES),
                "description": "How the party travels. normal (the default) is on foot. fast (mounted, a coach, a boat) halves the time and instant (teleportation, a portal) takes none; both need `how`.",
            },
            "how": {
                "type": "string",
                "description": "With pace fast or instant: the means the story has given the party, in a few words ('Mira's horses', 'the teleportation circle').",
            },
            "via": {
                "type": "string",
                "description": "When the party has more than one way to the place and has chosen: a place on the way or words from its description ('the servants' passages'). The result lists the ways when you need to ask.",
            },
            "guide": {
                "type": "string",
                "description": "A recorded person with the party who knows the way, so the party can go somewhere it has not been through places it has not seen.",
            },
        },
    },
}


_MOVE = re.compile(
    r"\b(head|go|walk|run|ride|sail|travel|move|enter|leave|return|climb|descend|follow|sneak|cross|visit|proceed|"
    r"hurry|rush|retreat|flee|step)\b.*\b(to|into|toward|towards|down|up|back|out|inside|through|across|home)\b",
    re.I | re.S,
)


def _unmoved_note(state: GameState, where: str) -> str:
    """Said when `set_scene` was called without a `location`, so the place did not change: a GM that narrated a move
    but left the place out would otherwise be told only where the party still is."""
    if _MOVE.search(state.player_text or ""):
        return (
            f" The place did NOT change: the party is still at {where}. The player asked to go somewhere: if they have "
            "arrived, call `set_scene` again now with `location` (record a new place with `establish` first), before "
            "you write your reply."
        )
    return f" The place did not change (still {where}). If the party has moved on, pass `location`."


def _learn_route(world: World, a: str, b: str, minutes: int) -> None:
    """The GM took longer than the estimate between two places with no recorded way: keep it, so the way back and the
    next trip take the same time (docs/TIME.md 5.5). Never changes a route that is already recorded."""
    if world.find_route(a, b) is None:
        try:
            world.set_route(a, b, min(minutes, MAX_ROUTE_MINUTES), source="play")
        except WorldError:
            pass  # a place with a dozen routes already: nothing is lost


def _move_party(
    world: World, origin: str, dest: str, *, pace: str, via: str | None, guided: bool, declared: int
) -> tuple[ToolOutcome | None, str, int, str, list[str]]:
    """Walk the party from `origin` towards `dest` (docs/TIME.md 5.4). Returns a refusal (or None), where the party ends,
    the minutes to spend, a note for the GM and the places passed on the way."""
    if pace == "instant":
        return None, dest, declared, "", []
    names = world.entities
    start, end = names[origin].name, names[dest].name
    move = plan_move(world, origin, dest, via=via, guided=guided)
    if move.kind == "choose":
        listing = "\n".join(f"- {way_text(world, w)}: about {duration_text(w.minutes)}" for w in move.options)
        return (
            ToolOutcome(
                f"Scene not changed: there is more than one way from {start} to {end}:\n{listing}\n"
                "Unless the player's own words, or what you have already narrated, chose one, ask which they take, in the "
                "story's voice (describe the ways, do not number them or say 'route'), and end your turn. Then call "
                "`set_scene` again with `via` naming a place on the way or words from its description.",
                is_error=True,
            ),
            origin, 0, "", [],
        )
    if move.kind == "none":
        return (
            ToolOutcome(
                f"Scene not changed: the party can find no way from {start} to {end}. Narrate that they cannot get there "
                "from here, and let the player try something else.",
                is_error=True,
            ),
            origin, 0, "", [],
        )
    needed = paced(move.minutes, pace)
    suffix = " at this pace" if pace != "normal" else ""
    if move.reason == "unexplored":
        ahead = names[move.next_place].name if move.next_place else end
        note = (
            f" The party stops at {names[move.stop].name}: it is new to them, and they have not yet seen the way on to "
            f"{ahead}. Narrate the journey as far as {names[move.stop].name} (about {duration_text(needed)}{suffix}) and no "
            f"further; they have to explore from there, and can set out for {end} again afterwards."
        )
    elif move.reason == "blocked" and move.blocker is not None:
        opens = f" (for you alone, it opens by: {move.blocker.block.opens_by})" if move.blocker.block.opens_by else ""
        note = (
            f" The party is stopped at {names[move.stop].name} on the way to {end}: {move.blocker.block.text}{opens}. "
            "Narrate reaching it and no further; the way on waits until it is dealt with (a key, a lockpicking attempt, "
            "force, or another way round)."
        )
    else:
        note = ""
        if needed > declared:
            note = (
                f" The way from {start} to {end} takes about {duration_text(needed)}{suffix}"
                + ("; the clock is moved to match." if declared else ".")
            )
        if pace == "normal" and move.kind == "estimate" and declared > move.minutes:
            _learn_route(world, origin, dest, declared)
    complete = move.reason is None
    return None, move.stop, (max(needed, declared) if complete else needed), note, move.passed


def set_scene(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    world = state.world.copy()
    problems: list[str] = []
    loc_ref, present_in = tool_input.get("location"), tool_input.get("present")
    minutes, hours = tool_input.get("elapsed_minutes"), tool_input.get("elapsed_hours")  # hours: an older spelling
    location = world.scene.location
    if loc_ref is not None:
        ent = world.resolve(loc_ref) if isinstance(loc_ref, str) else None
        if ent is None or ent.kind != "location":
            problems.append(f"{loc_ref!r} is not a recorded place; add it with `establish` first")
        else:
            location = ent.id
    present = list(world.scene.present)
    if present_in is not None:
        present = []
        for ref in _as_list(present_in):
            if isinstance(ref, str) and state.find_hero(ref):
                continue  # party members are always with the party; they are not recorded
            ent = world.resolve(ref) if isinstance(ref, str) else None
            if ent is None:
                problems.append(f"{ref!r} is not recorded; add it with `establish` first")
            else:
                present.append(ent.id)
    elif location != world.scene.location:
        present = []  # moved without saying who is there: do not carry people along by accident
    if minutes is not None and hours is not None:
        problems.append("give `elapsed_minutes` or `elapsed_hours`, not both")
    elif hours is not None:
        if isinstance(hours, bool) or not isinstance(hours, int) or hours < 0:
            problems.append("elapsed_hours must be a whole number of hours")
        else:
            minutes = hours * 60
    if minutes is not None and not problems:
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= MAX_ELAPSED_MINUTES:
            problems.append(f"elapsed_minutes must be a whole number from 0 to {MAX_ELAPSED_MINUTES}")
    pace, how = tool_input.get("pace", "normal"), tool_input.get("how")
    via, guide = tool_input.get("via"), tool_input.get("guide")
    if via is not None and not isinstance(via, str):
        problems.append("`via` must be text")
    guide_ent = None
    if guide is not None:
        guide_ent = world.resolve(guide) if isinstance(guide, str) else None
        if guide_ent is None or guide_ent.id not in present:
            problems.append(f"`guide` {guide!r} must be a recorded person who is with the party now (see `present`)")
    if pace not in PACES:
        problems.append(f"pace must be one of {', '.join(PACES)}")
    elif pace != "normal" and not (isinstance(how, str) and len(how.strip()) >= 3):
        problems.append(f"`pace` {pace} needs `how`: the means the story has given the party (a horse, a teleportation circle)")
    new_story, story_notes = None, []
    if "story" in tool_input:
        new_story, story_problems, story_notes = check_story_report(tool_input["story"], state)
        problems += story_problems
    if problems:
        return ToolOutcome("Scene not changed:\n- " + "\n- ".join(problems), is_error=True)
    origin = state.world.scene.location
    moved = location is not None and origin is not None and location != origin
    declared = minutes or 0
    travel_note = ""
    try:
        spent, passed = declared, []
        if moved:
            refusal, final, spent, travel_note, passed = _move_party(
                world, origin, location, pace=pace, via=via, guided=guide_ent is not None, declared=declared
            )
            if refusal is not None:
                return refusal
            if final != location:  # stopped short: the people at the destination are not here
                location, present = final, []
        world.set_scene(location, present, state.turn)
        if guide_ent is not None:
            for place in passed:  # led through, so the party has now been there
                world.entities[place].visited = True
        if spent:
            name = world.entities[location].name if moved else ""
            world.advance_minutes(
                spent, reported=True, turn=state.turn,
                why=f"the way to {name}" + (f" ({how.strip()})" if pace != "normal" else "") if moved else "time passing",
            )
    except WorldError as exc:
        return ToolOutcome(f"Scene not changed: {exc}", is_error=True)
    if location != state.world.scene.location:
        state.combat = None  # a fight does not follow the party to another place
    if new_story is not None:
        known = state.story.costs if state.story else []
        for cost in (c for c in new_story.costs if c not in known):  # a time cost takes the hours it names off the clock (STAKES.md 6)
            if cost.get("hours"):
                world.advance_minutes(
                    cost["hours"] * 60, reported=True, turn=state.turn, why=f"the cost of failing: {cost['text']}"
                )
    state.world = world
    if new_story is not None:
        state.story = new_story
    where = world.entities[location].name if location else "not set"
    unmoved = _unmoved_note(state, where) if loc_ref is None and location else ""
    here = _names([world.entities[e] for e in world.scene.present]) or "nobody recorded"
    return ToolOutcome(
        f"Scene: {where}. With the party: {here}. Time: {world.time}." + travel_note + unmoved
        + "".join(f" {n}" for n in story_notes)
    )


# ---- key_item ---------------------------------------------------------------------------

KEY_ITEM_SCHEMA: dict[str, Any] = {
    "name": "key_item",
    "input_schema": {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "description": f"What happened to key items this turn (at most {MAX_ITEM_EVENTS}).",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "A key item recorded with `establish` (kind item)."},
                        "event": {"type": "string", "enum": list(HOLDING_EVENTS)},
                        "note": {
                            "type": "string",
                            "description": f"One short sentence saying how (at most {MAX_HOLDING_NOTE_WORDS} words): 'Taken from the steward's desk.'",
                        },
                    },
                    "required": ["name", "event"],
                },
            }
        },
        "required": ["events"],
    },
}

_EVENT_RESULT = {
    "learned": "now known to the player (not yet found)",
    "acquired": "now in the party's hands",
    "used": "used up",
    "lost": "lost",
}


def _item_follow_ups(state: GameState, first: list[Entity]) -> str:
    """What the GM should do next about the key items the party has just got (docs/KEY_ITEMS.md 6): report the quest
    that was about finding one, make the award, and take up the quests the item opens."""
    if not first:
        return ""
    notes = []
    story = state.story
    for ent in first:
        finds = [m for m in (story.milestones if story else []) if m.finds == ent.id and m.status == "active"]
        for m in finds:
            notes.append(f"This completes the quest [{m.id}] {m.title}: report it in your next `set_scene` `story` field.")
        if finds:
            notes.append(f"Its award is the quest's: one `award` for the quest, not a second one for {ent.name}.")
        else:
            notes.append(
                f"Getting {ent.name} should usually earn an award: call `award` in this same response (XP in your "
                "ruleset's scale, reason: what the party did to get it), unless it was trivial."
            )
    if story is not None and story.planned:
        work = story.copy()
        opened = story_rules.settle_ready(work, state.world)
        if opened:
            state.story = work
            titles = ", ".join(f"[{i}] {work.milestone(i).title}" for i in opened)  # type: ignore[union-attr]
            notes.append(f"Now active, since the party has the item: {titles}. Your story notes show them.")
    return " " + " ".join(notes)


def key_item(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    events = _as_list(tool_input.get("events"))
    if not events:
        return ToolOutcome("Give `events`: what happened to which key item.", is_error=True)
    if len(events) > MAX_ITEM_EVENTS:
        return ToolOutcome(f"At most {MAX_ITEM_EVENTS} events per call.", is_error=True)
    world = state.world.copy()  # all or nothing, like establish
    problems: list[str] = []
    lines: list[str] = []
    first: list[Entity] = []  # items the party has just got for the first time
    for i, raw in enumerate(events, 1):
        try:
            if not isinstance(raw, dict):
                raise WorldError("each event must be an object with name and event")
            ent = world.resolve(raw["name"]) if isinstance(raw.get("name"), str) else None
            if ent is None:
                raise WorldError(f"{raw.get('name')!r} is not recorded; create it first with `establish` (kind item)")
            if ent.kind != "item":
                raise WorldError(f"{ent.name} is a {ent.kind}, not a key item")
            event = raw.get("event")
            before = ent.holding.acquired if ent.holding else False
            changed = world.set_holding(ent.id, str(event), str(raw.get("note") or ""), state.turn)
            if changed and event == "acquired" and not before:
                first.append(ent)
            lines.append(
                f"{ent.name}: {_EVENT_RESULT[event]}" if changed else f"{ent.name}: already so, nothing changed"
            )
        except WorldError as exc:
            problems.append(f"event {i}: {exc}")
    if problems:
        return ToolOutcome(
            "Nothing was recorded:\n- " + "\n- ".join(problems) + "\nFix these and call key_item again.", is_error=True
        )
    state.world = world
    return ToolOutcome("Recorded. " + "; ".join(lines) + "." + _item_follow_ups(state, first))


RECALL = Tool(schema=RECALL_SCHEMA, handler=recall, phases=ADVENTURE)
ESTABLISH = Tool(schema=ESTABLISH_SCHEMA, handler=establish, phases=ADVENTURE)
KEY_ITEM = Tool(schema=KEY_ITEM_SCHEMA, handler=key_item, phases=ADVENTURE)
SET_SCENE = Tool(
    schema=SET_SCENE_SCHEMA, handler=set_scene, phases=ADVENTURE, story_properties=STORY_PROPERTY
)
