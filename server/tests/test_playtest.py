"""Playtest mode (docs/PLAYTEST.md): a debug-only state in which the GM sets the game up on request."""

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from aigm.game import Game
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch, tool_schemas
from aigm.world import World, WorldTime

CAMPAIGN = {"setting": "x", "party": [{"name": "Mira"}], "party_size": 1, "level": 1}


def state(playtest=True):
    s = GameState(Phase.ADVENTURE, dict(CAMPAIGN), World())
    s.playtest = playtest
    return s


def names(**kw):
    return [t["name"] for t in tool_schemas(**kw)]


def test_playtest_tools_are_offered_only_in_playtest_mode():
    extra = {"end_playtest", "playtest_time", "playtest_hero"}
    assert not extra & set(names())
    assert extra <= set(names(playtest=True))
    assert not extra & set(names(phase=Phase.SESSION_ZERO, playtest=True))


def test_playtest_tools_do_not_run_outside_playtest_mode():
    out = dispatch("playtest_time", "t1", {"day": 2, "hour": 3}, state(playtest=False))
    assert out.is_error and "Unknown tool" in out.content


def test_the_prompt_and_tools_follow_the_mode():
    game = Game()
    assert "PLAYTEST MODE" not in game.system(state(False)) and game.system(state()).startswith("# PLAYTEST MODE")
    assert "You describe the world, play every NPC" not in game.system(state())  # the GM's role is suspended
    assert "end_playtest" in [t["name"] for t in game.tools(state())]
    assert "end_playtest" not in [t["name"] for t in game.tools(state(False))]


def test_end_playtest_leaves_the_mode():
    s = state()
    out = dispatch("end_playtest", "t1", {}, s)
    assert not out.is_error and not s.playtest


def test_the_clock_can_be_set_backward():
    s = state()
    s.world.set_time(WorldTime(5, 12))
    out = dispatch("playtest_time", "t1", {"day": 1, "hour": 23, "minute": 30}, s)
    assert not out.is_error and s.world.time == WorldTime(1, 23, 30)
    bad = dispatch("playtest_time", "t2", {"day": 0, "hour": 3}, s)
    assert bad.is_error and s.world.time == WorldTime(1, 23, 30)


def test_a_hero_level_can_be_set():
    s = state()
    out = dispatch("playtest_hero", "t1", {"name": "mira", "level": 7, "xp": 900, "classes": {"Rogue": 7}}, s)
    assert not out.is_error
    hero = s.hero("Mira")
    assert (hero.level, hero.xp, hero.classes) == (7, 900, {"Rogue": 7})
    assert dispatch("playtest_hero", "t2", {"name": "Nobody", "level": 3}, s).is_error
    assert dispatch("playtest_hero", "t3", {"name": "Mira", "level": 99}, s).is_error


def test_the_flag_is_saved_and_copied():
    s = state()
    assert s.copy().playtest and GameState.from_dict(s.to_dict()).playtest
    assert "playtest" not in state(False).to_dict()


@pytest.fixture
def client(tmp_path):
    def make(debug):
        app = create_app(Settings(_env_file=None, debug=debug, save_dir=str(tmp_path), anthropic_api_key="k"))
        return app, TestClient(app)

    return make


def test_the_endpoint_exists_only_in_debug_mode(client):
    _, plain = client(False)
    assert plain.post("/debug/playtest", json={}).status_code == 404


def test_the_endpoint_turns_the_mode_on_and_off_in_an_adventure(client):
    app, http = client(True)
    session = app.state.sessions.get("default")
    assert http.post("/debug/playtest", json={}).status_code == 409  # Session 0
    session.state = state(False)
    assert http.post("/debug/playtest", json={}).json()["playtest"] is True and session.state.playtest
    assert http.post("/debug/playtest", json={"enabled": False}).json()["playtest"] is False
    session.busy = True
    assert http.post("/debug/playtest", json={}).status_code == 409


def test_ending_playtest_makes_a_curator_pass_due_at_once():
    from aigm.session.store import Session
    from aigm.world.scripted import ScriptedCurator
    from aigm.world.service import CuratorService

    session = Session("s")
    session.state = state()
    session.state.world.set_scene(session.state.world.add_entity("Ashby", "location").id)
    session.messages = [
        {"role": "user", "content": [{"type": "text", "text": "add a rival"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
    ]
    svc = CuratorService(ScriptedCurator(), every_pages=3, page_chars=1500)
    assert not svc.due(session)  # a short exchange alone is not enough
    dispatch("end_playtest", "t1", {}, session.state)
    assert session.state.pass_now and svc.due(session)
    assert session.state.copy().pass_now


def story_state():
    from aigm.story import Chapter, Goal, Milestone, Story

    s = state()
    s.structure = "short"
    s.story = Story(
        "short", Goal("The silver", "x"),
        [Chapter("One", "p"), Chapter("Two", "p"), Chapter("Three", "p")],
        [Milestone("m01", 1, "A", "b", status="active"), Milestone("m02", 2, "B", "b"), Milestone("m03", 3, "C", "b")],
    )  # fmt: skip
    return s


def test_the_story_tool_is_for_story_games_in_playtest_mode():
    assert "playtest_story" not in names(playtest=True)
    assert "playtest_story" in names(playtest=True, structured=True)


def test_playtest_story_jumps_chapters_and_settles_what_it_passes():
    s = story_state()
    out = dispatch("playtest_story", "t1", {"chapter": 2}, s)
    assert not out.is_error and s.story.chapter == 2
    assert s.story.milestone("m01").status == "skipped" and s.story.goal.revealed
    assert s.story.milestone("m02").status == "active"  # opened by the jump
    out = dispatch("playtest_story", "t2", {"quests": [{"id": "m02", "status": "done"}]}, s)
    assert not out.is_error and s.story.milestone("m02").status == "done"
    assert dispatch("playtest_story", "t3", {"chapter": 9}, s).is_error
    assert dispatch("playtest_story", "t4", {"quests": [{"id": "zz", "status": "done"}]}, s).is_error
