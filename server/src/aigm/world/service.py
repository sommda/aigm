"""Runs curator passes in the background for a session (docs/WORLD.md 4.1, 4.5)."""

import logging

from aigm.session.state import Phase
from aigm.session.store import Session
from aigm.world.curator import Curator
from collections.abc import Callable
from typing import Any

from aigm.world.ops import Op
from aigm.world.passes import (
    DEFAULT_EVERY_PAGES,
    DEFAULT_PAGE_CHARS,
    PassConfig,
    narration_pages,
    run_bootstrap,
    run_pass,
)
from aigm.world.model import World
from aigm import story as story_rules
from aigm.world.plot import PlotResult, run_chapter_plot, run_plot

log = logging.getLogger(__name__)
PLAN_RETRY_TURNS = 3  # a chapter plan that failed is tried again after this many more turns
REQUESTED_MIN_PAGES = 1.0  # a lookup miss asks for a pass, but only once there is something to digest


class CuratorService:
    def __init__(
        self,
        curator: Curator,
        *,
        every_pages: float = DEFAULT_EVERY_PAGES,
        page_chars: int = DEFAULT_PAGE_CHARS,
        config: PassConfig | None = None,
    ) -> None:
        self.curator = curator
        self.every_pages = every_pages
        self.page_chars = page_chars
        self.config = config or PassConfig()

    def pages(self, session: Session) -> float:
        """Pages of narration the curator has not digested yet."""
        return narration_pages(session.messages, session.state.world.processed_through, self.page_chars)

    def due(self, session: Session) -> bool:
        if session.state.phase is not Phase.ADVENTURE or session.curating or session.busy:
            return False
        pages = self.pages(session)
        if pages >= self.every_pages:
            return True
        return session.state.pass_requested and pages >= min(REQUESTED_MIN_PAGES, self.every_pages)

    async def run_if_due(self, session: Session) -> bool:
        """Run a pass if enough narration has built up. Returns whether results were produced.

        Works on a snapshot, so the player's next turn is never blocked. The result is applied when
        the session is idle (`Session.drain_pending`); if the game was replaced meanwhile it is dropped.
        A failed pass changes nothing and leaves `processed_through` alone, so it is retried later."""
        if self.plan_due(session):
            return await self._plan_chapter(session)
        if not self.due(session):
            return False
        generation = session.generation
        session.curating = True
        session.state.pass_requested = False
        try:
            result = await run_pass(
                session.state.world,
                list(session.messages),
                self.curator,
                setting=(session.state.campaign or {}).get("setting", ""),
                party_names=[m.get("name", "") for m in (session.state.campaign or {}).get("party", []) if isinstance(m, dict)],
                config=self.config,
                story=session.state.story,
            )
        except Exception:
            log.exception("world curator pass failed; will retry")
            return False
        finally:
            session.curating = False
        if session.generation != generation:
            return False
        for note in result.notes:
            log.info("curator: %s", note)
        session.pending.append(result.ops)
        session.pending_reports += result.story_reports
        session.drain_pending()
        return True

    def plan_due(self, session: Session) -> bool:
        """Has the story reached a chapter whose quests are not written yet?"""
        story = session.state.story
        return (
            session.state.phase is Phase.ADVENTURE
            and story is not None
            and story_rules.needs_plan(story) is not None
            and not session.curating
            and not session.busy
            and session.state.turn >= session.plan_retry_turn
        )

    async def _plan_chapter(self, session: Session) -> bool:
        """Write the quests of the chapter the story has reached, in the background (docs/STORY.md 5)."""
        story = session.state.story
        assert story is not None
        chapter = story_rules.needs_plan(story)
        assert chapter is not None
        generation = session.generation
        session.curating = True
        try:
            result = await run_chapter_plot(
                session.state.world, session.state.campaign or {}, story.copy(), chapter, self.curator,
                turn=session.state.turn,
            )  # fmt: skip
        except Exception:
            log.exception("planning chapter %s failed; will retry", chapter)
            session.plan_retry_turn = session.state.turn + PLAN_RETRY_TURNS
            return False
        finally:
            session.curating = False
        if session.generation != generation:
            return False
        for note in result.notes:
            log.info("plot: %s", note)
        session.pending_plans.append(result)
        session.drain_pending()
        return True

    async def seed(
        self, campaign: dict[str, Any], history: list[dict[str, Any]], progress: Callable[[str], None] | None = None
    ) -> list[Op]:
        """Ops that build a new game's world from its campaign record (the player waits for this).
        `history` is the conversation the first scene will follow; it counts as digested."""
        result = await run_bootstrap(campaign, history, self.curator, progress=progress)
        for note in result.notes:
            log.info("bootstrap: %s", note)
        return result.ops

    async def plan(
        self, campaign: dict[str, Any], world: World, length: str, progress: Callable[[str], None] | None = None
    ) -> PlotResult:
        """The story plan of a new structured game, written against its freshly built world (docs/STORY.md 5)."""
        result = await run_plot(world, campaign, length, self.curator, progress=progress)
        for note in result.notes:
            log.info("plot: %s", note)
        return result
