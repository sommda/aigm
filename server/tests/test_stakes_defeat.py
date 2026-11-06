"""Stakes, step 6 (docs/STAKES.md 7.5): the `defeat` tool, the wipe count, capture protection, the escape quest."""

import pytest

from aigm import story as st
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.story import Deadline, Doom
from aigm.tools import dispatch
from aigm.world import World, WorldTime
from aigm.world.curator import CuratorError, EntityProposal
from aigm.world.plot import run_escape_plot
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService
from tests.test_plot import CAMPAIGN, world
from tests.test_story_gm import state_with_story
from tests.test_stakes_death import party


def defeat(state, how="left", hours=24, **kw):
    base = {"how": how, "aftermath": "They wake in a wagon.", "elapsed_hours": hours}
    if state.story is not None and state.story.chapter < 3:
        base |= {"cost": "The healing draughts are gone.", "cost_kind": "resource"}
    return dispatch("defeat", "t", base | kw, state)


def test_a_chapter_one_defeat_is_accepted_and_costs_a_little():
    state = party("Ana", "Bo")
    start = state.world.time
    out = defeat(state, hours=6)
    assert not out.is_error and "6 hours pass" in out.content
    assert state.world.time == start.plus(6) and state.story.wipes == 0  # chapter 1 wipes are not counted
    assert state.story.costs[-1]["kind"] == "resource" and state.story.escape is None
    assert any("defeated" in c["note"] for c in state.story.choices)


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"how": "died"}, "how"),
        ({"aftermath": " "}, "aftermath"),
        ({"elapsed_hours": -1}, "elapsed_hours"),
        ({"elapsed_hours": 30}, "at most 24"),
        ({"cost": ""}, "what the defeat cost"),
        ({"cost_kind": "ally"}, "what the defeat cost"),
    ],
)
def test_a_bad_defeat_changes_nothing(extra, message):
    state = party("Ana", "Bo")
    before = (state.world.time, state.story.to_dict())
    out = defeat(state, **extra)
    assert out.is_error and message in out.content and (state.world.time, state.story.to_dict()) == before


def test_chapter_two_wipes_cost_more_each_time():
    state = party("Ana", "Bo", chapter=2)
    short = defeat(state, hours=12)
    assert short.is_error and "at least 24" in short.content and state.story.wipes == 0
    assert not defeat(state, hours=24).is_error and state.story.wipes == 1
    assert "at least 72" in defeat(state, hours=24).content
    assert not defeat(state, hours=72).is_error
    assert "at least 120" in defeat(state, hours=100).content
    assert not defeat(state, hours=120).is_error and state.story.wipes == 3
    assert st.wipe_minimum(4) == 144 and st.wipe_minimum(5) == 168


def test_a_chapter_two_defeat_can_run_into_a_doom_deadline():
    state = party("Ana", "Bo", chapter=2)
    state.story.dooms = [Doom("d2", "The ritual completes", [2, 3], Deadline(state.world.time.plus(30)), "e2")]
    defeat(state, "left", 48)
    st.settle_due(state.story, state.world, state.turn)
    assert state.story.fall is not None and "ritual" in state.story.fall["why"]


def test_a_defeat_in_the_endgame_loses_the_game():
    state = party("Ana", "Bo", chapter=3)
    start = state.world.time
    out = defeat(state, "taken", 5)
    assert not out.is_error and "failure ending" in out.content and state.story.fall is not None
    assert state.world.time == start and state.story.escape is None


def test_a_defeat_cannot_follow_a_lost_story():
    state = party("Ana", "Bo", chapter=3)
    st.lose(state.story, 10, "x")
    assert defeat(state).is_error


def test_a_defeat_with_no_story_just_passes_time():
    state = party("Ana", story=False)
    start = state.world.time
    out = defeat(state, "routed", 8)
    assert not out.is_error and state.world.time == start.plus(8)


# ---- capture never fails the game ------------------------------------------------------------


