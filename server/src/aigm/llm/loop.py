"""The streaming tool-use loop for one chat turn."""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
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
from aigm.game import Game
from aigm.models import (
    DiceRoll,
    ErrorEvent,
    MessageEnd,
    MessageStart,
    PhaseChange,
    SSEEvent,
    Status,
    TextDelta,
    Thinking,
    ToolCall,
)
from aigm.session.state import GameState
from aigm.session.store import Session
from aigm.world.ops import apply_ops
from aigm.world.service import CuratorService

log = logging.getLogger(__name__)


def turn_number(messages: list[dict[str, Any]]) -> int:
    """How many player messages the history holds: the number of the turn in progress."""
    return sum(1 for m in messages if m["role"] == "user" and any(b.get("type") == "text" for b in m["content"]))


async def _seed_world(state: GameState, history: list[dict[str, Any]], curator: CuratorService) -> AsyncIterator[SSEEvent]:
    """Build the new game's world while the player waits, reporting progress as `status` events.
    The result goes into the turn's working state, so a failure anywhere rolls the whole turn back."""
    yield Status(stage="world", message="Preparing the world...")
    progress: asyncio.Queue[str] = asyncio.Queue()
    task = asyncio.ensure_future(curator.seed(state.campaign or {}, history, progress=progress.put_nowait))
    try:
        while not task.done():
            getter = asyncio.ensure_future(progress.get())
            await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter.done():
                yield Status(stage="world", message=getter.result())
            else:
                getter.cancel()
        while not progress.empty():
            yield Status(stage="world", message=progress.get_nowait())
        try:
            ops = task.result()
        except Exception as exc:
            log.exception("could not build the world")
            raise LLMError(f"The world could not be prepared ({type(exc).__name__}); try again", retryable=True) from None
    finally:
        task.cancel()  # a no-op once finished; stops the work if the client went away
    for why in apply_ops(state.world, ops).skipped:
        log.info("bootstrap op skipped: %s", why)
    yield Status(stage="world", message="The world is ready.", done=True)


async def run_turn(
    *,
    session: Session,
    user_text: str,
    llm: LLMClient,
    game: Game,
    max_iters: int,
    stream_thinking: bool = True,
    curator: CuratorService | None = None,
    roll_pause: float = 0.0,
) -> AsyncIterator[SSEEvent]:
    """Run one user turn, yielding SSE events.

    Messages and game state are staged in local copies and committed to the session only when
    the turn completes. A failed or cancelled turn therefore leaves history and state untouched
    (and never leaves a tool_use without its tool_result, which the API would reject). A tool
    may change the state mid-turn, for example `begin_adventure` switches the phase; the next
    request in the same turn then uses the new phase's system prompt and tools."""
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    session.drain_pending(in_turn=True)  # curator results land before the turn takes its working copy
    staged = [*session.messages, {"role": "user", "content": [{"type": "text", "text": user_text}]}]
    state = session.state.copy()
    state.turn = turn_number(staged)
    shown_corrections = list(state.world.corrections)  # the GM sees these in this turn's notes
    usage = {"input_tokens": 0, "output_tokens": 0}
    yield MessageStart(message_id=message_id, session_id=session.id, phase=state.phase.value)
    try:
        for _ in range(max_iters):
            completed: Completed | None = None
            think_started: float | None = None
            request = game.describe(state, staged, user_text)
            async for ev in llm.stream(system=request.system, messages=request.messages, tools=request.tools):
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
                state.world.clear_corrections(shown_corrections)
                previous, session.messages[:], session.state = session.state.phase, staged, state
                if state.phase != previous:  # announced only once committed, so it is never rolled back
                    yield PhaseChange(previous=previous.value, phase=state.phase.value)
                yield MessageEnd(
                    message_id=message_id, stop_reason=completed.stop_reason, usage=usage, phase=state.phase.value
                )
                return

            phase_before = state.phase
            results = []
            for block in tool_uses:
                tool_input = block.get("input") or {}
                yield ToolCall(tool_use_id=block["id"], name=block["name"], input=tool_input)
                outcome = game.dispatch(state, block["name"], block["id"], tool_input)
                if outcome.event is not None:
                    if roll_pause > 0 and isinstance(outcome.event, DiceRoll):
                        await asyncio.sleep(roll_pause)  # let the narration sink in before the dice land
                    yield outcome.event
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": outcome.content,
                        "is_error": outcome.is_error,
                    }
                )
            if state.phase != phase_before:
                # Session 0 just ended: its history is replaced by the campaign record
                staged = game.history_after_begin(state)
                state.turn = turn_number(staged)
                if curator is not None:
                    seeding = _seed_world(state, staged, curator)
                    try:
                        async for status in seeding:
                            yield status
                    finally:
                        await seeding.aclose()  # stops the work now if the client went away
            else:
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
