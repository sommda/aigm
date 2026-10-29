"""Portrait images (docs/PORTRAITS.md 9): the bytes of a picture the session may show its player."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import FileResponse

from aigm.deps import get_session
from aigm.errors import NotFound
from aigm.portraits import CONTENT_TYPES
from aigm.session.store import Session

router = APIRouter(prefix="/portraits")
SessionDep = Annotated[Session, Depends(get_session)]
# The file name is a hash of what made the picture, so the same name is always the same picture.
CACHE = "private, max-age=31536000, immutable"


@router.get("/{file}")
def portrait(request: Request, session: SessionDep, file: Annotated[str, Path(max_length=64)]) -> FileResponse:
    service = request.app.state.portraits
    path = service.shown(session, file) if service is not None else None
    if path is None:  # the same answer for a picture that does not exist and one this game does not show
        raise NotFound("No such portrait")
    return FileResponse(path, media_type=CONTENT_TYPES[path.suffix[1:]], headers={"Cache-Control": CACHE})
