"""The status page (docs/STATUS.md): where the party is and how everyone is doing, pulled by the client."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from aigm import status as stat
from aigm.compendium import _look
from aigm.deps import get_session
from aigm.errors import Conflict
from aigm.session.state import Phase
from aigm.session.store import Session

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/status")
def status(request: Request, session: SessionDep) -> dict[str, Any]:
    if session.state.phase is not Phase.ADVENTURE:
        raise Conflict("There is no status until the adventure has begun")
    page = stat.build(session.state)
    location = page["location"]
    if location:  # how the party's place looks, and its picture (docs/PLACES.md 9)
        ent = session.state.world.entities[location["id"]]
        portraits = request.app.state.portraits
        location["look"] = _look(ent)
        location["portrait"] = portraits.view_entity(session, ent.id) if portraits else None
    return {"session_id": session.id, "phase": session.state.phase.value, **page}
