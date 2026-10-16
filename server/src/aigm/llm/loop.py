"""The streaming tool-use loop for one chat turn."""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from aigm.llm.base import (
    Completed,
    LLMClient,
    LLMError,
    TextChunk,
    ThinkingChunk,
    ThinkingStarted,
    ThinkingStopped,
)
from aigm.models import (
    ErrorEvent,
    MessageEnd,
    MessageStart,
    SSEEvent,
    TextDelta,
    Thinking,
    ToolCall,
)
from aigm.session.store import Session
from aigm.tools.base import ToolOutcome

log = logging.getLogger(__name__)

Dispatch = Callable[[str, str, dict[str, Any]], ToolOutcome]


async def run_turn(
    *,
    session: Session,
    user_text: str,
    llm: LLMClient,
    system: str,
    tools: list[dict[str, Any]],
    dispatch: Dispatch,
    max_iters: int,
    stream_thinking: bool = True,
) -> AsyncIterator[SSEEvent]:
    """Run one user turn, yielding SSE events.

    Messages are staged in a local list and committed to the session only when the turn
    completes. A failed or cancelled turn therefore leaves history untouched (and never
    leaves a tool_use without its tool_result, which the API would reject)."""
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    staged = [*session.messages, {"role": "user", "content": [{"type": "text", "text": user_text}]}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    yield MessageStart(message_id=message_id, session_id=session.id)
    try:
        for _ in range(max_iters):
            completed: Completed | None = None
            think_started: float | None = None
            async for ev in llm.stream(system=system, messages=staged, tools=tools):
                if isinstance(ev, ThinkingStarted):
                    think_started = time.monotonic()
                    yield Thinking(status="start")
                elif isinstance(ev, ThinkingChunk):
                    if stream_thinking:
                        yield Thinking(status="delta", delta=ev.text)
                elif isinstance(ev, ThinkingStopped):
                    ms = int((time.monotonic() - (think_started or time.monotonic())) * 1000)
                    think_started = None
                    yield Thinking(status="end", duration_ms=ms)
                elif isinstance(ev, TextChunk):
                    yield TextDelta(delta=ev.text)
                elif isinstance(ev, Completed):
                    completed = ev
            if think_started is not None:  # model stream ended mid-thinking: close the phase
                yield Thinking(status="end", duration_ms=int((time.monotonic() - think_started) * 1000))
            if completed is None:
                raise LLMError("The model stream ended without a final message", retryable=True)
            staged.append({"role": "assistant", "content": completed.content})
            for key in usage:
                usage[key] += completed.usage.get(key, 0)

            tool_uses = [b for b in completed.content if b.get("type") == "tool_use"]
            if not completed.content:
                raise LLMError("The model returned an empty response", retryable=True)
            if tool_uses and completed.stop_reason != "tool_use":
                # e.g. max_tokens hit mid tool call: the tool input is incomplete and cannot be run
                raise LLMError(
                    f"The model's response was cut off mid tool call ({completed.stop_reason})", retryable=True
                )
            if completed.stop_reason != "tool_use" or not tool_uses:
                session.messages[:] = staged
                yield MessageEnd(message_id=message_id, stop_reason=completed.stop_reason, usage=usage)
                return

            results = []
            for block in tool_uses:
                tool_input = block.get("input") or {}
                yield ToolCall(tool_use_id=block["id"], name=block["name"], input=tool_input)
                outcome = dispatch(block["name"], block["id"], tool_input)
                if outcome.event is not None:
                    yield outcome.event
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": outcome.content,
                        "is_error": outcome.is_error,
                    }
                )
            staged.append({"role": "user", "content": results})
        yield ErrorEvent(
            code="tool_loop_limit",
            message=f"The model used tools more than {max_iters} times in one turn",
            retryable=False,
        )
    except LLMError as exc:
        yield ErrorEvent(code="upstream_error", message=str(exc), retryable=exc.retryable)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("unexpected error in chat turn")
        yield ErrorEvent(code="internal_error", message="Unexpected server error", retryable=False)
