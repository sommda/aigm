"""Measurements of each turn: how long the model took and what the requests cost (docs/HISTORY.md, A).

The turn loop builds one record per turn (`TurnMetrics`). It goes out on the `message_end` event, into the log
and, when enabled, onto a JSON line in {save_dir}/metrics/{session}.jsonl, so a long game can be analyzed
afterwards (for example to see what the history costs and what a change to it saved)."""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aigm.history import Reduction, block_chars, message_chars
from aigm.world.briefing import CHARS_PER_TOKEN

log = logging.getLogger(__name__)


def _tokens(chars: int) -> int:
    return -(-chars // CHARS_PER_TOKEN)


def _json_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def history_breakdown(messages: list[dict[str, Any]]) -> dict[str, int]:
    """Estimated tokens of the history by kind of content: where the tokens go."""
    chars = dict.fromkeys(("player", "gm", "digests", "thinking", "tool_calls", "tool_results"), 0)
    for msg in messages:
        for block in msg.get("content", []):
            kind = block.get("type")
            if kind == "text":
                text = block.get("text", "")
                if text.startswith("<story_so_far>"):
                    chars["digests"] += len(text)
                else:
                    chars["player" if msg["role"] == "user" else "gm"] += len(text)
            elif kind in ("thinking", "redacted_thinking"):
                chars["thinking"] += block_chars(block)
            elif kind == "tool_use":
                chars["tool_calls"] += block_chars(block)
            elif kind == "tool_result":
                chars["tool_results"] += block_chars(block)
    return {k: _tokens(v) for k, v in chars.items()}


def request_sizes(request: Any, stored: list[dict[str, Any]]) -> dict[str, Any]:
    """Estimated token sizes of one request (a `RequestDescription`), and how much of the stored history
    was left out of it."""
    return {
        "system": _tokens(len(request.system)),
        "tools": _tokens(_json_chars(request.tools)),
        "history": _tokens(message_chars(request.history)),
        "history_stored": _tokens(message_chars(stored)),
        "briefing": _tokens(len(request.briefing)),
        "messages_sent": len(request.history),
        "messages_stored": len(stored),
        "history_by_kind": history_breakdown(request.history),
    }


@dataclass
class RequestMetrics:
    """One call to the model. Times are milliseconds from the moment the request was started."""

    index: int
    input_tokens: int = 0  # everything the model read, cached or not
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    first_text_ms: int | None = None  # until the first visible text: thinking does not count as text
    thinking_ms: int = 0  # time spent thinking before the response finished
    narration_chars: int = 0  # characters of roll narration shown while the model was still writing the call
    total_ms: int = 0
    stop_reason: str = ""
    sent: dict[str, Any] = field(default_factory=dict)

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cache_read_tokens - self.cache_write_tokens)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "input_tokens": self.input_tokens,
            "uncached_input_tokens": self.uncached_input_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "output_tokens": self.output_tokens,
            "first_text_ms": self.first_text_ms,
            "thinking_ms": self.thinking_ms,
            "narration_chars": self.narration_chars,
            "total_ms": self.total_ms,
            "stop_reason": self.stop_reason,
            "sent": self.sent,
        }


@dataclass
class TurnMetrics:
    """One player turn: the model calls it took and the times the player experienced."""

    turn: int
    phase: str
    model: str = ""
    requests: list[RequestMetrics] = field(default_factory=list)
    first_text_ms: int | None = None  # from the start of the turn to the first visible text
    total_ms: int = 0  # the whole turn, including the pauses before dice rolls
    pause_ms: int = 0  # of which the deliberate pauses before dice rolls
    reduction: Reduction | None = None
    chapter: int | None = None  # story games: the chapter the turn began in

    def to_dict(self) -> dict[str, Any]:
        def total(key: str) -> int:
            return sum(getattr(r, key) for r in self.requests)

        out: dict[str, Any] = {
            "turn": self.turn,
            "phase": self.phase,
            "model": self.model,
            "first_text_ms": self.first_text_ms,
            "total_ms": self.total_ms,
            "pause_ms": self.pause_ms,
            "model_calls": len(self.requests),
            "input_tokens": total("input_tokens"),
            "uncached_input_tokens": sum(r.uncached_input_tokens for r in self.requests),
            "cache_read_tokens": total("cache_read_tokens"),
            "cache_write_tokens": total("cache_write_tokens"),
            "output_tokens": total("output_tokens"),
            "requests": [r.to_dict() for r in self.requests],
        }
        if self.chapter is not None:
            out["chapter"] = self.chapter
        if self.reduction is not None:
            red = self.reduction
            out["history"] = {
                "turns": red.turns,
                "digested_turns": red.digested_turns,
                "trimmed_turns": red.trimmed_turns,
            }
        return out


class MetricsLog:
    """Appends turn records to one file per session. With no directory it does nothing."""

    def __init__(self, directory: Path | None) -> None:
        self.dir = directory

    def record(self, session_id: str, metrics: TurnMetrics) -> None:
        data = metrics.to_dict()
        log.info(
            "turn %s: first text %s ms, total %s ms, in=%s (cache read %s, write %s) out=%s, %s calls",
            data["turn"], data["first_text_ms"], data["total_ms"], data["input_tokens"], data["cache_read_tokens"],
            data["cache_write_tokens"], data["output_tokens"], data["model_calls"],
        )  # fmt: skip
        if self.dir is None:
            return
        line = json.dumps({"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "session": session_id, **data})
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.dir / f"{session_id}.jsonl", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            log.warning("could not write metrics for %s", session_id, exc_info=True)
