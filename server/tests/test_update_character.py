"""The update_character tool (docs/STATUS.md 3.3): changes to a party member's sheet."""

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from aigm.game import Game
from aigm.session.state import GameState, Phase
from aigm.sheets import MAX_SECTIONS, Section, Sheet
from aigm.tools import dispatch, tool_schemas
from tests.conftest import chat


def make_state() -> GameState:
    sheet = Sheet("Human Rogue 3", 11, 15, ["prone"], [Section("Gear", ["Dagger", "12 gp"]), Section("Spells", ["none"])])
    campaign = {"setting": "x", "opening": "y", "level": 1, "party": [{"name": "Toby Fenn", "sheet": "s", "background": "b"}]}
    return GameState(Phase.ADVENTURE, campaign, sheets={"Toby Fenn": sheet})


def call(state, **args):
    return dispatch("update_character", "t1", args, state)


def test_damage_and_healing_move_hit_points_within_the_limits():
    state = make_state()
    assert call(state, name="toby fenn", hp_delta=-4).content == "Toby Fenn: HP 7/15; conditions: prone."
    assert state.sheets["Toby Fenn"].hp == 7
    assert state.sheets["Toby Fenn"].copy().hp == 7
    out = call(state, name="Toby Fenn", hp_delta=-40)
    assert state.sheets["Toby Fenn"].hp == 0 and "held at 0" in out.content and not out.is_error
    call(state, name="Toby Fenn", hp=99)
    assert state.sheets["Toby Fenn"].hp == 15


def test_the_maximum_can_change_and_pulls_hit_points_down_with_it():
    state = make_state()
    call(state, name="Toby Fenn", max_hp=8)
    assert (state.sheets["Toby Fenn"].hp, state.sheets["Toby Fenn"].max_hp) == (8, 8)
    call(state, name="Toby Fenn", max_hp=20, hp=20)
    assert state.sheets["Toby Fenn"].hp == 20


def test_conditions_are_added_removed_and_not_doubled():
    state = make_state()
    out = call(state, name="Toby Fenn", conditions_add=["Poisoned", "poisoned", "PRONE"], conditions_remove=["blind"])
    assert state.sheets["Toby Fenn"].conditions == ["prone", "Poisoned"] and "Not on Toby Fenn to remove: blind" in out.content
    call(state, name="Toby Fenn", conditions_remove=["Prone"])
    assert state.sheets["Toby Fenn"].conditions == ["Poisoned"]


def test_a_section_is_replaced_added_or_removed():
    state = make_state()
    call(state, name="Toby Fenn", section={"title": "gear", "lines": ["Dagger", "Healing potion"]})
    call(state, name="Toby Fenn", section={"title": "Notes", "lines": ["Owes Elian a favor"]})
    call(state, name="Toby Fenn", section={"title": "Spells", "lines": []})
    sections = {s.title: s.lines for s in state.sheets["Toby Fenn"].sections}
    assert sections == {"Gear": ["Dagger", "Healing potion"], "Notes": ["Owes Elian a favor"]}


def test_bad_calls_change_nothing_and_say_why():
    state = make_state()
    before = state.sheets["Toby Fenn"].to_dict()
    for args, text in [
        ({"name": "Elian", "hp": 3}, "not a party member"),
        ({"name": "Toby Fenn"}, "nothing to change"),
        ({"name": "Toby Fenn", "hp": 3, "hp_delta": 1}, "not both"),
        ({"name": "Toby Fenn", "hp": "three"}, "whole numbers"),
        ({"name": "Toby Fenn", "hp_delta": -2, "conditions_add": "poisoned"}, "list of strings"),
        ({"name": "Toby Fenn", "section": {"title": "Gear"}}, "needs a title"),
    ]:
        out = call(state, **args)
        assert out.is_error and text in out.content, (args, out.content)
    assert state.sheets["Toby Fenn"].to_dict() == before


def test_a_full_sheet_cannot_take_another_section():
    state = make_state()
    state.sheets["Toby Fenn"].sections = [Section(f"S{i}", ["x"]) for i in range(MAX_SECTIONS)]
    assert "at most" in call(state, name="Toby Fenn", section={"title": "New", "lines": ["x"]}).content


def test_a_character_with_no_sheet_or_no_maximum_is_explained():
    state = make_state()
    del state.sheets["Toby Fenn"]
    assert "no sheet on record" in call(state, name="Toby Fenn", hp=3).content
    state.sheets["Toby Fenn"] = Sheet("", None, None, [], [Section("Gear", ["x"])])
    assert "no hit point maximum" in call(state, name="Toby Fenn", hp_delta=-1).content


def test_it_is_offered_in_the_adventure_only():
    names = lambda phase: [t["name"] for t in tool_schemas(phase=phase)]  # noqa: E731
    assert "update_character" in names(Phase.ADVENTURE) and "update_character" not in names(Phase.SESSION_ZERO)
    state = make_state()
    state.phase = Phase.SESSION_ZERO
    assert dispatch("update_character", "t", {"name": "Toby Fenn", "hp": 1}, state).is_error


def test_the_gm_sees_the_sheets_in_the_briefing_and_they_follow_changes():
    game = Game()
    state = make_state()
    call(state, name="Toby Fenn", hp_delta=-6, section={"title": "Gear", "lines": ["Dagger", "Rope"]})
    notes = game.briefing(state, "hello", "")
    assert "Character sheets (change them with update_character)" in notes
    assert "Toby Fenn: Human Rogue 3; HP 5/15; conditions: prone" in notes and "Gear: Dagger | Rope" in notes


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None))
    client = TestClient(app)
    client.session = app.state.sessions.get("default")
    return client


def test_a_scripted_hurt_reaches_the_character_page_and_the_status_table(api):
    chat(api, "begin")
    name = api.session.state.party_names[0]
    chat(api, f"hurt {name} 5")
    assert api.get(f"/characters/{name}").json()["hp"] == "7/12"
    rows = api.get("/status").json()["table"]["rows"]
    assert any(r[0] == name and r[1] == "7/12" for r in rows)
    chat(api, f"heal {name} 99")
    assert api.get("/characters").json()["characters"][0]["hp"] == "12/12"
