"""The GM's story tools (docs/STORY.md 8, 9): reporting progress (a field of `set_scene`) and `end_story`."""

from typing import Any

from aigm import story as story_rules
from aigm.session.state import GameState, Phase
from aigm.story import SETTLED, Story
from aigm.tools.base import Tool, ToolOutcome

MAX_REPORTS = 6
MAX_OUTCOME = 600
MAX_EPILOGUE = 3000

# What `set_scene` gains in a story game; the description is a prompt: prompts/tools/set_scene_story.md.
STORY_PROPERTY: dict[str, Any] = {
    "story": {
        "type": "object",
        "properties": {
            "quests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "The quest id from your story notes, such as m03."},
                        "status": {"type": "string", "enum": ["done", "skipped", "failed"]},
                        "outcome": {
                            "type": "string",
                            "description": "One or two sentences: what happened and what the party chose.",
                        },
                    },
                    "required": ["id", "status", "outcome"],
                },
                "description": "Quests that were finished, bypassed or can no longer be done.",
            },
            "goal_revealed": {
                "type": "boolean",
                "description": "True when the party has learned what the final goal is.",
            },
        },
    }
}


CARRY_ON = (
    "This changes the notes, not the scene: carry on exactly where the action stands, finish what the player "
    "just set in motion, and do not skip ahead or open a new scene because of it."
)


def check_story_report(report: Any, state: GameState) -> tuple[Story | None, list[str], list[str]]:
    """Check the `story` field of a set_scene call against `state.story`.

    Returns (the story with the report applied, problems, notes for the GM). The state is not changed: the caller
    keeps the new story only if the rest of the call is fine too, so a call is all or nothing."""
    story = state.story
    if story is None:
        return None, ["this game has no story to report on"], []
    if not isinstance(report, dict):
        return None, ["'story' must be an object"], []
    quests, revealed = report.get("quests", []), report.get("goal_revealed")
    if not isinstance(quests, list) or len(quests) > MAX_REPORTS:
        return None, [f"'quests' must be a list of at most {MAX_REPORTS}"], []
    if revealed is not None and not isinstance(revealed, bool):
        return None, ["'goal_revealed' must be true or false"], []
    work, problems, notes = story.copy(), [], []
    if revealed and work.goal is not None and not work.goal.revealed:
        work.goal.revealed = True
        work.last_progress_turn = state.turn
        notes.append("The player now knows the goal.")
    for q in quests:
        if not isinstance(q, dict):
            problems.append("each quest report must be an object with id, status and outcome")
            continue
        outcome = q.get("outcome")
        outcome = outcome.strip()[:MAX_OUTCOME] if isinstance(outcome, str) else ""
        result = story_rules.report(work, str(q.get("id")), str(q.get("status")), outcome, state.turn)
        if not result.ok:
            problems.append(f"{q.get('id')}: {result.message}")
            continue
        notes.append(result.message + ".")
        reward = work.milestone(str(q.get("id")))
        if q.get("status") == "done" and reward is not None and reward.gives:
            notes.append(f"Its reward: {reward.gives}. Hand it out now, with the `award` tool for any XP or level.")
        if result.opened:
            notes.append("Now active: " + ", ".join(result.opened) + ".")
        if result.advanced_to:
            notes.append(chapter_note(work, result.advanced_to))
    if not problems and story_rules.chapter_complete(work, state.turn):  # learning the goal can be what finishes chapter 1
        chapter = story_rules.advance_chapter(work, state.turn)
        story_rules.settle_ready(work)
        notes.append(chapter_note(work, chapter))
    if notes:
        notes.append(CARRY_ON)
    return (None, problems, []) if problems else (work, [], notes)


def chapter_note(story: Story, chapter: int) -> str:
    title = story_rules.chapter_label(story)
    if not story.in_chapter(chapter):
        return f'Chapter {chapter} begins ("{title}"). Its quests are not planned yet: keep the story moving.'
    return f'Chapter {chapter} begins ("{title}"). Your story notes show its quests.'


# ---- end_story ----------------------------------------------------------------------------

END_STORY_SCHEMA: dict[str, Any] = {
    "name": "end_story",
    "input_schema": {
        "type": "object",
        "properties": {
            "ending": {
                "type": "string",
                "description": "The id of the ending that fits (such as end1), or end_custom if none of them does.",
            },
            "epilogue": {
                "type": "string",
                "description": "Two or three sentences: what becomes of the world and the people the party met.",
            },
            "party_defeated": {
                "type": "boolean",
                "description": "True only if the whole party has fallen or the story can no longer continue.",
            },
        },
        "required": ["ending", "epilogue"],
    },
}


def end_story(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    story = state.story
    if story is None:
        return ToolOutcome("This game has no story to end.", is_error=True)
    if story.concluded:
        return ToolOutcome("The story has already ended.", is_error=True)
    ending, epilogue = tool_input.get("ending"), tool_input.get("epilogue")
    if not isinstance(ending, str) or not isinstance(epilogue, str) or not epilogue.strip():
        return ToolOutcome("Give the ending id and an epilogue.", is_error=True)
    defeated = tool_input.get("party_defeated") is True
    if not defeated:
        climax = story.chapter == 3 and all(m.status in SETTLED | {"failed"} for m in story.in_chapter(3) if m.required)
        if not climax:
            return ToolOutcome(
                "The story is not at its end yet: chapter 3 and its quests must be finished first. "
                "If the whole party has fallen, set party_defeated.",
                is_error=True,
            )
    result = story_rules.conclude(story.copy(), ending, epilogue[:MAX_EPILOGUE])
    if not result.ok:
        known = ", ".join([e.id for e in story.endings] + ["end_custom"])
        return ToolOutcome(f"Cannot end the story: {result.message}. Choose one of: {known}.", is_error=True)
    story_rules.conclude(story, ending, epilogue[:MAX_EPILOGUE])
    return ToolOutcome(
        "The story has ended. Write the final scene and the epilogue now, then tell the player the story is over "
        "and offer to keep playing in this world as an endless game."
    )


END_STORY = Tool(
    schema=END_STORY_SCHEMA, handler=end_story, phases=frozenset({Phase.ADVENTURE}), story_only=True
)
