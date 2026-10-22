"""Typed events mirroring the SSE events in docs/API.md. Parsing is tolerant: missing
fields get defaults and unknown event types become `Unknown` (forward compatibility)."""

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MessageStart:
    message_id: str = ""
    session_id: str = ""
    phase: str = ""  # "session_zero" | "adventure" ("" from servers that do not report it)
    ruleset_name: str = ""  # short display name such as "AD&D 1e" ("" from older servers)


@dataclass(frozen=True)
class Thinking:
    status: str = "start"  # "start" | "delta" | "end"
    delta: str = ""
    duration_ms: int | None = None


@dataclass(frozen=True)
class Text:
    delta: str = ""


@dataclass(frozen=True)
class ToolCall:
    tool_use_id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DieRoll:
    value: int
    kept: bool = True
    values: tuple[int, ...] = ()


@dataclass(frozen=True)
class DiceTerm:
    notation: str = ""
    count: int = 0
    sides: int = 0
    total: int = 0
    annotation: str | None = None
    rolls: tuple[DieRoll, ...] = ()


@dataclass(frozen=True)
class DiceRoll:
    tool_use_id: str = ""
    expression: str = ""
    total: float | int | None = None
    result: str = ""
    crit: str = "none"
    comment: str | None = None
    dice: tuple[DiceTerm, ...] = ()


@dataclass(frozen=True)
class Status:
    """Progress of a long wait (for example "Preparing the world..."); `done` ends it."""

    stage: str = ""
    message: str = ""
    done: bool = False


@dataclass(frozen=True)
class MessageEnd:
    message_id: str = ""
    stop_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    phase: str = ""
    ruleset_name: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)  # timings and token use of the turn
    story: dict[str, Any] | None = None  # story games: {"length", "chapter", "chapter_title", "ended"}


@dataclass(frozen=True)
class PhaseChange:
    previous: str = ""
    phase: str = ""


@dataclass(frozen=True)
class ChapterChange:
    previous: int = 0
    chapter: int = 0
    title: str = ""


@dataclass(frozen=True)
class Standing:
    name: str = ""
    xp: int = 0
    level: int = 1
    previous_level: int = 1
    classes: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Award:
    """Some of the party earned XP (`xp_gained` each, to `to`, or everyone) and/or levels (the standings that rose)."""

    xp_gained: int = 0
    to: tuple[str, ...] = ()
    everyone: bool = False
    characters: tuple[Standing, ...] = ()
    average_level: float = 1.0
    reason: str = ""


@dataclass(frozen=True)
class ErrorEvent:
    code: str = "internal_error"
    message: str = ""
    retryable: bool = False


@dataclass(frozen=True)
class Unknown:
    name: str
    data: Any = None


Event = MessageStart | Thinking | Text | ToolCall | DiceRoll | Status | MessageEnd | PhaseChange | ChapterChange | Award | ErrorEvent | Unknown


def _die(d: dict[str, Any]) -> DieRoll:
    return DieRoll(
        value=int(d.get("value", 0)),
        kept=bool(d.get("kept", True)),
        values=tuple(int(v) for v in d.get("values", [])),
    )


def _term(d: dict[str, Any]) -> DiceTerm:
    return DiceTerm(
        notation=str(d.get("notation", "")),
        count=int(d.get("count", 0)),
        sides=int(d.get("sides", 0)),
        total=int(d.get("total", 0)),
        annotation=d.get("annotation"),
        rolls=tuple(_die(r) for r in d.get("rolls", [])),
    )


def parse_event(name: str, data: str) -> Event | None:
    """Return a typed event, or None if `data` is not a JSON object (event is skipped)."""
    try:
        d = json.loads(data) if data else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    try:
        match name:
            case "message_start":
                return MessageStart(
                    d.get("message_id", ""), d.get("session_id", ""), d.get("phase", ""), d.get("ruleset_name", "")
                )
            case "thinking":
                return Thinking(d.get("status", "start"), d.get("delta", ""), d.get("duration_ms"))
            case "text":
                return Text(d.get("delta", ""))
            case "tool_call":
                return ToolCall(d.get("tool_use_id", ""), d.get("name", ""), d.get("input") or {})
            case "dice_roll":
                return DiceRoll(
                    tool_use_id=d.get("tool_use_id", ""),
                    expression=d.get("expression", ""),
                    total=d.get("total"),
                    result=d.get("result", ""),
                    crit=d.get("crit", "none"),
                    comment=d.get("comment"),
                    dice=tuple(_term(t) for t in d.get("dice", [])),
                )
            case "status":
                return Status(str(d.get("stage", "")), str(d.get("message", "")), bool(d.get("done", False)))
            case "message_end":
                return MessageEnd(
                    d.get("message_id", ""),
                    d.get("stop_reason", ""),
                    d.get("usage") or {},
                    d.get("phase", ""),
                    d.get("ruleset_name", ""),
                    d.get("metrics") or {},
                    d["story"] if isinstance(d.get("story"), dict) else None,
                )
            case "phase_change":
                return PhaseChange(d.get("previous", ""), d.get("phase", ""))
            case "chapter":
                return ChapterChange(int(d.get("previous", 0)), int(d.get("chapter", 0)), str(d.get("title", "")))
            case "award":
                return Award(
                    int(d.get("xp_gained", 0)),
                    tuple(str(n) for n in d.get("to") or ()),
                    bool(d.get("everyone", False)),
                    tuple(
                        Standing(
                            str(c.get("name", "")), int(c.get("xp", 0)), int(c.get("level", 1)),
                            int(c.get("previous_level", c.get("level", 1))),
                            tuple((str(k), int(v)) for k, v in (c.get("classes") or {}).items()),
                        )
                        for c in d.get("characters") or ()
                        if isinstance(c, dict)
                    ),
                    float(d.get("average_level", 1.0)),
                    str(d.get("reason", "")),
                )  # fmt: skip
            case "error":
                return ErrorEvent(
                    d.get("code", "internal_error"), d.get("message", ""), bool(d.get("retryable", False))
                )
            case _:
                return Unknown(name, d)
    except (TypeError, ValueError):
        return None
