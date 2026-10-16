from typing import Any

import d20

from aigm.models import DiceRoll, DiceTerm, DieRoll
from aigm.tools.base import Tool, ToolOutcome

MAX_EXPRESSION_LENGTH = 200
SYNTAX_HINT = "Expected syntax like '1d20+5' or '4d6kh3'."

# The tool description is a prompt: it lives in prompts/tools/roll_dice.md and is added by
# `aigm.tools.tool_schemas()`.
SCHEMA: dict[str, Any] = {
    "name": "roll_dice",
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "A dice expression in d20 syntax, e.g. '1d20+5' or '4d6kh3'.",
            }
        },
        "required": ["expression"],
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


def roll_dice(tool_use_id: str, tool_input: dict[str, Any]) -> ToolOutcome:
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
    try:
        result = d20.roll(dice_part)
        payload = build_roll_payload(tool_use_id, expression, result, comment)
    except d20.RollError as exc:
        return _error(expression, str(exc).strip().splitlines()[0] if str(exc).strip() else "roll failed")
    except Exception as exc:  # d20/lark can raise unexpected errors on odd input
        return _error(expression, f"could not evaluate ({type(exc).__name__})")
    return ToolOutcome(content=result.result, event=payload)


ROLL_DICE = Tool(schema=SCHEMA, handler=roll_dice)
