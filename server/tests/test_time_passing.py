"""Time that passes inside the tools (docs/TIME.md 4): a roll's minutes, a fight's end, pass_time, and the briefing's line
about the last turn."""

import pytest

from aigm.session.state import GameState, Phase
from aigm.tools import dispatch, tool_schemas
from aigm.world import WorldTime
from aigm.world.briefing import build_briefing
from aigm.world.model import World, duration_text

NARRATION = "Kit kneels at the vault lock, picks between her teeth."


@pytest.fixture
def state():
    s = GameState(Phase.ADVENTURE, {"setting": "x", "party": [{"name": "Kit", "sheet": "Rogue"}]})
    inn = s.world.add_entity("The Rusty Flagon", "location")
    s.world.set_scene(inn.id, [])
    s.turn = 5
    return s


def roll(state, **over):
    args = {"expression": "1d20+0 # lockpicking", "narration": NARRATION}
    args.update(over)
    return dispatch("roll_dice", "t1", args, state)


@pytest.mark.parametrize(
    "minutes, text",
    [(1, "1 minute"), (45, "45 minutes"), (60, "1 hour"), (150, "2 hours 30 minutes"), (1500, "1 day 1 hour"), (0, "no time")],
)
def test_a_duration_in_words(minutes, text):
    assert duration_text(minutes) == text


def test_a_roll_with_minutes_moves_the_clock(state):
    out = roll(state, minutes=10)
    assert not out.is_error and state.world.time == WorldTime(1, 8, 10) and state.world.reported_minutes == 10
    assert "10 minutes pass. It is now Day 1, 08:10." in out.content
    assert state.world.time_log == [{"turn": 5, "minutes": 10, "why": "lockpicking"}]


def test_a_roll_without_minutes_is_a_moment(state):
    out = roll(state)
    assert not out.is_error and state.world.time == WorldTime(1, 8, 0) and "pass" not in out.content


@pytest.mark.parametrize("bad", [-1, 1.5, True, 1441, "10"])
def test_a_roll_refuses_bad_minutes_and_rolls_nothing(state, bad):
    out = roll(state, minutes=bad)
    assert out.is_error and "minutes" in out.content and out.event is None and state.world.time == WorldTime(1, 8, 0)


def test_a_session_zero_roll_ignores_minutes():
    zero = GameState(Phase.SESSION_ZERO)
    out = dispatch("roll_dice", "t1", {"expression": "3d6", "narration": "Rolling Strength.", "minutes": 10}, zero)
    assert not out.is_error and "pass" not in out.content and zero.world.time == WorldTime(1, 8, 0)


def test_pass_time(state):
    out = dispatch("pass_time", "t1", {"minutes": 45, "reason": "the steward talks through the accounts"}, state)
    assert not out.is_error and state.world.time == WorldTime(1, 8, 45)
    assert "45 minutes pass. It is now Day 1, 08:45." in out.content
    assert state.world.time_log[-1] == {"turn": 5, "minutes": 45, "why": "the steward talks through the accounts"}


@pytest.mark.parametrize(
    "args",
    [
        {"minutes": 0, "reason": "a moment"}, {"minutes": 1441, "reason": "too long"}, {"minutes": 5},
        {"minutes": True, "reason": "yes"}, {"reason": "no minutes"}, {"minutes": 5, "reason": " "},
    ],
)
def test_pass_time_refuses_a_bad_call(state, args):
    out = dispatch("pass_time", "t1", args, state)
    assert out.is_error and out.content.startswith("No time passed") and state.world.time == WorldTime(1, 8, 0)


def test_pass_time_is_an_adventure_tool():
    assert "pass_time" not in {t["name"] for t in tool_schemas(phase=Phase.SESSION_ZERO)}
    assert "pass_time" in {t["name"] for t in tool_schemas()}


def test_ending_a_fight_takes_ten_minutes_or_what_the_gm_says(state):
    dispatch("set_combat", "t1", {"action": "start", "combatants": [{"name": "Wolf", "side": "foe"}]}, state)
    dispatch("set_combat", "t2", {"action": "end", "minutes": 25}, state)
    assert state.world.time == WorldTime(1, 8, 25)
    out = dispatch("set_combat", "t3", {"action": "end"}, state)  # no fight: no time
    assert state.world.time == WorldTime(1, 8, 25) and "no fight" in out.content.lower()


def test_set_scene_minutes_are_logged(state):
    dispatch("set_scene", "t1", {"elapsed_minutes": 30}, state)
    assert state.world.time_log == [{"turn": 5, "minutes": 30, "why": "time passing"}]


def test_the_briefing_says_how_long_the_last_turn_took(state):
    roll(state, minutes=10)
    pass_ = dispatch("pass_time", "t1", {"minutes": 20, "reason": "a patient watch"}, state)
    assert not pass_.is_error
    this_turn = build_briefing(state.world, turn=5)
    assert "Last turn took" not in this_turn  # it is this turn's time, not the last one's
    next_turn = build_briefing(state.world, turn=6)
    assert "Last turn took 30 minutes (lockpicking; a patient watch)." in next_turn
    assert "Last turn took" not in build_briefing(state.world, turn=7)  # only the turn before


def test_the_time_log_survives_a_save_and_old_worlds_have_none(state):
    roll(state, minutes=10)
    again = World.from_dict(state.world.to_dict())
    assert again.time_log == state.world.time_log
    data = state.world.to_dict()
    del data["time_log"]
    assert World.from_dict(data).time_log == []


def test_the_briefing_says_when_a_turn_put_nothing_on_the_clock():
    from aigm.world.briefing import build_briefing

    w = World()
    w.set_scene(w.add_entity("Mine", "location").id, [])
    assert "put nothing on the clock" not in build_briefing(w, turn=1)
    assert "put nothing on the clock" in build_briefing(w, turn=3)
    w.advance_minutes(30, reported=True, turn=2, why="a long talk")
    text = build_briefing(w, turn=3)
    assert "Last turn took" in text and "put nothing on the clock" not in text
