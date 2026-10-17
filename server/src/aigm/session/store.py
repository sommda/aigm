from typing import Any

import logging

from aigm.session.state import GameState
from aigm.world.ops import Op, apply_ops

log = logging.getLogger(__name__)


class Session:
    """One live conversation. `busy` is set for the whole duration of a streamed turn
    (single event loop, so check-and-set is atomic)."""

    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.messages: list[dict[str, Any]] = []
        self.state = GameState()  # a new game starts in Session 0
        self.busy = False
        # Background world curation (see aigm/world/service.py)
        self.generation = 0  # bumped when the game is replaced, so a stale pass is discarded
        self.curating = False
        self.pending: list[list[Op]] = []  # finished passes waiting for the session to be idle

    def reset_world_work(self) -> None:
        """The game was replaced (new game, restore): forget in-flight and finished curator work."""
        self.generation += 1
        self.pending.clear()

    def drain_pending(self, *, in_turn: bool = False) -> None:
        """Apply finished curator passes to the live world. Done only between turns (a turn works on
        a copy of the state and would overwrite changes made while it runs), or at the very start
        of a turn, before that copy is taken."""
        if (self.busy and not in_turn) or not self.pending:
            return
        for ops in self.pending:
            applied = apply_ops(self.state.world, ops)
            for why in applied.skipped:
                log.info("curator op skipped: %s", why)
        self.pending.clear()

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
