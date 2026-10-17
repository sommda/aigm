"""The GM's world tools: `recall` reads the knowledge base, `establish` and `set_scene` write to it.

They work on the turn's working copy of the game state, so what they record only becomes real if
the turn succeeds. Descriptions live in prompts/tools/*.md. See docs/WORLD.md section 6."""

from typing import Any

from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.world import DISCLOSURES, KINDS, Entity, Fact, World, WorldError
from aigm.world.briefing import LABELS

ADVENTURE = frozenset({Phase.ADVENTURE})
RECALL_FACTS = 25  # facts listed for one entity
RECALL_HITS = 8  # facts listed for a text query
MAX_NEW_FACTS = 12
MAX_NEW_ENTITIES = 6
MAX_ELAPSED_HOURS = 24 * 30


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
    facts = sorted(world.facts_about(ent.id), key=lambda f: (f.disclosure != "known", int(f.id[1:])))
    for fact in facts[:RECALL_FACTS]:
        lines.append(_fact_line(fact))
    if len(facts) > RECALL_FACTS:
        lines.append(f"(+{len(facts) - RECALL_FACTS} more facts not shown)")
    if not facts:
        lines.append("No facts recorded yet.")
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
                "description": f"New people, places, groups or concepts you have introduced (at most {MAX_NEW_ENTITIES}). Skip ones already recorded.",
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
                            "description": "One self-contained declarative sentence of at most 40 words, using names rather than pronouns.",
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
    for raw in entities:
        label = f"entity {raw.get('name')!r}" if isinstance(raw, dict) else "entity"
        try:
            if not isinstance(raw, dict):
                raise WorldError("each entity must be an object with a name and kind")
            name, kind = raw.get("name"), raw.get("kind")
            aliases = [a for a in _as_list(raw.get("aliases")) if isinstance(a, str)]
            existing = world.find(name) if isinstance(name, str) else None
            if existing:
                if existing.kind != kind:
                    raise WorldError(f"already recorded as a {existing.kind} (id {existing.id}), not a {kind}")
                for alias in aliases:
                    world.add_alias(existing.id, alias)
                continue
            parent = None
            if raw.get("parent"):
                parent_ent = world.resolve(str(raw["parent"]))
                if parent_ent is None:
                    raise WorldError(f"parent {raw['parent']!r} is not recorded")
                parent = parent_ent.id
            ent = world.add_entity(name, kind, aliases=aliases, parent=parent)
            done.append(f"{ent.name} ({ent.id})")
        except WorldError as exc:
            problems.append(f"{label}: {exc}")
    recorded: list[str] = []
    skipped: list[str] = []
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
    parts = []
    if done:
        parts.append("new: " + ", ".join(done))
    if recorded:
        parts.append("facts: " + ", ".join(recorded))
    if revealed:
        parts.append("now known to the player: " + ", ".join(revealed))
    if skipped:
        parts.append("skipped (already recorded): " + "; ".join(skipped))
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
    if problems:
        return ToolOutcome("Scene not changed:\n- " + "\n- ".join(problems), is_error=True)
    try:
        world.set_scene(location, present)
        if hours:
            world.advance_time(hours, reported=True)
    except WorldError as exc:
        return ToolOutcome(f"Scene not changed: {exc}", is_error=True)
    state.world = world
    where = world.entities[location].name if location else "not set"
    here = _names([world.entities[e] for e in world.scene.present]) or "nobody recorded"
    return ToolOutcome(f"Scene: {where}. With the party: {here}. Time: {world.time}.")


RECALL = Tool(schema=RECALL_SCHEMA, handler=recall, phases=ADVENTURE)
ESTABLISH = Tool(schema=ESTABLISH_SCHEMA, handler=establish, phases=ADVENTURE)
SET_SCENE = Tool(schema=SET_SCENE_SCHEMA, handler=set_scene, phases=ADVENTURE)
