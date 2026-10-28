"""The GM's `set_motive` tool: give a person a motive for the scene, change one that play has changed, or mark that a
tell has been shown (docs/ROLEPLAY.md 7.3). Like the other world tools it works on a copy of the world and replaces
it only if every change is accepted. The description lives in prompts/tools/set_motive.md."""

from typing import Any

from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.world import MOTIVE_KINDS, WorldError

ADVENTURE = frozenset({Phase.ADVENTURE})
MAX_CHANGES = 6
OPS = ("add", "shift", "resolve", "disclose")
SETTABLE_STRENGTHS = ("leaning", "driven")  # absolute is never offered: it is written ahead of play and fixed

_PHRASES = {"type": "array", "items": {"type": "string"}}
SET_MOTIVE_SCHEMA: dict[str, Any] = {
    "name": "set_motive",
    "input_schema": {
        "type": "object",
        "properties": {
            "changes": {
                "type": "array",
                "description": f"What to record, in order (at most {MAX_CHANGES}).",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string", "enum": list(OPS)},
                        "owner": {"type": "string", "description": "add: the recorded person who has the motive."},
                        "id": {"type": "string", "description": "shift, resolve, disclose: the motive's id, like m031."},
                        "text": {
                            "type": "string",
                            "description": "add, shift: what they want, fear or hold to, in one sentence of about 40 "
                            "words, using names rather than pronouns.",
                        },
                        "scope": {
                            "type": "string",
                            "enum": ["scene", "underlying"],
                            "description": "add: scene (default) is what they are after right now, in this place.",
                        },
                        "kind": {"type": "string", "enum": list(MOTIVE_KINDS)},
                        "strength": {
                            "type": "string",
                            "enum": list(SETTABLE_STRENGTHS),
                            "description": "leaning tilts a result; driven shapes it.",
                        },
                        "moved_by": {**_PHRASES, "description": "Kinds of argument or offer that engage it."},
                        "resists": {**_PHRASES, "description": "Kinds that bounce off."},
                        "tells": {**_PHRASES, "description": "Behavior that hints at it, without stating it."},
                        "outcome": {"type": "string", "enum": ["satisfied", "frustrated"], "description": "resolve."},
                    },
                    "required": ["op"],
                },
            }
        },
        "required": ["changes"],
    },
}


def _phrases(raw: dict[str, Any], key: str) -> list[str] | None:
    value = raw.get(key)
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else None


def _change(world: Any, state: GameState, raw: dict[str, Any]) -> str:
    """Apply one change to `world` and say what happened. Raises WorldError with a message for the model."""
    op = raw.get("op")
    if op not in OPS:
        raise WorldError(f"op must be one of {', '.join(OPS)}")
    if op == "add":
        ref = raw.get("owner")
        if isinstance(ref, str) and state.find_hero(ref):
            raise WorldError("party members' motives belong to the player; give motives to other people only")
        owner = world.resolve(ref) if isinstance(ref, str) else None
        if owner is None:
            raise WorldError(f"{ref!r} is not a recorded person; add them with `establish` first")
        strength = raw.get("strength") or "leaning"
        if strength not in SETTABLE_STRENGTHS:
            raise WorldError("strength must be leaning or driven (an absolute motive cannot be created in play)")
        motive = world.add_motive(
            owner.id, raw.get("text"), scope=raw.get("scope") or "scene", kind=raw.get("kind") or "want",
            strength=strength, moved_by=_phrases(raw, "moved_by") or (), resists=_phrases(raw, "resists") or (),
            tells=_phrases(raw, "tells") or (), source="improvised", turn=state.turn,
        )  # fmt: skip
        return f"{motive.id}: {owner.name}, {motive.kind} ({motive.strength}, {motive.scope})"
    motive_id = raw.get("id")
    if not isinstance(motive_id, str):
        raise WorldError(f"{op} needs the motive's `id`")
    if op == "shift":
        if raw.get("strength") is not None and raw["strength"] not in SETTABLE_STRENGTHS:
            raise WorldError("strength must be leaning or driven")
        new = world.shift_motive(
            motive_id, text=raw.get("text"), kind=raw.get("kind"), strength=raw.get("strength"),
            moved_by=_phrases(raw, "moved_by"), resists=_phrases(raw, "resists"), tells=_phrases(raw, "tells"),
            source="play", turn=state.turn,
        )  # fmt: skip
        return f"{motive_id} replaced by {new.id}"
    if op == "resolve":
        world.resolve_motive(motive_id, raw.get("outcome"))
        return f"{motive_id} {raw['outcome']}"
    world.disclose_motive(motive_id, "hinted")
    return f"{motive_id}: the player has now seen a tell"


def set_motive(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    changes = tool_input.get("changes")
    if not isinstance(changes, list) or not changes:
        return ToolOutcome("Give `changes`: a list of motives to add, shift, resolve or disclose.", is_error=True)
    if len(changes) > MAX_CHANGES:
        return ToolOutcome(f"Too much at once: at most {MAX_CHANGES} changes per call.", is_error=True)
    world = state.world.copy()  # all or nothing
    done: list[str] = []
    problems: list[str] = []
    for i, raw in enumerate(changes, 1):
        try:
            if not isinstance(raw, dict):
                raise WorldError("each change must be an object with an `op`")
            done.append(_change(world, state, raw))
        except WorldError as exc:
            problems.append(f"change {i}: {exc}")
    if problems:
        return ToolOutcome(
            "Nothing was recorded:\n- " + "\n- ".join(problems) + "\nFix these and call set_motive again.", is_error=True
        )
    state.world = world
    return ToolOutcome("Recorded. " + "; ".join(done))


SET_MOTIVE = Tool(schema=SET_MOTIVE_SCHEMA, handler=set_motive, phases=ADVENTURE)
