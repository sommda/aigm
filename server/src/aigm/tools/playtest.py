"""The playtest tools (docs/PLAYTEST.md): offered only while a debug server's playtest mode is on. They set up what the
other tools cannot: leaving the mode, setting the clock to any moment, and setting a character's level directly.
Descriptions live in prompts/tools/."""

from typing import Any

from aigm import story as story_rules
from aigm.session.state import MAX_CHARACTER_LEVEL, GameState, Hero, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.tools.story import chapter_note
from aigm.world import WorldTime

ADVENTURE = frozenset({Phase.ADVENTURE})


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


END_PLAYTEST_SCHEMA: dict[str, Any] = {"name": "end_playtest", "input_schema": {"type": "object", "properties": {}}}


def end_playtest(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    state.playtest = False
    state.pass_now = True  # the curator then reconciles the world with what the playtest changed
    return ToolOutcome(
        "Playtest mode is over. Tell the developer in a line that the game is back; the next message is the story, "
        "which continues from the scene as it now stands. Everything said in the playtest is out of the story."
    )


TIME_SCHEMA: dict[str, Any] = {
    "name": "playtest_time",
    "input_schema": {
        "type": "object",
        "properties": {
            "day": {"type": "integer", "description": "The day number, 1 or more."},
            "hour": {"type": "integer", "description": "The hour, 0 to 23."},
            "minute": {"type": "integer", "description": "The minute, 0 to 59. Default 0."},
        },
        "required": ["day", "hour"],
    },
}


def playtest_time(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    day, hour, minute = (tool_input.get(k, 0 if k == "minute" else None) for k in ("day", "hour", "minute"))
    if not (_int(day) and _int(hour) and _int(minute) and day >= 1 and 0 <= hour <= 23 and 0 <= minute <= 59):
        return ToolOutcome("The clock is unchanged: day must be 1 or more, hour 0-23, minute 0-59.", is_error=True)
    state.world.reset_time(WorldTime(day, hour, minute))
    return ToolOutcome(f"The clock now reads {state.world.time}.")


HERO_SCHEMA: dict[str, Any] = {
    "name": "playtest_hero",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The party member."},
            "level": {"type": "integer", "description": f"Their overall level, 1 to {MAX_CHARACTER_LEVEL}."},
            "xp": {"type": "integer", "description": "Their experience points. Leave out to keep them."},
            "classes": {
                "type": "object",
                "additionalProperties": {"type": "integer"},
                "description": "Their level in each class, replacing the record. Leave out to keep it.",
            },
        },
        "required": ["name", "level"],
    },
}


def playtest_hero(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    name = state.find_hero(str(tool_input.get("name", "")))
    if name is None:
        return ToolOutcome(f"No such party member. The party is: {', '.join(state.party_names) or 'nobody'}.", is_error=True)
    level, xp, classes = tool_input.get("level"), tool_input.get("xp"), tool_input.get("classes")
    if not _int(level) or not 1 <= level <= MAX_CHARACTER_LEVEL:
        return ToolOutcome(f"The level must be a whole number from 1 to {MAX_CHARACTER_LEVEL}.", is_error=True)
    if xp is not None and (not _int(xp) or xp < 0):
        return ToolOutcome("The XP must be a whole number, 0 or more.", is_error=True)
    if classes is not None and not (
        isinstance(classes, dict) and all(isinstance(c, str) and _int(v) and 1 <= v <= 20 for c, v in classes.items())
    ):
        return ToolOutcome("The classes must map class names to levels from 1 to 20.", is_error=True)
    old = state.hero(name)
    state.heroes[name] = Hero(level, old.xp if xp is None else xp, dict(old.classes if classes is None else classes))
    return ToolOutcome(f"{name} is now level {level}. Update the character sheet to match (update_character).")


STORY_SCHEMA: dict[str, Any] = {
    "name": "playtest_story",
    "input_schema": {
        "type": "object",
        "properties": {
            "chapter": {
                "type": "integer",
                "description": "Jump to this chapter, 1 to 3. Quests of earlier chapters still open are skipped.",
            },
            "goal_revealed": {"type": "boolean", "description": "Set whether the party knows the final goal."},
            "quests": {
                "type": "array",
                "description": "Quests to set to a status whatever it is now, by id.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "active", "done", "skipped", "failed"]},
                    },
                    "required": ["id", "status"],
                },
            },
        },
    },
}
PLAYTEST_OUTCOME = "Settled in playtest."


def playtest_story(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    story = state.story
    if story is None or story.concluded or not story.planned:
        return ToolOutcome("There is no running, planned story to change.", is_error=True)
    chapter, revealed, quests = tool_input.get("chapter"), tool_input.get("goal_revealed"), tool_input.get("quests", [])
    if chapter is not None and not (_int(chapter) and 1 <= chapter <= 3):
        return ToolOutcome("The chapter must be 1, 2 or 3.", is_error=True)
    if revealed is not None and not isinstance(revealed, bool):
        return ToolOutcome("'goal_revealed' must be true or false.", is_error=True)
    if not isinstance(quests, list):
        return ToolOutcome("'quests' must be a list.", is_error=True)
    work, notes = story.copy(), []
    for q in quests:
        m = work.milestone(str(q.get("id"))) if isinstance(q, dict) else None
        if m is None or q.get("status") not in ("pending", "active", "done", "skipped", "failed"):
            return ToolOutcome(f"Bad quest entry {q!r}: use an id from the story notes and a valid status.", is_error=True)
        m.status = q["status"]
        m.outcome = m.outcome or (PLAYTEST_OUTCOME if m.status in ("done", "skipped", "failed") else None)
        m.done_turn = state.turn if m.status in ("done", "skipped", "failed") else None
        notes.append(f"{m.id} is now {m.status}.")
    if work.goal is not None and (revealed is not None or chapter is not None and chapter > 1):
        work.goal.revealed = revealed if revealed is not None else True
        notes.append(f"The goal is {'known' if work.goal.revealed else 'unknown'} to the party.")
    if chapter is not None:
        for m in work.milestones:
            if m.chapter < chapter and m.status not in story_rules.SETTLED:
                m.status, m.outcome, m.done_turn = "skipped", PLAYTEST_OUTCOME, state.turn
        work.chapter, work.chapter_started_turn, work.last_progress_turn = chapter, state.turn, state.turn
        notes.append(chapter_note(work, chapter))
    story_rules.settle_ready(work, state.world)
    state.story = work
    return ToolOutcome(" ".join(notes) or "Nothing was changed.")


END_PLAYTEST = Tool(schema=END_PLAYTEST_SCHEMA, handler=end_playtest, phases=ADVENTURE, playtest_only=True)
PLAYTEST_TIME = Tool(schema=TIME_SCHEMA, handler=playtest_time, phases=ADVENTURE, playtest_only=True)
PLAYTEST_HERO = Tool(schema=HERO_SCHEMA, handler=playtest_hero, phases=ADVENTURE, playtest_only=True)
PLAYTEST_STORY = Tool(
    schema=STORY_SCHEMA, handler=playtest_story, phases=ADVENTURE, playtest_only=True, story_only=True
)
