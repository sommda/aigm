"""Session 0 asks what kind of game this is (docs/STORY.md 4): set_structure, and begin_adventure waiting for it."""

import json

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from aigm.game import Game
from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch
from tests.test_session_zero import GOOD


def call(mode, state):
    return dispatch("set_structure", "t", {"mode": mode}, state)


@pytest.mark.parametrize("mode", ["endless", "short", "medium", "long"])
def test_the_mode_is_recorded(mode):
    state = GameState()
    out = call(mode, state)
    assert not out.is_error and state.structure == mode


def test_the_last_choice_wins_and_repeating_one_changes_nothing():
    state = GameState()
    call("short", state)
    assert "already" in call("short", state).content
    assert not call("long", state).is_error and state.structure == "long"


@pytest.mark.parametrize("mode", ["epic", "", None, 3])
def test_other_modes_are_refused(mode):
    state = GameState()
    out = dispatch("set_structure", "t", {"mode": mode}, state)
    assert out.is_error and state.structure is None and "endless" in out.content


def test_a_story_is_told_not_to_plan_it_now():
    assert "do not plan it now" in call("short", GameState()).content
    assert "do not plan" not in call("endless", GameState()).content


def test_it_is_not_offered_or_accepted_once_the_adventure_has_begun():
    assert "set_structure" not in [t["name"] for t in Game().tools(GameState(Phase.ADVENTURE))]
    state = GameState(Phase.ADVENTURE, {"setting": "x"})
    out = call("long", state)
    assert out.is_error and state.structure == "endless"  # a game in play is endless unless it chose otherwise


# ---- begin_adventure waits for the answer -------------------------------------------------


def test_begin_adventure_is_refused_until_the_player_was_asked():
    state = GameState()
    out = dispatch("begin_adventure", "t", GOOD, state)
    assert out.is_error and "set_structure" in out.content and "what kind of game" in out.content
    assert state.phase is Phase.SESSION_ZERO and state.campaign is None
    call("medium", state)
    assert not dispatch("begin_adventure", "t", GOOD, state).is_error
    assert state.phase is Phase.ADVENTURE and state.structure == "medium"


def test_an_endless_choice_is_a_choice():
    state = GameState()
    call("endless", state)
    assert not dispatch("begin_adventure", "t", GOOD, state).is_error


def test_a_game_in_play_without_a_recorded_choice_is_endless():
    assert GameState(Phase.ADVENTURE).structure == "endless"
    loaded = GameState.from_dict({"phase": "adventure", "campaign": {"setting": "x"}})
    assert loaded.structure == "endless"
    zero = GameState.from_dict({"phase": "session_zero"})
    assert zero.structure is None


def test_a_session_zero_choice_is_saved():
    state = GameState()
    call("long", state)
    again = GameState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert again.structure == "long" and again.phase is Phase.SESSION_ZERO


# ---- the prompts -------------------------------------------------------------------------


def test_session_zero_asks_and_adventures_do_not_mention_it():
    lib = PromptLibrary()
    zero = lib.system_prompt(Phase.SESSION_ZERO)
    assert "Choosing the kind of game" in zero and "Always ask" in zero and "set_structure" in zero
    assert "four things" in zero and "kind of game" in zero.split("Finishing Session 0")[1]
    assert "Choosing the kind of game" not in lib.system_prompt(Phase.ADVENTURE)
    assert "ask the player" in lib.tool_description("set_structure")


def test_a_story_game_says_so_in_its_record_and_an_endless_one_does_not():
    lib, campaign = PromptLibrary(), {**GOOD}
    plain = lib.campaign_record(campaign)
    assert "Kind of game" not in plain
    assert plain == lib.campaign_record(campaign, structure="endless")
    story = lib.campaign_record(campaign, structure="short")
    assert "### Kind of game\n\nA short story" in story and story.index("Ruleset") < story.index("Kind of game")
    assert story.index("Kind of game") < story.index("### Party")
    assert "{{" not in story


def test_the_first_adventure_entry_carries_the_kind_of_game():
    state = GameState(Phase.ADVENTURE, dict(GOOD), structure="long")
    text = Game().history_after_begin(state)[1]["content"][0]["text"]
    assert "A long story" in text


# ---- over the API with the scripted model ------------------------------------------------


@pytest.fixture
def client(tmp_path):
    settings = Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None)
    return TestClient(create_app(settings))


def chat(client, text):
    with client.stream("POST", "/chat", json={"message": text}) as r:
        return [line for line in r.iter_lines() if line.startswith("event:")]


def test_the_scripted_model_can_choose_before_beginning(client):
    chat(client, "structure short")
    events = chat(client, "begin")
    assert "event: phase_change" in events
    assert client.get("/chat/history").json()["phase"] == "adventure"
