from typing import Any

import logging

from aigm import story as story_rules
from aigm.compendium import Compendium
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
        self.pending_plans: list[Any] = []  # finished chapter plans (aigm.world.plot.PlotResult), same wait
        self.pending_reports: list[dict[str, Any]] = []  # quests the curator saw finished, same wait
        self.plan_retry_turn = 0  # a failed chapter plan is not tried again before this turn
        # Compendium marks sent while a turn ran: entity ids, or None for everything (docs/COMPENDIUM.md 4.3).
        self.pending_seen: list[list[str] | None] = []

    def reset_world_work(self) -> None:
        """The game was replaced (new game, restore): forget in-flight and finished curator work."""
        self.generation += 1
        self.pending.clear()
        self.pending_plans.clear()
        self.pending_reports.clear()
        self.pending_seen.clear()
        self.plan_retry_turn = 0

    def drain_pending(self, *, in_turn: bool = False) -> None:
        """Apply finished curator passes to the live world. Done only between turns (a turn works on
        a copy of the state and would overwrite changes made while it runs), or at the very start
        of a turn, before that copy is taken."""
        if (self.busy and not in_turn) or not (
            self.pending or self.pending_plans or self.pending_reports or self.pending_seen
        ):
            return
        self.state.compendium = self.reading_state()
        self.pending_seen.clear()
        for ops in self.pending:
            applied = apply_ops(self.state.world, ops)
            for why in applied.skipped:
                log.info("curator op skipped: %s", why)
        self.pending.clear()
        for plan in self.pending_plans:
            self._apply_plan(plan)
        self.pending_plans.clear()
        for report in self.pending_reports:
            self._apply_report(report)
        self.pending_reports.clear()

    def mark_seen(self, entity_ids: list[str] | None) -> None:
        """The player has read these compendium entries (None: all of it). During a turn the live state is about to be
        replaced by the turn's copy, so the mark waits until the turn is over."""
        if self.busy:
            self.pending_seen.append(entity_ids)
        else:
            self.state.compendium = self.reading_state([entity_ids])

    def reading_state(self, extra: list[list[str] | None] | None = None) -> Compendium:
        """The compendium's reading state with the waiting marks (and `extra`) applied, as a copy."""
        comp = self.state.compendium.copy()
        for ids in [*self.pending_seen, *(extra or [])]:
            if ids is None:
                comp.mark_all(self.state.world)
            else:
                comp.mark_seen(self.state.world, ids)
        return comp

    def _apply_plan(self, plan: Any) -> None:
        """Add a later chapter's quests, if the story is still waiting for exactly that chapter."""
        story = self.state.story
        if story is None or story_rules.needs_plan(story) != plan.chapter:
            log.info("chapter plan dropped: the story has moved on")
            return
        for why in apply_ops(self.state.world, plan.ops).skipped:
            log.info("plot op skipped: %s", why)
        plan.rebind(self.state.world)
        story.milestones += plan.milestones
        story_rules.settle_ready(story)
        story.last_progress_turn = self.state.turn  # a fresh chapter is not an idle one

    def _apply_report(self, report: dict[str, Any]) -> None:
        """Quest progress the curator read from the narration. Each item counts on its own: the GM may have reported
        some of it already, and those are simply not active any more."""
        from aigm.tools.story import check_story_report

        items = [{"quests": [q]} for q in report.get("quests", [])]
        if report.get("goal_revealed"):
            items.append({"goal_revealed": True})
        for item in items:
            story, problems, _ = check_story_report(item, self.state)
            if story is not None:
                self.state.story = story
            else:
                log.info("story report skipped: %s", "; ".join(problems))

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
