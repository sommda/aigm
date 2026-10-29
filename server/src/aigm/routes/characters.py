"""The party's character sheets (docs/STATUS.md 7), pulled by the client one tab at a time."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request

from aigm import characters
from aigm.deps import get_session
from aigm.errors import Conflict, NotFound
from aigm.session.state import Phase
from aigm.session.store import Session

router = APIRouter(prefix="/characters")
SessionDep = Annotated[Session, Depends(get_session)]


def _adventure(session: Session) -> None:
    if session.state.phase is not Phase.ADVENTURE:
        raise Conflict("There are no character sheets until the adventure has begun")


@router.get("")
def party(session: SessionDep) -> dict[str, Any]:
    _adventure(session)
    return {"session_id": session.id, "characters": characters.roster(session.state)}


@router.get("/{name}")
def sheet(
    request: Request, session: SessionDep, name: Annotated[str, Path(min_length=1, max_length=80)]
) -> dict[str, Any]:
    _adventure(session)
    page = characters.detail(session.state, name)
    if page is None:
        raise NotFound(f"No party member named {name!r}")
    portraits = request.app.state.portraits
    return {"session_id": session.id, **page, "portrait": portraits.view(session, page["name"]) if portraits else None}
