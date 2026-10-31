from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTasks

from aigm import rulesets
from aigm.compendium import unseen_totals
from aigm.story import public_summary
from aigm.deps import get_session
from aigm.errors import Conflict
from aigm.llm.loop import run_turn
from aigm.models import ChatRequest
from aigm.session.state import GameState
from aigm.session.store import Session
from aigm.sse import SSE_HEADERS, encode

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/chat")
async def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    app = request.app
    session = app.state.sessions.get(body.session_id)
    if not session.try_begin():
        raise Conflict("A turn is already in progress for this session")

    released = False

    def release() -> None:  # idempotent: runs from the generator and from the response
        nonlocal released
        if not released:
            released = True
            session.end()

    settings = app.state.settings

    async def event_stream():
        try:
            async for event in run_turn(
                session=session,
                user_text=body.message,
                llm=app.state.llm,
                game=app.state.game,
                max_iters=settings.max_tool_iters,
                stream_thinking=settings.stream_thinking,
                curator=app.state.curator,
                roll_pause=settings.roll_pause,
                metrics=app.state.metrics,
                model=app.state.model_name,
            ):
                yield encode(event)
        finally:
            release()

    async def curate() -> None:  # after the response: the player is never kept waiting for the world
        service = app.state.curator
        if service is not None:
            await service.run_if_due(session)
            await service.run_looks_if_due(session)
            await service.run_place_looks_if_due(session)
            await service.run_item_looks_if_due(session)
            await service.run_revisions_if_due(session)
        portraits = app.state.portraits
        if portraits is not None:
            await portraits.run_if_due(session)
        await app.state.dumper.update(session)  # the turn, a tool or the pass may have changed the world

    background = BackgroundTasks()
    background.add_task(release)
    background.add_task(curate)
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
        background=background,
    )


@router.get("/chat/history")
async def chat_history(session: SessionDep) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "phase": session.state.phase.value,
        "ruleset": session.state.ruleset,
        "ruleset_name": rulesets.get(session.state.ruleset).short,
        "campaign": session.state.campaign,
        "story": public_summary(session.state.story),
        "compendium": unseen_totals(session.state.world, session.reading_state()),
        "messages": session.messages,
    }


@router.post("/chat/new")
async def new_game(session: SessionDep, request: Request) -> dict[str, Any]:
    if session.busy:
        raise Conflict("A turn is in progress for this session")
    discarded = len(session.messages)
    session.messages = []
    session.state = GameState()  # back to Session 0
    session.reset_world_work()
    await request.app.state.dumper.remove(session.id)
    return {
        "session_id": session.id,
        "phase": session.state.phase.value,
        "ruleset": session.state.ruleset,
        "ruleset_name": rulesets.get(session.state.ruleset).short,
        "message_count": 0,
        "discarded_message_count": discarded,
    }
