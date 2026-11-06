"""Stakes, step 4 (docs/STAKES.md 3, 5, 10): chapter 3 failure, lost games, dooms, the forced ending."""

from aigm import story as st
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.story import Deadline, Doom
from aigm.tools import dispatch
from aigm.world import World, WorldTime
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService
from tests.test_plot import CAMPAIGN, world
from tests.test_story import short_story
from tests.test_story_gm import state_with_story


def chapter(n, **kw):
    state = state_with_story()
    s = state.story
    s.chapter = n
    for m in s.milestones:
        if m.chapter == 2:
            m.chapter, m.requires = n, []  # m3 and m4 are both open at once
    st.settle_ready(s)
    for k, v in kw.items():
        setattr(s, k, v)
    return state


def fail(state, quest="m3", **extra):
    q = {"id": quest, "status": "failed", "outcome": "The vault burned."} | extra
    return dispatch("set_scene", "t", {"story": {"quests": [q]}}, state)


def test_a_failed_required_quest_loses_the_game_in_chapter_three():
    state = chapter(3)
    state.story.milestone("m3").ending = "e2"
    out = fail(state)
    assert not out.is_error and "ends the story in failure" in out.content
    assert state.story.fall["ending"] == "e2" and "The vault burned." in state.story.fall["why"]
    assert st.needs_repair(state.story) is None  # nothing is mended in chapter 3


def test_a_failed_side_quest_does_not_lose_the_game():
    state = chapter(3)
    state.story.milestone("m3").required = False
    state.story.milestone("m3").status = "active"
    assert not fail(state).is_error and state.story.fall is None


def test_chapters_one_and_two_are_not_lost_by_a_failed_quest():
    state = chapter(2)
    fail(state, cost="Lost a day.", cost_kind="time", cost_hours=2)
    assert state.story.fall is None


def test_no_quest_can_be_finished_once_the_story_is_lost():
    state = chapter(3)
    fail(state)
    out = dispatch("set_scene", "t", {"story": {"quests": [{"id": "m4", "status": "done", "outcome": "ok"}]}}, state)
    assert out.is_error and "ending in failure" in out.content


def end(state, ending, **kw):
    return dispatch("end_story", "t", {"ending": ending, "epilogue": "It is over."} | kw, state)


def test_a_lost_story_must_play_out_its_own_ending():
    state = chapter(3)
    state.story.milestone("m3").ending = "e2"
    fail(state)
    bad = end(state, "e1")
    assert bad.is_error and "e2" in bad.content and not state.story.concluded
    assert not end(state, "e2").is_error and state.story.concluded and state.story.ending == "e2"


def test_a_lost_story_with_no_named_ending_may_use_any_listed_or_a_custom_one():
    state = chapter(3)
    fail(state)
    assert state.story.fall["ending"] is None
    assert not end(state, "end_custom").is_error


def test_a_lost_story_ends_without_the_climax():
    state = chapter(3)
    fail(state)
    assert any(m.status == "active" for m in state.story.milestones if m.chapter == 3)
    assert not end(state, "e2").is_error


def test_a_doom_ending_closes_chapter_two():
    state = chapter(2)
    state.story.dooms = [Doom("d1", "The party abandons the vale", [2, 3], None, "e2")]
    early = end(state, "e1")
    assert early.is_error  # an ordinary ending is still not allowed
    assert not end(state, "e2").is_error and state.story.concluded


def test_a_doom_of_another_chapter_does_not_count():
    state = chapter(2)
    state.story.dooms = [Doom("d1", "The vault is breached", [3], None, "e2")]
    assert end(state, "e2").is_error


# ---- the clock -----------------------------------------------------------------------------


def test_a_passed_chapter_three_deadline_loses_the_game():
    state = chapter(3)
    quest = state.story.milestone("m3")
    quest.deadline, quest.ending = Deadline(WorldTime(3, 12), "the suns"), "e2"
    state.world.time = WorldTime(3, 13)
    notes = st.settle_due(state.story, state.world, 12)
    assert notes and state.story.fall["ending"] == "e2" and state.story.fall["turn"] == 12
    assert st.settle_due(state.story, state.world, 13) == []  # it only counts once


def test_a_doom_deadline_loses_a_chapter_two_game():
    state = chapter(2)
    state.story.dooms = [Doom("d2", "Vane's ritual completes", [2, 3], Deadline(WorldTime(20, 0)), "e2")]
    state.world.time = WorldTime(20, 1)
    st.settle_due(state.story, state.world, 40)
    assert state.story.fall["ending"] == "e2" and "ritual completes" in state.story.fall["why"]


def test_an_unknown_ending_id_leaves_the_choice_to_the_gm():
    state = chapter(3)
    assert st.lose(state.story, 5, "x", "end_nothing") and state.story.fall["ending"] is None


# ---- what the GM is told, and the forced end -----------------------------------------------


def test_the_briefing_orders_the_ending_and_hides_the_rest():
    state = chapter(3)
    state.story.milestone("m3").ending = "e2"
    fail(state)
    text = st.briefing_block(state.story, state.world, state.story.fall["turn"])
    assert "THE STORY IS LOST" in text and "end_story" in text and "Active quests" not in text
    assert "ending \"Fallen\" (e2)" in text and "within 40 turns, the server will" in text


def test_the_briefing_lists_the_chapters_dooms_and_tripwires():
    state = chapter(2)
    state.story.dooms = [Doom("d1", "Vane's ritual completes", [2], None, "e2"), Doom("d3", "Vault breached", [3])]
    state.story.milestone("m3").fails_if = ["Vane burns the ledger"]
    text = st.briefing_block(state.story, state.world, 12)
    assert "Vane's ritual completes (ending e2)" in text and "Vault breached" not in text
    assert "It is lost if: Vane burns the ledger" in text


def test_the_server_ends_a_lost_story_the_gm_never_ended():
    state = chapter(3)
    state.story.milestone("m3").ending = "e2"
    fail(state)
    turn = state.story.fall["turn"]
    assert st.forced_ending(state.story, turn + 39) is None
    assert st.forced_ending(state.story, turn + 40).ok
    assert state.story.concluded and state.story.ending == "e2" and "failure" in state.story.epilogue


async def test_the_service_forces_the_ending_after_a_turn():
    state = chapter(3)
    fail(state)
    session = Session("s")
    session.state = state
    state.turn = state.story.fall["turn"] + 45
    await CuratorService(ScriptedCurator()).run_if_due(session)
    assert state.story.concluded


def test_a_lost_story_survives_a_save():
    state = chapter(3)
    fail(state)
    assert st.Story.from_dict(state.story.to_dict()).fall == state.story.fall
