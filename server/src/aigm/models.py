"""SSE event models. Field names and shapes follow docs/API.md."""

from typing import ClassVar

from pydantic import BaseModel


class SSEEvent(BaseModel):
    event: ClassVar[str]


class DieRoll(BaseModel):
    value: int
    kept: bool
    values: list[int]


class DiceTerm(BaseModel):
    notation: str
    count: int
    sides: int
    total: int
    annotation: str | None
    rolls: list[DieRoll]


class DiceRoll(SSEEvent):
    event: ClassVar[str] = "dice_roll"

    tool_use_id: str
    expression: str
    total: int | float
    result: str
    crit: str
    comment: str | None
    dice: list[DiceTerm]
