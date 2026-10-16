from typing import Any

from aigm.session.state import GameState


class Session:
    """One live conversation. `busy` is set for the whole duration of a streamed turn
    (single event loop, so check-and-set is atomic)."""

    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.messages: list[dict[str, Any]] = []
        self.state = GameState()  # a new game starts in Session 0
        self.busy = False

    def try_begin(self) -> bool:
        if self.busy:
            return False
        self.busy = True
        return True

    def end(self) -> None:
        self.busy = False


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            session = self._sessions[session_id] = Session(session_id)
        return session
