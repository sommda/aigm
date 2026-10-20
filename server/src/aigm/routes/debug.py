"""Debug-only endpoints. This router is registered only when the server runs with --debug (docs/CONTEXT.md),
so without it these paths do not exist."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from aigm.context_view import build_context
from aigm.deps import get_session
from aigm.session.store import Session
from aigm.story import needs_plan, summary_so_far

log = logging.getLogger(__name__)
router = APIRouter(prefix="/debug")


@router.get("/context")
def context(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    draft: Annotated[str, Query(max_length=20000, description="The text typed so far")] = "",
) -> dict[str, Any]:
    log.info("context requested for session %s", session.id)  # the content is never logged
    return build_context(
        game=request.app.state.game, session=session, model=request.app.state.model_name, draft=draft
    )


class ThinkingSetting(BaseModel):
    enabled: bool


@router.get("/thinking")
def get_thinking(request: Request) -> dict[str, bool]:
    return {"thinking": getattr(request.app.state.llm, "thinking", True)}


@router.put("/thinking")
def set_thinking(request: Request, body: ThinkingSetting) -> dict[str, bool]:
    """Turns the GM's model thinking on or off for every session until changed (or the server restarts), so one
    action can be tried both ways from the same save."""
    request.app.state.llm.thinking = body.enabled
    log.info("model thinking %s", "on" if body.enabled else "off")
    return {"thinking": body.enabled}


@router.get("/story")
def story(session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    """The whole story plan, spoilers and all, and the same as readable text."""
    state = session.state
    plan = state.story
    return {
        "session_id": session.id,
        "structure": state.structure,
        "story": plan.to_dict() if plan else None,
        "text": summary_so_far(plan) if plan else "",
        "waiting_for_plan": needs_plan(plan) if plan else None,
    }
