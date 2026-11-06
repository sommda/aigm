"""The `defeat` tool: the whole party is out of the fight (docs/STAKES.md 7.5). The description is a prompt:
prompts/tools/defeat.md."""

from typing import Any

from aigm import story as story_rules
from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome

MAX_AFTERMATH = 600

SCHEMA: dict[str, Any] = {
    "name": "defeat",
    "input_schema": {
        "type": "object",
        "properties": {
            "how": {"type": "string", "enum": list(story_rules.DEFEAT_HOWS)},
            "aftermath": {
                "type": "string",
                "description": "Where the party is and what state they are in: a position they can act from.",
            },
            "cost": {"type": "string", "description": "One sentence: what the defeat cost the party."},
            "cost_kind": {"type": "string", "enum": list(story_rules.COST_KINDS)},
            "elapsed_hours": {"type": "integer", "description": "Whole hours that pass before the party can act."},
        },
        "required": ["how", "aftermath", "elapsed_hours"],
    },
}


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def defeat(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    how, aftermath, hours = tool_input.get("how"), tool_input.get("aftermath"), tool_input.get("elapsed_hours")
    story = state.story
    problems: list[str] = []
    if how not in story_rules.DEFEAT_HOWS:
        problems.append(f"`how` must be one of: {', '.join(story_rules.DEFEAT_HOWS)}")
    if not isinstance(aftermath, str) or not aftermath.strip():
        problems.append("`aftermath` is required: where the party is, in a position they can act from")
    aftermath = " ".join(aftermath.split())[:MAX_AFTERMATH] if isinstance(aftermath, str) else ""
    if not _whole(hours) or hours < 0:
        problems.append("`elapsed_hours` must be a whole number of hours")
    if story is not None and (story.concluded or story.fall is not None):
        problems.append("the story is already lost or over")
    if problems:
        return ToolOutcome("Not recorded:\n- " + "\n- ".join(problems), is_error=True)
    assert isinstance(how, str) and isinstance(hours, int)

    if story is not None and story.chapter == story_rules.CHAPTERS[-1]:  # the endgame: a defeat is the end
        story_rules.lose(story, state.turn, f"the party was defeated: {aftermath}")
        story.choices = [*story.choices, {"turn": state.turn, "milestone": "", "note": f"The party was defeated: {aftermath}"}][
            -story_rules.MAX_CHOICES :
        ]
        return ToolOutcome(
            "The party is defeated, and in the endgame that is the end. Finish the scene, then play out the failure "
            "ending your next notes name and call `end_story`."
        )

    notes: list[str] = []
    cost: tuple[str, str] | None = None
    response = story_rules.failure_response(story) if story is not None else None
    if story is not None and response is not None and response.cost_required:
        text, kind = tool_input.get("cost"), tool_input.get("cost_kind")
        if not isinstance(text, str) or not text.strip() or kind not in response.cost_kinds:
            problems.append(f"say what the defeat cost: `cost` (one sentence) and a `cost_kind` of {', '.join(response.cost_kinds)}")
        else:
            cost = (kind, text)
    chapter = story.chapter if story is not None else 1
    limit = story_rules.MAX_DEFEAT_HOURS.get(chapter, 24)
    least = 0
    if story is not None and chapter == 2:
        least = story_rules.wipe_minimum(story.wipes + 1)
    if hours < least:
        problems.append(f"this is wipe number {story.wipes + 1 if story else 1} of the chapter: at least {least} hours pass")
    elif hours > limit:
        problems.append(f"at most {limit} hours can pass")
    elif hours < 1 and how == "taken":
        problems.append("a captivity lasts at least an hour")
    if problems:
        return ToolOutcome("Not recorded:\n- " + "\n- ".join(problems), is_error=True)

    escape_hours: int | None = None
    scene_only = False
    if story is not None:
        if chapter == 2:
            story.wipes += 1
        if how == "taken":
            hours, protect, escape_hours = story_rules.protect_capture(story, state.world, state.turn, hours)
            notes += protect
            scene_only = escape_hours is not None and escape_hours < story_rules.CAPTURE_RESERVE_MIN
        if cost is not None:
            story_rules.record_cost(story, state.turn, "", cost[0], cost[1], clock=False)
        story.choices = [*story.choices, {"turn": state.turn, "milestone": "", "note": f"The party was defeated ({how}): {aftermath}"}][
            -story_rules.MAX_CHOICES :
        ]
        if how == "taken" and not scene_only:
            story.escape = {"turn": state.turn, "held": aftermath, "hours": escape_hours}
            notes.append(
                "A way out is being written as a quest. Until it appears, narrate the captivity and keep the party "
                "able to act; do not free them yourself."
            )
        elif how == "taken":
            notes.append("There is little time left, so the escape is a scene, not a quest: play it now.")
        if chapter == 2:
            prices = story_rules.WIPE_PRICES[min(story.wipes, len(story_rules.WIPE_PRICES)) - 1]
            notes.append(f"Wipe number {story.wipes}: a price like {prices} fits.")
    if hours:
        state.world.advance_minutes(hours * 60, reported=True, turn=state.turn, why=f"the party was defeated ({how})")
    return ToolOutcome(
        f"The party is defeated ({how}); {hours} hours pass. Time: {state.world.time}. Narrate the aftermath: {aftermath} "
        "Update every sheet (hit points, conditions, what was taken) with `update_character`." + "".join(f" {n}" for n in notes)
    )


DEFEAT = Tool(schema=SCHEMA, handler=defeat, phases=frozenset({Phase.ADVENTURE}))
