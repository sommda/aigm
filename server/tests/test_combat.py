"""The fight record and the set_combat tool (docs/STATUS.md 4)."""

import json

import pytest
from fastapi.testclient import TestClient

from aigm import status
from aigm.app import create_app
from aigm.combat import Combat, Combatant, read_combat
from aigm.config import Settings
from aigm.errors import CorruptSave
from aigm.game import Game
from aigm.session.state import GameState, Phase
from aigm.sheets import Section, Sheet
from aigm.tools import dispatch, tool_schemas
from tests.conftest import chat


def make_state() -> GameState:
    campaign = {"setting": "x", "opening": "y", "level": 1, "party": [{"name": "Toby Fenn", "sheet": "s", "background": "b"}]}
    sheet = Sheet("Rogue 3", 11, 15, ["prone"], [Section("Gear", ["Dagger"])])
    return GameState(Phase.ADVENTURE, campaign, sheets={"Toby Fenn": sheet})


def call(state, **args):
    return dispatch("set_combat", "t1", args, state)


WOLVES = {"name": "Wolf", "side": "foe", "count": 4}


def test_a_fight_starts_updates_and_ends():
    state = make_state()
    assert call(state, action="start", combatants=[WOLVES, {"name": "Mira", "side": "ally", "health": "9/12"}]).content == (
        "Fight: Wolf x4 (unhurt), Mira (9/12)."
    )
    out = call(state, action="update", combatants=[{"name": "wolf", "health": "Bloodied", "count": 3, "conditions": ["prone"]}])
    wolf = state.combat.find("Wolf")
    assert not out.is_error and (wolf.health, wolf.count, wolf.conditions) == ("bloodied", 3, ["prone"])
    call(state, action="update", combatants=[{"name": "Wolf", "remove": True}, {"name": "Bandit", "side": "foe"}])
    assert [c.name for c in state.combat.combatants] == ["Mira", "Bandit"]
    assert call(state, action="end").content == "The fight is over." and state.combat is None


def test_foes_show_words_not_numbers():
    state = make_state()
    out = call(state, action="start", combatants=[{"name": "Ogre", "side": "foe", "health": "34/60"}])
    assert out.is_error and "one of unhurt" in out.content and state.combat is None


def test_bad_calls_change_nothing():
    state = make_state()
    call(state, action="start", combatants=[WOLVES])
    before = state.combat.to_dict()
    for args, text in [
        ({"action": "dance"}, "start, update or end"),
        ({"action": "start"}, "list"),
        ({"action": "update", "combatants": [{"name": "Toby Fenn", "side": "ally"}]}, "party member"),
        ({"action": "update", "combatants": [{"name": "Bear"}]}, "side must be"),
        ({"action": "update", "combatants": [{"name": "Bear", "remove": True}]}, "not in the fight"),
        ({"action": "update", "combatants": [{"name": "Wolf", "count": 0}]}, "count must be"),
        ({"action": "update", "combatants": ["Wolf"]}, "needs a name"),
    ]:
        out = call(state, **args)
        assert out.is_error and text in out.content, (args, out.content)
    assert state.combat.to_dict() == before
    assert call(make_state(), action="update", combatants=[WOLVES]).is_error


def test_an_ally_that_turns_foe_loses_its_numbers():
    state = make_state()
    call(state, action="start", combatants=[{"name": "Mira", "side": "ally", "health": "9/12"}])
    call(state, action="update", combatants=[{"name": "Mira", "side": "foe"}])
    assert state.combat.find("Mira").health == "unhurt"


def test_moving_the_party_ends_the_fight_but_staying_does_not():
    state = make_state()
    for name in ("Docks", "Customs House"):
        dispatch("establish", "e", {"entities": [{"name": name, "kind": "location"}], "facts": []}, state)
    dispatch("set_scene", "s", {"location": "Docks"}, state)
    call(state, action="start", combatants=[WOLVES])
    dispatch("set_scene", "s", {"elapsed_hours": 1}, state)
    assert state.combat is not None
    dispatch("set_scene", "s", {"location": "Customs House"}, state)
    assert state.combat is None


def test_it_is_saved_copied_and_checked():
    state = make_state()
    call(state, action="start", combatants=[WOLVES])
    again = GameState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert again.combat.to_dict() == state.combat.to_dict() and state.copy().combat.to_dict() == state.combat.to_dict()
    assert GameState.from_dict({**state.to_dict(), "combat": None}).combat is None
    with pytest.raises(CorruptSave):
        read_combat({"combatants": [{"name": "Wolf", "side": "dragon", "count": 1, "health": "x", "conditions": []}]})
    with pytest.raises(CorruptSave):
        read_combat("fight")


def test_it_is_offered_in_the_adventure_only():
    names = lambda phase: [t["name"] for t in tool_schemas(phase=phase)]  # noqa: E731
    assert "set_combat" in names(Phase.ADVENTURE) and "set_combat" not in names(Phase.SESSION_ZERO)


def test_the_gm_is_reminded_of_the_table():
    state = make_state()
    assert "Fight in progress" not in Game().briefing(state, "hi", "")
    call(state, action="start", combatants=[WOLVES])
    assert "Wolf x4 [foe] unhurt" in Game().briefing(state, "hi", "")


def test_the_status_table_changes_in_a_fight():
    state = make_state()
    page = status.build(state)
    assert page["combat"] is None and page["table"]["columns"][1] == "HP"
    call(state, action="start", combatants=[WOLVES, {"name": "Mira", "side": "ally", "health": "9/12"}])
    page = status.build(state)
    assert page["combat"] == {"foes": 4}
    assert page["table"]["columns"] == ["Name", "Side", "Health", "Conditions"]
    assert page["table"]["rows"] == [
        ["Toby Fenn", "Party", "11/15", "prone"], ["Mira", "Ally", "9/12", "-"], ["Wolf x4", "Foe", "unhurt", "-"]
    ]


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None))
    client = TestClient(app)
    client.session = app.state.sessions.get("default")
    return client


def test_a_scripted_fight_reaches_the_status_route(api):
    chat(api, "begin")
    chat(api, "fight Wolf 3")
    page = api.get("/status").json()
    assert page["combat"] == {"foes": 3} and ["Wolf x3", "Foe", "unhurt", "-"] in page["table"]["rows"]
    chat(api, "wound Wolf near death")
    assert ["Wolf x3", "Foe", "near death", "-"] in api.get("/status").json()["table"]["rows"]
    chat(api, "peace")
    assert api.get("/status").json()["combat"] is None
