"""The status page (docs/STATUS.md): where the party is and how everyone is doing, pulled by the client."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from aigm import status as stat
from aigm.deps import get_session
from aigm.errors import Conflict
from aigm.session.state import Phase
from aigm.session.store import Session

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/status")
def status(session: SessionDep) -> dict[str, Any]:
    if session.state.phase is not Phase.ADVENTURE:
        raise Conflict("There is no status until the adventure has begun")
    return {"session_id": session.id, "phase": session.state.phase.value, **stat.build(session.state)}
