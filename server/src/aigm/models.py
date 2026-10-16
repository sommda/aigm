"""SSE event models and request models. Field names and shapes follow docs/API.md."""

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
ID_RE = re.compile(ID_PATTERN)


# ---- requests --------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    session_id: str = Field(default="default", pattern=ID_PATTERN)

    @field_validator("message")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be empty")
        return v


# ---- SSE events ------------------------------------------------------------------------


class SSEEvent(BaseModel):
    event: ClassVar[str]

    def payload(self) -> dict[str, Any]:
        return self.model_dump()


class MessageStart(SSEEvent):
    event: ClassVar[str] = "message_start"
    message_id: str
    session_id: str
    phase: str


class Thinking(SSEEvent):
    event: ClassVar[str] = "thinking"
    status: Literal["start", "delta", "end"]
    delta: str | None = None
    duration_ms: int | None = None

    def payload(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class TextDelta(SSEEvent):
    event: ClassVar[str] = "text"
    delta: str


class ToolCall(SSEEvent):
    event: ClassVar[str] = "tool_call"
    tool_use_id: str
    name: str
    input: dict[str, Any]


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


class PhaseChange(SSEEvent):
    event: ClassVar[str] = "phase_change"
    previous: str
    phase: str


class MessageEnd(SSEEvent):
    event: ClassVar[str] = "message_end"
    message_id: str
    stop_reason: str
    usage: dict[str, int]
    phase: str


class ErrorEvent(SSEEvent):
    event: ClassVar[str] = "error"
    code: str
    message: str
    retryable: bool = False
