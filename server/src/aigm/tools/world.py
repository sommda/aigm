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
from aigm.world import DISCLOSURES, KINDS, Entity, Fact, World, WorldError
from aigm.world.model import HOLDING_EVENTS, MAX_HOLDING_NOTE_WORDS
from aigm.world.briefing import LABELS, motive_line
from aigm.world.text import normalize_name

ADVENTURE = frozenset({Phase.ADVENTURE})
RECALL_FACTS = 25  # facts listed for one entity
RECALL_HITS = 8  # facts listed for a text query
MAX_NEW_FACTS = 12
MAX_NEW_ENTITIES = 6
MAX_ELAPSED_HOURS = 24 * 30
MAX_LOOK_NOTE_WORDS = 40
MAX_ITEM_EVENTS = 6
MAX_NEW_ITEMS = 2  # key items created by one `establish` call (docs/KEY_ITEMS.md 5.1)
MAX_ITEM_NOTE_WORDS = 30


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


def establish(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    entities, facts, reveals = (_as_list(tool_input.get(k)) for k in ("entities", "facts", "reveal"))
    if not (entities or facts or reveals):
        return ToolOutcome("Nothing to record: give `entities`, `facts` or `reveal`.", is_error=True)
    if len(entities) > MAX_NEW_ENTITIES or len(facts) > MAX_NEW_FACTS:
        return ToolOutcome(
            f"Too much at once: at most {MAX_NEW_ENTITIES} entities and {MAX_NEW_FACTS} facts per call.", is_error=True
        )
    world = state.world.copy()  # all or nothing: only replaces the real world if everything is accepted
    problems: list[str] = []
    done: list[str] = []
    reused: list[str] = []
    ignored: list[str] = []
    hints: dict[str, str] = {}  # person's name -> look_notes, kept only if the whole call is accepted
    appearance: dict[str, str] = {}  # key item's name -> what it looks like, recorded as a hidden fact below
    items_made: list[str] = []
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
            allowed, why = addition_allowed(state.story, world, kind, parent)
            if not allowed:
                raise WorldError(f"{why}. This is the road to the goal: use what is already recorded")
            ent = world.add_entity(name, kind, aliases=aliases, parent=parent)
            done.append(f"{ent.name} ({ent.id})")
            if kind == "npc":
                _look_note(raw, ent.name, hints, ignored)
            elif kind == "item":
                items_made.append(ent.id)
                _item_note(raw, ent.name, appearance)
            elif raw.get("look_notes"):
                ignored.append(f"`look_notes` of {name!r} (only people have a look)")
        except WorldError as exc:
            problems.append(f"{label}: {exc}")
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
            if about_ids and isinstance(text, str):
                twin = world.similar_fact(text, about_ids[0])
                if twin:
                    skipped.append(f"fact {i} repeats {twin.id}")
                    continue
            fact = world.add_fact(
                text,
                about_ids,
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
            "elapsed_hours": {
                "type": "integer",
                "description": "Whole in-world hours that have passed since your last reply, if any (0 if none).",
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


def set_scene(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    world = state.world.copy()
    problems: list[str] = []
    loc_ref, present_in, hours = tool_input.get("location"), tool_input.get("present"), tool_input.get("elapsed_hours")
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
    if hours is not None:
        if isinstance(hours, bool) or not isinstance(hours, int) or not 0 <= hours <= MAX_ELAPSED_HOURS:
            problems.append(f"elapsed_hours must be a whole number from 0 to {MAX_ELAPSED_HOURS}")
    new_story, story_notes = None, []
    if "story" in tool_input:
        new_story, story_problems, story_notes = check_story_report(tool_input["story"], state)
        problems += story_problems
    if problems:
        return ToolOutcome("Scene not changed:\n- " + "\n- ".join(problems), is_error=True)
    try:
        world.set_scene(location, present, state.turn)
        if hours:
            world.advance_time(hours, reported=True)
    except WorldError as exc:
        return ToolOutcome(f"Scene not changed: {exc}", is_error=True)
    if location != state.world.scene.location:
        state.combat = None  # a fight does not follow the party to another place
    state.world = world
    if new_story is not None:
        state.story = new_story
    where = world.entities[location].name if location else "not set"
    unmoved = _unmoved_note(state, where) if loc_ref is None and location else ""
    here = _names([world.entities[e] for e in world.scene.present]) or "nobody recorded"
    return ToolOutcome(f"Scene: {where}. With the party: {here}. Time: {world.time}." + unmoved + "".join(f" {n}" for n in story_notes))


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
