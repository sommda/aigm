"""Stakes, step 2 (docs/STAKES.md 6): the cost of a failed quest, the briefing line, the clock move."""

import pytest

from aigm import story as st
from aigm.tools import dispatch
from tests.test_story_gm import state_with_story


def fail(state, quest="m1", **extra):
    q = {"id": quest, "status": "failed", "outcome": "It went wrong."} | extra
    return dispatch("set_scene", "t", {"story": {"quests": [q]}}, state)


def test_a_failed_quest_needs_a_cost_in_chapters_one_and_two():
    for chapter in (1, 2):
        state = state_with_story()
        state.story.chapter = chapter
        st.settle_ready(state.story)
        quest = "m1" if chapter == 1 else "m3"
        before = state.story.to_dict()
        out = fail(state, quest)
        assert out.is_error and "cost" in out.content and state.story.to_dict() == before


def test_a_cost_is_recorded_and_noted():
    state = state_with_story()
    out = fail(state, cost="The miller's debt took 40 gold.", cost_kind="resource")
    assert not out.is_error and "Cost recorded" in out.content
    [cost] = state.story.costs
    assert (cost["kind"], cost["chapter"], cost["milestone"], cost["turn"]) == ("resource", 1, "m1", 10)
    assert state.story.milestone("m1").status == "failed"


def test_chapter_one_costs_are_small_kinds_only():
    state = state_with_story()
    out = fail(state, cost="An ally walked away.", cost_kind="ally")
    assert out.is_error and "time, resource" in out.content and not state.story.costs
    state = state_with_story()
    state.story.chapter = 2
    st.settle_ready(state.story)
    assert not fail(state, "m3", cost="An ally walked away.", cost_kind="ally").is_error


def test_a_time_cost_moves_the_clock():
    state = state_with_story()
    start = state.world.time
    out = fail(state, cost="They lost a day to the storm.", cost_kind="time", cost_hours=24)
    assert not out.is_error and "24 hours" in out.content
    assert state.world.time == start.plus(24) and state.story.costs[0]["hours"] == 24


@pytest.mark.parametrize("hours", [None, 0, 25, "3", True])
def test_a_time_cost_needs_sensible_hours(hours):
    state = state_with_story()
    extra = {} if hours is None else {"cost_hours": hours}
    start = state.world.time
    out = fail(state, cost="Lost time.", cost_kind="time", **extra)
    assert out.is_error and "cost_hours" in out.content and state.world.time == start and not state.story.costs


def test_a_cost_goes_only_with_a_failure():
    state = state_with_story()
    out = dispatch(
        "set_scene", "t",
        {"story": {"quests": [{"id": "m1", "status": "done", "outcome": "ok", "cost": "x", "cost_kind": "time"}]}},
        state,
    )  # fmt: skip
    assert out.is_error and "only with a failed quest" in out.content


def test_the_curator_may_report_a_failure_without_a_cost():
    from aigm.tools.story import check_story_report

    state = state_with_story()
    story, problems, _ = check_story_report(
        {"quests": [{"id": "m1", "status": "failed", "outcome": "The miller died."}]}, state, require_cost=False
    )
    assert not problems and story.milestone("m1").status == "failed" and not story.costs


def test_the_briefing_lists_recent_costs():
    state = state_with_story()
    for i in range(4):
        st.record_cost(state.story, i, "m1", "resource", f"Paid toll {i}")
    text = st.briefing_block(state.story, state.world, 10)
    assert "Paid toll 3" in text and "Paid toll 1" in text and "Paid toll 0" not in text
    assert "What failure has cost" not in st.briefing_block(state_with_story().story, state.world, 10)


def test_the_cost_log_is_bounded():
    state = state_with_story()
    for i in range(st.MAX_COSTS + 5):
        st.record_cost(state.story, i, "m1", "resource", f"c{i}")
    assert len(state.story.costs) == st.MAX_COSTS and state.story.costs[-1]["text"] == f"c{st.MAX_COSTS + 4}"


def test_costs_do_not_exist_in_endless_games():
    assert st.record_cost(st.Story(st.ENDLESS), 1, "m1", "resource", "x") == "this game has no costs"
