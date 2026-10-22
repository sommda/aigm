"""The `award` tool: party members earn experience points or gain levels (docs/PROGRESSION.md).

Advancement is per character: the same XP usually goes to everyone, but not always, and how much a level takes depends
on the character's class and the ruleset. The server keeps the numbers; the GM decides what is earned and, from the
ruleset's own tables, when a level is reached. Every XP award therefore ends by telling the GM to check for level-ups.
Descriptions live in prompts/tools/award.md."""

from typing import Any

from aigm import story as story_rules
from aigm.models import Award, Standing
from aigm.session.state import GameState, Hero, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.tools.story import chapter_note

MAX_LEVEL = 20
MAX_XP_AWARD = 1_000_000
MAX_REASON = 160

NAMES = {"type": "array", "items": {"type": "string"}}
SCHEMA: dict[str, Any] = {
    "name": "award",
    "input_schema": {
        "type": "object",
        "properties": {
            "xp": {"type": "integer", "description": "Experience points each of the named characters earns."},
            "who": {
                **NAMES,
                "description": "The characters who earn the XP. Leave it out for the whole party.",
            },
            "level_up": {
                **NAMES,
                "description": "Characters who have just reached their next level. Each goes up exactly one level.",
            },
            "reason": {"type": "string", "description": "What earned it, in a few words (a defeated foe, a quest)."},
        },
        "required": ["reason"],
    },
}


def _names(state: GameState, raw: Any, field: str, problems: list[str]) -> list[str]:
    if not isinstance(raw, list) or not raw or not all(isinstance(n, str) for n in raw):
        problems.append(f"'{field}' must be a list of party member names")
        return []
    found, unknown = [], []
    for n in raw:
        name = state.find_hero(n)
        if name is None:
            unknown.append(n)
        elif name not in found:
            found.append(name)
    if unknown:
        problems.append(f"{', '.join(map(repr, unknown))} is not in the party ({', '.join(state.party_names)})")
    return found


def _standings(state: GameState, before: dict[str, Hero]) -> list[Standing]:
    return [Standing(name=n, xp=state.hero(n).xp, level=state.hero(n).level, previous_level=before[n].level) for n in before]


def award(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    xp, reason = tool_input.get("xp"), tool_input.get("reason")
    problems: list[str] = []
    if not state.party_names:
        return ToolOutcome(content="Nothing was awarded: the party has no recorded members.", is_error=True)
    if xp is not None and (isinstance(xp, bool) or not isinstance(xp, int) or not 0 <= xp <= MAX_XP_AWARD):
        problems.append(f"'xp' must be an integer from 0 to {MAX_XP_AWARD}")
    who = _names(state, tool_input["who"], "who", problems) if tool_input.get("who") is not None else state.party_names
    ups = _names(state, tool_input["level_up"], "level_up", problems) if tool_input.get("level_up") is not None else []
    for name in ups:
        if state.hero(name).level >= MAX_LEVEL:
            problems.append(f"{name} is already at the highest level")
    if not isinstance(reason, str) or not reason.strip():
        problems.append("'reason' must say what earned it")
    if not xp and not ups and not problems:
        problems.append("give 'xp' (to 'who', or to everyone), 'level_up', or both")
    if problems:
        return ToolOutcome(content="Nothing was awarded: " + "; ".join(problems) + ".", is_error=True)
    gained = xp or 0
    receivers = who if gained else []
    touched = list(dict.fromkeys([*receivers, *ups]))
    before = {n: Hero(state.hero(n).level, state.hero(n).xp) for n in touched}
    for name in receivers:
        state.heroes[name] = Hero(state.hero(name).level, state.hero(name).xp + gained)
    for name in ups:
        state.heroes[name] = Hero(state.hero(name).level + 1, state.hero(name).xp)
    average = state.average_level
    notes = []
    if state.story is not None:
        state.story.party_level = average
        if story_rules.chapter_complete(state.story, state.turn):  # reaching the level can be what ends a chapter
            chapter = story_rules.advance_chapter(state.story, state.turn)
            story_rules.settle_ready(state.story)
            notes.append(chapter_note(state.story, chapter))
    standings = _standings(state, before)
    event = Award(
        tool_use_id=tool_use_id,
        xp_gained=gained,
        to=receivers,
        everyone=bool(gained) and set(receivers) == set(state.party_names),
        characters=standings,
        average_level=round(average, 2),
        reason=reason.strip()[:MAX_REASON],
    )
    lines = [f"{s.name}: level {s.level}, {s.xp} XP" + (f" (was level {s.previous_level})" if s.level != s.previous_level else "")
             for s in standings]  # fmt: skip
    out = ["Awarded. The player has been told. Now:", *lines, f"Average party level: {average:.1f}."]
    if gained:
        out.append(
            "Check each of these characters against your ruleset's advancement table for their class: if any has now "
            "earned a level, call `award` again with `level_up` naming them, then update their sheets."
        )
    if ups:
        out.append("Update the character sheet of everyone who levelled up (hit points, features, choices).")
    return ToolOutcome(content="\n".join(out + notes), event=event)


AWARD = Tool(schema=SCHEMA, handler=award, phases=frozenset({Phase.ADVENTURE}))
