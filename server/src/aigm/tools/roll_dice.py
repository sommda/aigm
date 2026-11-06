from typing import Any

import d20

from aigm import attempts
from aigm.models import DiceRoll, DiceTerm, DieRoll
from aigm.roleplay import SOCIAL_SKILL
from aigm.session.state import GameState, Phase
from aigm.tools.base import Tool, ToolOutcome
from aigm.tools.attempt import attempts_active, closed_result, read_attempt, settle, start_try
from aigm.tools.timing import MINUTES_PROPERTY, read_minutes, spend

MAX_EXPRESSION_LENGTH = 200
MIN_NARRATION_CHARS = 10
SYNTAX_HINT = "Expected syntax like '1d20+5' or '4d6kh3'."

# The tool description is a prompt: it lives in prompts/tools/roll_dice.md and is added by
# `aigm.tools.tool_schemas()`.
SCHEMA: dict[str, Any] = {
    "name": "roll_dice",
    # The API normally buffers each parameter until it is complete; this sends the narration as it is written, so
    # it can be shown to the player word by word (docs/NARRATION_STREAMING.md). The input is then not validated by
    # the API, so the tool checks it itself.
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "A dice expression in d20 syntax, e.g. '1d20+5' or '4d6kh3'.",
            },
            "narration": {
                "type": "string",
                "description": (
                    "The narration the player reads just before the dice appear: what is happening, what the "
                    "character attempts and what is at stake, in the story's voice. It is shown as part of the "
                    "story, so do not repeat it in your reply."
                ),
            },
            "minutes": MINUTES_PROPERTY,
            "dc": {
                "type": "integer",
                "description": (
                    "The number the roll must meet or beat, fixed before you roll, when the roll has a difficulty. "
                    "The result then says whether it succeeded or failed and by how much. Never tell the player."
                ),
            },
            "attempt": {
                "type": "object",
                "description": (
                    "What this roll is for, when it tests a task that can fail and be tried again or closed: pick a "
                    "lock, climb a cliff, search a room. Needs `dc`. Leave it out of rolls that are not tasks (damage, "
                    "initiative, attribute values, random tables, attacks)."
                ),
                "properties": {
                    "who": {"type": "string", "description": "The party member who tries."},
                    "kind": {"type": "string", "enum": [k for k in attempts.KINDS if k != "social"]},
                    "task": {"type": "string", "description": "Two to twelve words: \"pick the vault lock\"."},
                    "about": {"type": "string", "description": "What it concerns (an entity). Default: the party's place."},
                    "failure": {
                        "type": "string",
                        "description": "Up to 25 words completing \"...and failed; ___\": what failing costs or shows.",
                    },
                    "closes": {"type": "boolean", "description": "Override the kind's rule: close (or keep open) on failure."},
                    "reopens_if": {"type": "string", "description": "GM only: what would reopen it if it closes."},
                    "after_minutes": {"type": "integer", "description": "A closure that lifts by itself after this long."},
                    "scope": {"type": "string", "enum": list(attempts.SCOPES)},
                    "changed": {"type": "string", "description": "What is new since a closed attempt, to roll it again."},
                    "opens": {
                        "description": "The blocked way a success opens: {from, to} places, or the words of a way out of here.",
                    },
                },
                "required": ["who", "kind", "task", "failure"],
            },
            "dc_mode": {
                "type": "string",
                "enum": list(attempts.DC_MODES),
                "description": "`under` when the roll succeeds at or below the dc (roll-under checks). Default `over`.",
            },
        },
        "required": ["expression", "narration"],
    },
}


def _find_dice(node: Any) -> list[d20.Dice]:
    found: list[d20.Dice] = []
    if isinstance(node, d20.Dice):
        found.append(node)
    for child in node.children:
        found.extend(_find_dice(child))
    return found


def _notation(dice: d20.Dice) -> str:
    ops = ""
    for op in dice.operations:
        ops += op.op
        for sel in op.sels:
            ops += f"{sel.cat or ''}{sel.num}"
    return f"{dice.num}d{dice.size}{ops}"


def build_roll_payload(
    tool_use_id: str, expression: str, result: d20.RollResult, comment: str | None = None
) -> DiceRoll:
    terms = []
    for dice in _find_dice(result.expr):
        rolls = []
        for die in dice.values:
            values = [int(v.total) for v in die.values]
            rolls.append(DieRoll(value=values[-1], kept=bool(die.kept), values=values))
        terms.append(
            DiceTerm(
                notation=_notation(dice),
                count=dice.num,
                sides=dice.size,
                total=int(dice.total),
                annotation=dice.annotation,
                rolls=rolls,
            )
        )
    return DiceRoll(
        tool_use_id=tool_use_id,
        expression=expression,
        total=result.total,
        result=result.result,
        crit=d20.CritType(result.crit).name.lower(),
        comment=comment,
        dice=terms,
    )


