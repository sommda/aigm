"""The GM's `social_check` tool: roll a social skill, but only after the player has said what the character says, and
with the dice the ruleset gives for good (or poor) role play and the listener's motives (docs/ROLEPLAY.md 3 to 7).

The GM judges the words (`quality`) and says which of the listener's motives they touch; the server checks that the
words are the player's, works out the boon and builds the dice, so the GM cannot choose its own. The description is a
prompt: prompts/tools/social_check.md."""

from typing import Any

import d20

from aigm import roleplay, rulesets
from aigm.roleplay import EFFECTS, QUALITIES
from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.tools.roll_dice import MIN_NARRATION_CHARS, build_roll_payload
from aigm.world.model import Motive

ADVENTURE = frozenset({Phase.ADVENTURE})
MAX_SKILL_CHARS = 40

SCHEMA: dict[str, Any] = {
    "name": "social_check",
    # Unlike roll_dice, the narration is not streamed while it is written: the call may be refused for want of words,
    # and then nothing of it may reach the player.
    "input_schema": {
        "type": "object",
        "properties": {
            "character": {"type": "string", "description": "The party member who speaks."},
            "skill": {"type": "string", "description": "The ruleset's name for the skill, e.g. Persuasion."},
            "target": {"type": "string", "description": "The recorded person who is being addressed."},
            "spoken": {
                "type": "string",
                "description": "What the player typed for the character to say, quoted or trimmed (at least four "
                "words). It must be the player's own words.",
            },
            "quality": {
                "type": "string",
                "enum": list(QUALITIES),
                "description": "Your judgment of the words: weak, ordinary (the usual), strong or brilliant.",
            },
            "engages": {
                "type": "array",
                "description": "Motives of the target (ids from your notes) that the words touch.",
                "items": {
                    "type": "object",
                    "properties": {
                        "motive": {"type": "string"},
                        "effect": {"type": "string", "enum": list(EFFECTS)},
                    },
                    "required": ["motive", "effect"],
                },
            },
            "modifier": {
                "type": "integer",
                "description": "The character's total modifier for the skill (the charisma reaction adjustment for "
                "a reaction roll), read from the sheet.",
            },
            "dc": {"type": "integer", "description": "The difficulty. Leave out for a reaction roll."},
            "narration": {
                "type": "string",
                "description": "The narration the player reads just before the dice appear: what the character says "
                "and does and what is at stake, in the story's voice. Do not repeat it in your reply.",
            },
        },
        "required": ["character", "skill", "target", "spoken", "quality", "modifier", "narration"],
    },
}


def _refuse(why: str) -> ToolOutcome:
    return ToolOutcome(f"Nothing was rolled: {why}", is_error=True)


NO_WORDS = (
    "The player has not said anything for the character to say. Ask what the character says, in the story's voice, "
    "and end your turn. Do not roll, and do not mention this error to the player."
)


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _natural(payload: Any) -> int | None:
    """The kept d20 of a roll, for a natural 20 or 1."""
    for term in payload.dice:
        if term.sides == 20:
            kept = [r.value for r in term.rolls if r.kept]
            return kept[0] if kept else None
    return None


def _engaged(state: GameState, target_id: str, raw: Any) -> tuple[list[tuple[Motive, str]], str | None]:
    """The motives the GM says the words touch, checked against the world."""
    found: list[tuple[Motive, str]] = []
    for item in raw if isinstance(raw, list) else []:
        motive = state.world.motives.get(item.get("motive")) if isinstance(item, dict) else None
        effect = item.get("effect") if isinstance(item, dict) else None
        if motive is None or effect not in EFFECTS:
            return [], f"`engages` has {item!r}: give a motive id from your notes and an effect of aligned or against"
        if motive.owner != target_id or not state.world.motive_live(motive):
            return [], f"motive {motive.id} is not a live motive of the person being addressed"
        found.append((motive, effect))
    return found, None