def test_a_deadline_people_set_slides_by_the_captivity():
    state = party("Ana", "Bo", chapter=2)
    state.story.dooms = [Doom("d2", "The ritual completes", [2, 3], Deadline(state.world.time.plus(200), "the glow"), "e2")]
    due = state.story.dooms[0].deadline.at
    out = defeat(state, "taken", 48)
    assert not out.is_error and "slid 48 hours" in out.content
    assert state.story.dooms[0].deadline.at == due.plus(48)
    assert any("held up" in c["text"] for c in state.story.costs)


def test_a_fixed_deadline_shortens_the_captivity():
    state = party("Ana", "Bo", chapter=2)
    now = state.world.time
    state.story.dooms = [Doom("d2", "The suns meet", [2, 3], Deadline(now.plus(100), "the suns", fixed=True), "e2")]
    out = defeat(state, "taken", 100)
    # 100 hours left: the reserve is a third (33), so at most 67 pass
    assert "cut to 67 hours" in out.content and state.world.time == now.plus(67)
    assert state.story.escape["hours"] == 33
    assert st.settle_due(state.story, state.world, state.turn) == [] and state.story.fall is None


def test_a_near_fixed_deadline_makes_the_escape_a_scene():
    state = party("Ana", "Bo", chapter=2)
    now = state.world.time
    state.story.dooms = [Doom("d2", "The suns meet", [2, 3], Deadline(now.plus(10), fixed=True), "e2")]
    out = defeat(state, "taken", 24)
    assert "escape is a scene" in out.content and state.story.escape is None and state.world.time == now


def test_only_a_capture_is_protected():
    state = party("Ana", "Bo", chapter=2)
    now = state.world.time
    state.story.dooms = [Doom("d2", "The suns meet", [2, 3], Deadline(now.plus(30), fixed=True), "e2")]
    defeat(state, "left", 48)
    st.settle_due(state.story, state.world, state.turn)
    assert state.story.fall is not None


# ---- the escape quest --------------------------------------------------------------------------


def test_a_capture_asks_for_an_escape_quest_and_the_briefing_says_so():
    state = party("Ana", "Bo")
    out = defeat(state, "taken", 12)
    assert state.story.escape["turn"] == state.turn and "being written" in out.content
    assert "The party is held" in st.briefing_block(state.story, state.world, state.turn)


async def test_the_service_writes_the_escape_quest():
    state = party("Ana", "Bo")
    state.world = world()
    state.campaign = CAMPAIGN
    defeat(state, "taken", 12)
    session = Session("s")
    session.state = state
    service = CuratorService(ScriptedCurator())
    assert service.escape_due(session) and await service.run_if_due(session)
    story = state.story
    [quest] = [m for m in story.milestones if m.escape]
    assert quest.status == "active" and quest.required and quest.requires == [] and quest.scale == "small"
    assert story.escape is None and not service.escape_due(session)


async def test_the_escape_plan_is_held_to_the_rules():
    state = party("Ana", "Bo", chapter=2)
    state.campaign = CAMPAIGN
    defeat(state, "taken", 30)
    seen = []

    class Curator(ScriptedCurator):
        async def plot(self, request):
            seen.append(request.feedback)
            out = await super().plot(request)
            if not request.feedback:
                out.entities.append(EntityProposal("The Pens", "faction"))
            return out

    result = await run_escape_plot(world(), CAMPAIGN, state.story, Curator())
    assert any("major addition" in f for f in seen[1]) and result.escape and len(result.milestones) == 1


async def test_a_broken_escape_plan_is_retried_then_dropped_after_the_stall():
    class Broken(ScriptedCurator):
        async def plot(self, request):
            raise CuratorError("no")

    state = party("Ana", "Bo")
    state.world = world()
    state.campaign = CAMPAIGN
    defeat(state, "taken", 12)
    session = Session("s")
    session.state = state
    service = CuratorService(Broken())
    assert not await service.run_if_due(session) and state.story.escape is not None
    state.turn += st.STALL_TURNS
    await service.run_if_due(session)
    assert state.story.escape is None


def test_the_escape_survives_a_save():
    state = party("Ana", "Bo")
    defeat(state, "taken", 12)
    again = st.Story.from_dict(state.story.to_dict())
    assert again.escape == state.story.escape
