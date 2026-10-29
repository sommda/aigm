"""Runs curator passes in the background for a session (docs/WORLD.md 4.1, 4.5)."""

import logging

from aigm.session.state import Phase
from aigm.session.store import Session
from aigm.world.curator import Curator
from collections.abc import Callable
from typing import Any

from aigm.sheets import Sheet
from aigm.world.ops import Op
from aigm.world.passes import (
    DEFAULT_EVERY_PAGES,
    DEFAULT_PAGE_CHARS,
    PassConfig,
    narration_pages,
    run_bootstrap,
    run_pass,
    run_sheets,
)
from aigm import rulesets
from aigm.looks import Look
from aigm.world.describe import Given, LooksResult, needing, revision_candidates, run_looks, run_revisions
from aigm.world.describe_places import needing_places, run_place_looks
from aigm.world.model import World
from aigm.world.text import normalize_name
from aigm import story as story_rules
from aigm.world.plot import PlotResult, run_chapter_plot, run_plot

log = logging.getLogger(__name__)
PLAN_RETRY_TURNS = 3  # a chapter plan that failed is tried again after this many more turns
SEED_MESSAGES = 3  # what the world was built from when the adventure began (the note, the record and the cue)
LOOK_RETRY_TURNS = 2  # a sweep that wrote no Look is not tried again until this many more turns have passed
BOOTSTRAP_LOOKS = 24  # characters described while a new game's world is prepared (the player is waiting anyway)
FIRST_PASS_PAGES = 1.0  # the opening scene introduces the cast, so the first pass does not wait for the usual pages
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
        first = session.state.world.processed_through == SEED_MESSAGES
        if pages >= (min(FIRST_PASS_PAGES, self.every_pages) if first else self.every_pages):
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

    async def sheets(
        self,
        campaign: dict[str, Any],
        ruleset: str,
        levels: dict[str, int],
        *,
        only: list[str] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, Sheet]:
        """The party's sheets written out as sections (docs/STATUS.md 3.2). A sheet that fails is left out."""
        sheets, notes = await run_sheets(campaign, ruleset, levels, self.curator, only=only, progress=progress)
        for note in notes:
            log.info("sheets: %s", note)
        return sheets

    async def looks(
        self,
        campaign: dict[str, Any],
        ruleset: str,
        world: World,
        party_looks: dict[str, Look],
        *,
        recent_text: str = "",
        given: dict[str, Given] | None = None,
        limit: int | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> LooksResult:
        """Looks for the characters that have none (docs/LOOKS.md 5). Never raises for a model failure."""
        kwargs: dict[str, Any] = {"recent_text": recent_text, "given": given, "progress": progress}
        if limit is not None:
            kwargs["limit"] = limit
        result = await run_looks(world, campaign, ruleset, party_looks, self.curator, **kwargs)
        for note in result.notes:
            log.info("looks: %s", note)
        return result

    def looks_due(self, session: Session) -> bool:
        """Is any character without a Look, and is this a quiet moment to write them?"""
        state = session.state
        return (
            state.phase is Phase.ADVENTURE
            and not session.curating
            and not session.busy
            and state.turn >= session.looks_retry_turn
            and bool(needing(state.world, state.party_names, state.looks))
        )

    async def run_looks_if_due(self, session: Session) -> bool:
        """Write the missing Looks in the background, after the turn. The results wait for the session to be idle,
        like a curator pass. A sweep that wrote nothing backs off for a few turns, so a failing model costs little."""
        if not self.looks_due(session):
            return False
        generation = session.generation
        state = session.state
        session.curating = True
        try:
            result = await self.looks(
                state.campaign or {}, rulesets.get(state.ruleset).name, state.world.copy(), dict(state.looks),
                recent_text=_last_narration(session.messages),
                given={
                    name: Given([note], "narration", "the GM, who was about to narrate it")
                    for name, note in state.look_hints.items()
                },
            )  # fmt: skip
        except Exception:
            log.exception("writing looks failed; will retry")
            session.looks_retry_turn = state.turn + LOOK_RETRY_TURNS
            return False
        finally:
            session.curating = False
        if session.generation != generation:
            return False
        if not result.ops and not result.party:
            session.looks_retry_turn = state.turn + LOOK_RETRY_TURNS
            return False
        for op in result.ops:
            state.look_hints.pop(normalize_name(op.entity), None)  # used
        session.pending.append(result.ops)
        session.pending_looks.append(result.party)
        session.drain_pending()
        return True

    def place_looks_due(self, session: Session) -> bool:
        """Is any place the player knows well enough to picture without a Look, and is this a quiet moment?"""
        state = session.state
        return (
            state.phase is Phase.ADVENTURE
            and not session.curating
            and not session.busy
            and state.turn >= session.place_looks_retry_turn
            and getattr(self.curator, "place_look", None) is not None
            and bool(needing_places(state.world))
        )

    async def run_place_looks_if_due(self, session: Session) -> bool:
        """Describe the places that need it, in the background, after the turn (docs/PLACES.md 6). The results wait for
        the session to be idle, like a curator pass; a sweep that wrote nothing backs off for a few turns."""
        if not self.place_looks_due(session):
            return False
        generation = session.generation
        state = session.state
        session.curating = True
        try:
            result = await run_place_looks(
                state.world.copy(), state.campaign or {}, rulesets.get(state.ruleset).name, self.curator,
                recent_text=_last_narration(session.messages),
            )  # fmt: skip
        except Exception:
            log.exception("describing places failed; will retry")
            session.place_looks_retry_turn = state.turn + LOOK_RETRY_TURNS
            return False
        finally:
            session.curating = False
        for note in result.notes:
            log.info("place looks: %s", note)
        if session.generation != generation:
            return False
        if not result.ops:
            session.place_looks_retry_turn = state.turn + LOOK_RETRY_TURNS
            return False
        session.pending.append(result.ops)
        session.drain_pending()
        return True

    def revisions_due(self, session: Session) -> bool:
        """Has the last turn's narration described someone who already has a Look?"""
        state = session.state
        if (
            state.phase is not Phase.ADVENTURE
            or session.curating
            or session.busy
            or state.turn <= session.revision_checked_turn
            or getattr(self.curator, "revise_looks", None) is None
        ):
            return False
        narration = _last_narration(session.messages)
        return bool(narration) and bool(
            revision_candidates(state.world, state.party_names, state.looks, narration)
        )

    async def run_revisions_if_due(self, session: Session) -> bool:
        """Check the narration of the turn just played against the Looks of the people it describes (docs/LOOKS.md 7).
        Once per turn, in the background; a failure is not retried, since the next turn brings new narration."""
        if not self.revisions_due(session):
            return False
        generation = session.generation
        state = session.state
        session.revision_checked_turn = state.turn
        session.curating = True
        try:
            result = await run_revisions(
                state.world.copy(), state.campaign or {}, dict(state.looks), self.curator,
                _last_narration(session.messages), turn=state.turn,
            )  # fmt: skip
        except Exception:
            log.exception("revising looks failed")
            return False
        finally:
            session.curating = False
        for note in result.notes:
            log.info("looks: %s", note)
        if session.generation != generation or not (result.ops or result.party):
            return False
        session.pending.append(result.ops)
        session.pending_revised.append(result.party)
        session.drain_pending()
        return True

    async def plan(
        self, campaign: dict[str, Any], world: World, length: str, progress: Callable[[str], None] | None = None
    ) -> PlotResult:
        """The story plan of a new structured game, written against its freshly built world (docs/STORY.md 5)."""
        result = await run_plot(world, campaign, length, self.curator, progress=progress)
        for note in result.notes:
            log.info("plot: %s", note)
        return result


def _last_narration(messages: list[dict[str, Any]]) -> str:
    """The GM's text since the player's last message: what the last turn narrated."""
    texts: list[str] = []
    for msg in reversed(messages):
        if msg["role"] == "user" and any(b.get("type") == "text" for b in msg["content"]):
            break
        if msg["role"] == "assistant":
            texts += [b.get("text", "") for b in msg["content"] if b.get("type") == "text"]
    return "\n".join(reversed(texts))
