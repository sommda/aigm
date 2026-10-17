"""Debug-only endpoints. This router is registered only when the server runs with --debug (docs/CONTEXT.md),
so without it these paths do not exist."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from aigm.context_view import build_context
from aigm.deps import get_session
from aigm.session.store import Session

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
