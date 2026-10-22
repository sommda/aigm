"""Experience and levels: the server keeps the party's totals, the GM awards them (docs/PROGRESSION.md)."""

from aigm.game import Game
from aigm.models import Award
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch, tool_schemas
from aigm.world import World


def adventure(level=1, **kw):
    return GameState(Phase.ADVENTURE, {"setting": "x", "level": level, "party": []}, World(), **kw)


def test_the_party_starts_at_the_level_session_zero_chose():
    state = adventure(level=3)
    assert state.party_level == 3 and state.level is None and state.xp == 0


def test_xp_adds_up_and_the_player_is_told():
    state = adventure()
    out = dispatch("award", "a1", {"xp": 120, "reason": "the wolves"}, state)
    assert not out.is_error and isinstance(out.event, Award)
    assert (out.event.xp_gained, out.event.xp, out.event.level, out.event.reason) == (120, 120, 1, "the wolves")
    dispatch("award", "a2", {"xp": 80, "reason": "the bridge troll"}, state)
    assert state.xp == 200 and state.party_level == 1


def test_a_level_goes_up_one_at_a_time():
    state = adventure()
    out = dispatch("award", "a", {"level": 2, "reason": "the first quest"}, state)
    assert not out.is_error and out.event.previous_level == 1 and out.event.level == 2
    assert state.party_level == 2 and "update every character sheet" in out.content
    for bad in (2, 4, 1):
        assert dispatch("award", "b", {"level": bad, "reason": "x"}, state).is_error
    assert state.party_level == 2


def test_bad_awards_change_nothing():
    state = adventure()
    for given in ({"reason": "x"}, {"xp": -5, "reason": "x"}, {"xp": "lots", "reason": "x"}, {"xp": 10}, {"xp": 10, "reason": " "}):
        assert dispatch("award", "a", given, state).is_error
    assert (state.xp, state.level) == (0, None)


def test_the_tool_is_for_adventures_only():
    assert "award" in [t["name"] for t in tool_schemas(phase=Phase.ADVENTURE)]
    assert "award" not in [t["name"] for t in tool_schemas(phase=Phase.SESSION_ZERO)]


def test_the_notes_show_the_party_level_and_xp():
    state = adventure(level=2)
    town = state.world.add_entity("Ashby", "location")
    state.world.set_scene(town.id, [])
    assert "Party: level 2.\n" in Game().briefing(state, "hi", "")
    dispatch("award", "a", {"xp": 450, "reason": "x"}, state)
    assert "Party: level 2, 450 XP." in Game().briefing(state, "hi", "")


def test_the_totals_survive_a_save_and_copy():
    state = adventure()
    dispatch("award", "a", {"xp": 90, "level": 2, "reason": "x"}, state)
    for again in (GameState.from_dict(state.to_dict()), state.copy()):
        assert (again.xp, again.level, again.party_level) == (90, 2, 2)
    old = state.to_dict()
    del old["level"], old["xp"]
    assert GameState.from_dict(old).party_level == 1  # saves from before version 5
