from typing import Annotated

from fastapi import Query, Request

from aigm.models import ID_PATTERN
from aigm.session.persistence import HistoryRepository
from aigm.session.store import Session, SessionStore

SessionId = Annotated[str, Query(pattern=ID_PATTERN, description="Session id")]


def get_session(request: Request, session_id: SessionId = "default") -> Session:
    store: SessionStore = request.app.state.sessions
    return store.get(session_id)


def get_repo(request: Request) -> HistoryRepository:
    return request.app.state.repo
