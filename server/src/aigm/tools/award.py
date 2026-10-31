"""The `award` tool: party members earn experience points or gain levels (docs/PROGRESSION.md).

Advancement is per character: the same XP usually goes to everyone, but not always, and how much a level takes depends
on the character's class and the ruleset. The server keeps the numbers; the GM decides what is earned and, from the
ruleset's own tables, when a level is reached. Every XP award therefore ends by telling the GM to check for level-ups.
Descriptions live in prompts/tools/award.md."""

from typing import Any

from aigm import story as story_rules
from aigm.models import Award, Standing
from aigm.session.state import MAX_CHARACTER_LEVEL, GameState, Hero, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.tools.story import chapter_note

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
                "type": "array",
                "description": "Characters who have just gained a level, one entry each for each level gained.",
                "items": {
                    "type": "object",
                    "properties": {
                        "who": {"type": "string", "description": "The character's name."},
                        "class": {
                            "type": "string",
                            "description": "The class that gained the level: one the character has, or a new one.",
                        },
                        "class_level": {"type": "integer", "description": "The character's level in that class now."},
                        "level": {
                            "type": "integer",
                            "description": "The character's overall level now, by your ruleset's rule (a total of "
                            "the class levels, or the highest).",
                        },
                    },
                    "required": ["who", "class", "class_level", "level"],
                },
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
    return [
        Standing(
            name=n, xp=state.hero(n).xp, level=state.hero(n).level, previous_level=before[n].level,
            classes=dict(state.hero(n).classes),
        )
        for n in before
    ]  # fmt: skip


def _level_ups(state: GameState, raw: Any, problems: list[str]) -> list[tuple[str, str, int, int]]:
    """(name, class, class level, overall level) for each valid entry. Several entries may name one character: they are
    checked in order, each against the state the earlier ones leave."""
    if not isinstance(raw, list) or not raw:
        problems.append("'level_up' must be a list of {who, class, class_level, level} entries")
        return []
    out, seen = [], {n: Hero(h.level, h.xp, dict(h.classes)) for n, h in state.heroes.items()}
    for entry in raw:
        if not isinstance(entry, dict):
            problems.append("each 'level_up' entry must be an object with who, class, class_level and level")
            continue
        name, cls = state.find_hero(entry.get("who", "")), entry.get("class")
        class_level, level = entry.get("class_level"), entry.get("level")
        if name is None:
            problems.append(f"{entry.get('who')!r} is not in the party ({', '.join(state.party_names)})")
            continue
        if not isinstance(cls, str) or not cls.strip():
            problems.append(f"{name}: 'class' must name the class that gained the level")
            continue
        cls = " ".join(cls.split())
        hero = seen.get(name) or Hero(state.start_level)
        have = next((c for c in hero.classes if c.lower() == cls.lower()), None)
        ints = all(isinstance(v, int) and not isinstance(v, bool) for v in (class_level, level))
        if not ints or not 1 <= class_level <= 20:
            problems.append(f"{name}: 'class_level' must be an integer from 1 to 20 and 'level' an integer")
        elif have is not None and class_level != hero.classes[have] + 1:
            problems.append(f"{name}: {have} is level {hero.classes[have]}, so its next level is {hero.classes[have] + 1}")
        elif level <= hero.level or level > MAX_CHARACTER_LEVEL:
            problems.append(f"{name}: the overall level must rise above {hero.level} (and be at most {MAX_CHARACTER_LEVEL})")
        else:
            seen[name] = Hero(level, hero.xp, {**hero.classes, have or cls: class_level})
            out.append((name, have or cls, class_level, level))
    return out


def award(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    xp, reason = tool_input.get("xp"), tool_input.get("reason")
    problems: list[str] = []
    if not state.party_names:
        return ToolOutcome(content="Nothing was awarded: the party has no recorded members.", is_error=True)
    if xp is not None and (isinstance(xp, bool) or not isinstance(xp, int) or not 0 <= xp <= MAX_XP_AWARD):
        problems.append(f"'xp' must be an integer from 0 to {MAX_XP_AWARD}")
    who = _names(state, tool_input["who"], "who", problems) if tool_input.get("who") is not None else state.party_names
    ups = _level_ups(state, tool_input["level_up"], problems) if tool_input.get("level_up") is not None else []
    if not isinstance(reason, str) or not reason.strip():
        problems.append("'reason' must say what earned it")
    if not xp and not ups and not problems:
        problems.append("give 'xp' (to 'who', or to everyone), 'level_up', or both")
    if problems:
        return ToolOutcome(content="Nothing was awarded: " + "; ".join(problems) + ".", is_error=True)
    gained = xp or 0
    receivers = who if gained else []
    touched = list(dict.fromkeys([*receivers, *(u[0] for u in ups)]))
    before = {n: Hero(state.hero(n).level, state.hero(n).xp, dict(state.hero(n).classes)) for n in touched}
    for name in receivers:
        h = state.hero(name)
        state.heroes[name] = Hero(h.level, h.xp + gained, dict(h.classes))
    for name, cls, class_level, level in ups:
        h = state.hero(name)
        state.heroes[name] = Hero(level, h.xp, {**h.classes, cls: class_level})
    for ent in state.world.entities.values():
        if ent.holding is not None and ent.holding.owed == state.turn:
            ent.holding.owed = None  # the award for what the party got this turn is made (docs/KEY_ITEMS.md 6.3)
    average = state.average_level
    notes = []
    if state.story is not None:
        state.story.party_level = average
        if story_rules.chapter_complete(state.story, state.turn):  # reaching the level can be what ends a chapter
            chapter = story_rules.advance_chapter(state.story, state.turn)
            story_rules.settle_ready(state.story, state.world)
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
    lines = [
        f"{s.name}: level {s.level}"
        + (f" ({', '.join(f'{c} {v}' for c, v in s.classes.items())})" if s.classes else "")
        + f", {s.xp} XP"
        + (f" (was level {s.previous_level})" if s.level != s.previous_level else "")
        for s in standings
    ]
    out = ["Awarded. The player has been told. Now:", *lines, f"Average party level: {average:.1f}."]
    if gained:
        out.append(
            "Check each of these characters against your ruleset's advancement table for their class (or classes): if any "
            "has now earned a level, call `award` again with `level_up` giving the class that gains it, its new level and "
            "the character's new overall level, then update their sheets."
        )
    if ups:
        out.append("Update the character sheet of everyone who levelled up (hit points, features, choices).")
    return ToolOutcome(content="\n".join(out + notes), event=event)


AWARD = Tool(schema=SCHEMA, handler=award, phases=frozenset({Phase.ADVENTURE}))