def _error(expression: Any, detail: str) -> ToolOutcome:
    return ToolOutcome(
        content=f"Invalid dice expression {expression!r}: {detail}. {SYNTAX_HINT}",
        is_error=True,
    )


def _missing_narration() -> ToolOutcome:
    return ToolOutcome(
        content=(
            "Nothing was rolled: every roll_dice call needs a `narration` (at least a sentence) that tells the player "
            "what is happening and what is at stake. It is shown as story text just before the dice. Call it again "
            "with the narration, and do not mention this error to the player."
        ),
        is_error=True,
    )


def roll_dice(tool_use_id: str, tool_input: dict[str, Any], state: GameState | None = None) -> ToolOutcome:
    narration = tool_input.get("narration")
    if not isinstance(narration, str) or len(narration.strip()) < MIN_NARRATION_CHARS:
        return _missing_narration()
    minutes, minutes_problem = read_minutes(tool_input)
    if minutes_problem:
        return ToolOutcome(f"Nothing was rolled: {minutes_problem}.", is_error=True)
    dc, dc_mode, dc_problem = attempts.read_dc(tool_input)
    if dc_problem:
        return ToolOutcome(f"Nothing was rolled: {dc_problem}.", is_error=True)
    expression = tool_input.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        return _error(expression, "expression must be a non-empty string")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        return _error(
            expression[:30] + "...", f"expression is longer than {MAX_EXPRESSION_LENGTH} characters"
        )
    # d20's own comment support treats any trailing junk as a comment (e.g. '2x20' -> 2),
    # so split off a '# comment' ourselves and parse the rest strictly.
    dice_part, _, comment_part = expression.partition("#")
    comment = comment_part.strip() or None
    if comment and SOCIAL_SKILL.search(comment) and state is not None and state.phase is Phase.ADVENTURE:
        return ToolOutcome(
            "Nothing was rolled: a social check is made with `social_check`, once the player has said what the "
            "character says. If they have not, ask them what the character says and end your turn. Do not mention "
            "this error to the player.",
            is_error=True,
        )
    plan, earlier = None, None
    if dc is not None and tool_input.get("attempt") is None and attempts_active(state):
        kind = attempts.task_kind(comment)
        if kind is not None:
            return ToolOutcome(
                f"Nothing was rolled: this roll tests a task (it looks like a `{kind}`) but has no `attempt`, so a failure "
                "would leave no record and nothing to stop a retry. Call it again with `attempt` (who, kind, task, "
                "failure: what failing costs), or, if it is not a task someone could fail at and retry, leave out the "
                "`dc` and read the total yourself. Do not mention this to the player.",
                is_error=True,
            )
    if tool_input.get("attempt") is not None and attempts_active(state):
        assert state is not None
        if dc is None:
            return ToolOutcome(
                "Nothing was rolled: an `attempt` needs a `dc`. Decide the difficulty first (roll the opposition and use "
                "its total, or the passive figure for the task) and call again. Do not mention this to the player.",
                is_error=True,
            )
        plan, problems = read_attempt(tool_input["attempt"], state, minutes)
        if plan is None:
            return ToolOutcome(f"Nothing was rolled: {'; '.join(problems)}.", is_error=True)
        earlier, shut = start_try(state, plan)
        if shut and earlier is not None:
            return ToolOutcome(closed_result(earlier, narration), say=narration.strip())
    try:
        result = d20.roll(dice_part)
        payload = build_roll_payload(tool_use_id, expression, result, comment)
    except d20.RollError as exc:
        return _error(expression, str(exc).strip().splitlines()[0] if str(exc).strip() else "roll failed")
    except Exception as exc:  # d20/lark can raise unexpected errors on odd input
        return _error(expression, f"could not evaluate ({type(exc).__name__})")
    passed = spend(state, plan.minutes if plan else minutes, plan.task if plan else comment or "an action")
    verdict = attempts.verdict_text(result.total, dc, dc_mode) if dc is not None else ""
    recorded = settle(state, plan, earlier, attempts.margin(result.total, dc, dc_mode)) if plan and dc is not None else ""
    content = " ".join(part for part in (result.result, verdict, passed, recorded) if part)
    return ToolOutcome(content=content, event=payload, say=narration.strip())


ROLL_DICE = Tool(schema=SCHEMA, handler=roll_dice)
