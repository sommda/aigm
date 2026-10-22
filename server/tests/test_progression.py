"""Experience and levels: the server keeps each character's totals, the GM awards them (docs/PROGRESSION.md)."""

from aigm import story as st
from aigm.game import Game
from aigm.models import Award
from aigm.session.state import GameState, Hero, Phase
from aigm.tools import dispatch, tool_schemas
from aigm.world import World
from tests.test_story import short_story

PARTY = [{"name": "Maren Holt", "sheet": "x"}, {"name": "Ilyr Wren", "sheet": "x"}, {"name": "Corvin", "sheet": "x"}]


def adventure(level=1, **kw):
    return GameState(Phase.ADVENTURE, {"setting": "x", "level": level, "party": PARTY}, World(), **kw)


def award(state, **given):
    return dispatch("award", "a1", {"reason": "the wolves", **given}, state)


def test_everyone_starts_at_the_level_session_zero_chose():
    state = adventure(level=3)
    assert [state.hero(n) for n in state.party_names] == [Hero(3, 0)] * 3 and state.average_level == 3


def test_xp_goes_to_the_whole_party_by_default_and_the_player_is_told():
    state = adventure()
    out = award(state, xp=120)
    assert not out.is_error and isinstance(out.event, Award)
    assert out.event.xp_gained == 120 and out.event.to == state.party_names and out.event.reason == "the wolves"
    assert [state.hero(n).xp for n in state.party_names] == [120, 120, 120]


def test_xp_can_go_to_some_characters_by_name_in_any_case():
    state = adventure()
    out = award(state, xp=50, who=["ilyr  wren", "CORVIN"])
    assert out.event.to == ["Ilyr Wren", "Corvin"]
    assert [state.hero(n).xp for n in state.party_names] == [0, 50, 50]


def test_every_xp_award_tells_the_gm_to_check_for_level_ups():
    out = award(adventure(), xp=300)
    assert "Maren Holt: level 1, 300 XP" in out.content and "advancement table for their class" in out.content
    assert "`level_up`" in out.content
    assert "advancement table" not in award(adventure(), level_up=["Corvin"]).content


def test_levels_are_per_character_and_one_at_a_time():
    state = adventure()
    out = award(state, level_up=["Maren Holt"])
    assert [s.level for s in out.event.characters] == [2] and out.event.characters[0].previous_level == 1
    assert [state.hero(n).level for n in state.party_names] == [2, 1, 1]
    award(state, level_up=["Maren Holt", "Corvin"])
    assert [state.hero(n).level for n in state.party_names] == [3, 1, 2]
    assert round(state.average_level, 2) == 2.0 and round(out.event.average_level, 2) == 1.33


def test_bad_awards_change_nothing():
    state = adventure()
    for given in ({}, {"xp": -5}, {"xp": "lots"}, {"xp": 10, "who": ["Nobody"]}, {"level_up": ["Nobody"]}, {"xp": 1, "who": []}):
        assert award(state, **given).is_error
    assert dispatch("award", "a", {"xp": 10}, state).is_error  # no reason
    assert state.heroes == {}
    state.heroes["Corvin"] = Hero(20, 0)
    assert award(state, level_up=["Corvin"]).is_error


def test_the_tool_is_for_adventures_only():
    assert "award" in [t["name"] for t in tool_schemas(phase=Phase.ADVENTURE)]
    assert "award" not in [t["name"] for t in tool_schemas(phase=Phase.SESSION_ZERO)]


def test_the_notes_show_each_characters_level_and_xp():
    state = adventure(level=2)
    town = state.world.add_entity("Ashby", "location")
    state.world.set_scene(town.id, [])
    assert "Party: Maren Holt level 2; Ilyr Wren level 2; Corvin level 2.\n" in Game().briefing(state, "hi", "")
    award(state, xp=450, who=["Corvin"])
    assert "Corvin level 2, 450 XP." in Game().briefing(state, "hi", "")


def test_the_totals_survive_a_save_and_copy():
    state = adventure()
    award(state, xp=90)
    award(state, level_up=["Corvin"])
    for again in (GameState.from_dict(state.to_dict()), state.copy()):
        assert again.hero("Corvin") == Hero(2, 90) and again.hero("Maren Holt") == Hero(1, 90)
    old = state.to_dict()
    del old["heroes"]
    assert GameState.from_dict(old).hero("Corvin") == Hero(1, 0)  # saves from before version 5


# ---- the story's chapter levels ------------------------------------------------------------------------------------


def story_state(target=3):
    story = short_story()
    story.chapters[0].target_level = target
    story.goal.revealed = True
    state = adventure(story=story, structure="short", turn=10)
    state.story.party_level = state.average_level
    return state


def test_a_chapter_waits_for_the_average_party_level():
    state = story_state(target=2)
    for q in ("m1", "m2"):
        st.report(state.story, q, "done", "Done.", 5)
    assert state.story.chapter == 1 and st.level_short(state.story) and not st.chapter_complete(state.story)
    award(state, level_up=["Maren Holt", "Ilyr Wren"])
    assert state.story.chapter == 1 and round(state.story.party_level, 2) == 1.67  # not yet two on average
    out = award(state, level_up=["Corvin", "Maren Holt"])
    assert state.story.chapter == 2 and "Chapter 2 begins" in out.content  # the award itself ended the chapter


def test_the_level_gate_lapses_after_the_grace_period():
    state = story_state(target=5)
    for q in ("m1", "m2"):
        st.report(state.story, q, "done", "Done.", 5)
    assert not st.chapter_complete(state.story, 10)
    assert st.chapter_complete(state.story, 1 + st.LEVEL_GRACE_TURNS)


def test_the_briefing_says_what_the_chapter_needs():
    state = story_state(target=3)
    notes = st.briefing_block(state.story, state.world, 10, 12)
    assert "average level is 1.0" in notes and "reaches 3" in notes
    for q in ("m1", "m2"):
        st.report(state.story, q, "done", "Done.", 5)
    assert "below the level this chapter needs" in st.briefing_block(state.story, state.world, 10, 12)