def social_check(tool_use_id: str, tool_input: dict[str, Any], state: GameState) -> ToolOutcome:
    world = state.world
    character = state.find_hero(str(tool_input.get("character", "")))
    if character is None:
        return _refuse(f"{tool_input.get('character')!r} is not a party member. Name the player character who speaks.")
    ref = tool_input.get("target")
    target = world.resolve(ref) if isinstance(ref, str) else None
    if target is None or target.kind != "npc":
        return _refuse(f"{ref!r} is not a recorded person. Record them with `establish` first.")
    if target.id not in world.scene.present:
        return _refuse(f"{target.name} is not with the party. Put them in the scene with `set_scene` if they are.")
    problem = roleplay.words_problem(tool_input.get("spoken"), state.player_text)
    if problem:
        return ToolOutcome(f"Nothing was rolled: {problem}. {NO_WORDS}", is_error=True)
    if (state.turn, target.id) in state.social_done:
        return _refuse(
            f"{target.name} has already answered the player's words this turn. A second try needs new words from the "
            "player: ask what the character says next and end your turn."
        )
    skill = tool_input.get("skill")
    quality = tool_input.get("quality")
    if not isinstance(skill, str) or not skill.strip() or len(skill) > MAX_SKILL_CHARS:
        return _refuse("`skill` must be the skill's name.")
    if quality not in QUALITIES:
        return _refuse(f"`quality` must be one of {', '.join(QUALITIES)}.")
    style = rulesets.get(state.ruleset).social_style
    modifier, dc = tool_input.get("modifier"), tool_input.get("dc")
    if not _whole(modifier):
        return _refuse("`modifier` must be a whole number.")
    if style != "reaction" and not (_whole(dc) and 1 <= dc <= 60):
        return _refuse("`dc` must be a whole number from 1 to 60.")
    engaged, problem = _engaged(state, target.id, tool_input.get("engages"))
    if problem:
        return _refuse(problem)
    effect = roleplay.motive_effect(engaged)
    state.social_done.add((state.turn, target.id))
    tells = "; ".join(effect.decided_by.tells) if effect.decided_by and effect.decided_by.tells else ""
    if effect.barred:
        return ToolOutcome(
            f"No roll. {target.name} will not be moved: the words cross something they hold absolutely, and nothing "
            f"the player says or offers changes that. Narrate the refusal in character"
            + (f", and let one tell show ({tells})" if tells else "")
            + ". The player is not told why."
        )
    if effect.auto_success:
        return ToolOutcome(
            f"No roll. What the character asks is something {target.name} already holds to absolutely, so it works. "
            "Narrate it succeeding, with no roll and no mention of why."
        )
    narration = tool_input.get("narration")
    if not isinstance(narration, str) or len(narration.strip()) < MIN_NARRATION_CHARS:
        state.social_done.discard((state.turn, target.id))
        return _refuse("every call needs a `narration` (at least a sentence) shown to the player just before the dice.")

    boon = roleplay.boon_for(quality, effect)
    plan = roleplay.plan_roll(style, boon, modifier, dc if _whole(dc) else None)
    label = skill.strip().lower()
    label += ", well played" if roleplay.QUALITY_BOON[quality] > 0 else ", weak argument" if roleplay.QUALITY_BOON[quality] < 0 else ""
    try:
        result = d20.roll(plan.expression)
        payload = build_roll_payload(tool_use_id, f"{plan.expression} # {label}", result, label)
    except d20.RollError as exc:  # cannot happen for an expression built here, but never leave the turn on it
        return _refuse(f"the dice failed ({exc}).")
    total = result.total
    lines = [f"{skill.strip()} for {character} on {target.name}: {result.result}."]
    if plan.modifier_note:
        lines.append(f"The words earned {plan.modifier_note}.")
    if plan.dc is None:
        lines.append(f"Reaction total {total}: read it on the edition's reaction table.")
    elif style == "circumstance":
        lines.append(f"Against DC {plan.dc}: {roleplay.degree(total, plan.dc, _natural(payload), True)}.")
    else:
        margin = total - plan.dc
        lines.append(f"Against DC {plan.dc}: {'success' if margin >= 0 else 'failure'} by {abs(margin)}.")
    lines.append(
        "Narrate the outcome and how the person reacts"
        + (f"; where the words touched what they want, show it as a tell ({tells})" if tells else "")
        + ". Never state their motive or the DC."
    )
    return ToolOutcome(" ".join(lines), event=payload, say=narration.strip())


SOCIAL_CHECK = Tool(schema=SCHEMA, handler=social_check, phases=ADVENTURE)
