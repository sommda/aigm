"""The status page (docs/STATUS.md): the place the party is in, who and what is there, and the route."""

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from aigm.session.state import GameState, Hero, Phase
from aigm.sheets import Section, Sheet
from aigm.status import build
from aigm.world import World
from tests.conftest import chat
from tests.test_compendium import sweep

SECRETS = ("SECRET", "Vael", "Hidden Cellar")


def harbor() -> tuple[GameState, dict[str, str]]:
    """Port Veyra, with the Docks as the scene, a known and an unknown neighbour, and a hidden overview elsewhere."""
    w = World()
    port = w.add_entity("Port Veyra", "location")
    docks = w.add_entity("The Docks", "location", parent=port.id)
    pier = w.add_entity("Pier Nine", "location", parent=docks.id)
    keep = w.add_entity("Customs House", "location", parent=port.id)
    cellar = w.add_entity("Hidden Cellar", "location", parent=docks.id)
    elian = w.add_entity("Elian", "npc")
    vael = w.add_entity("Captain Vael", "npc")
    known = {"disclosure": "known", "source": "seed", "turn": 0}
    w.add_fact("Port Veyra is a harbour city.", [port.id], aspect="history", **known)
    w.add_fact("Pier Nine is a long jetty at the end of the Docks.", [pier.id], aspect="approach", **known)
    w.add_fact("The Customs House stands up Dock Street from the Docks.", [keep.id, docks.id], aspect="approach", **known)
    w.add_fact("Elian is a merchant who needs a crate moved.", [elian.id], aspect="role", **known)
    w.add_fact("SECRET: Elian works for Captain Vael.", [elian.id, vael.id], aspect="knowledge")
    w.add_fact("SECRET: the Hidden Cellar holds contraband.", [cellar.id], aspect="secret")
    w.add_fact("Gulls wheel over wet planks and tarred rope.", [docks.id], aspect="overview")  # hidden until arrival
    w.add_fact("A barred cargo hatch.", [docks.id], aspect="items")
    w.add_fact("Dock Street climbs from the Customs House.", [port.id], aspect="overview")
    w.set_scene(docks.id, [elian.id, vael.id])
    ids = {e.name: e.id for e in w.entities.values()}
    state = GameState(Phase.ADVENTURE, {"party": [{"name": "Toby"}, {"name": "Galvin"}], "level": 1}, w)
    state.heroes["Toby"] = Hero(3, 900, {"Rogue": 3})
    return state, ids


def test_arriving_reveals_what_can_be_seen_there():
    state, ids = harbor()
    w = state.world
    keep = w.add_fact("Clerks bend over ledgers under a high, cold ceiling.", [ids["Customs House"]], aspect="overview")
    assert keep.disclosure == "hidden"  # the party is at the Docks
    w.set_scene(ids["Port Veyra"], [], 4)
    port = next(f for f in w.facts.values() if f.aspect == "overview" and f.about == [ids["Port Veyra"]])
    assert port.disclosure == "known" and port.revealed_turn == 4 and port.learned_seq > 0
    assert keep.disclosure == "hidden"
    w.set_scene(ids["Customs House"], [], 5)
    assert keep.disclosure == "known" and keep.revealed_turn == 5


def test_a_fact_written_about_the_place_the_party_is_in_is_known_at_once():
    state, ids = harbor()
    w = state.world
    f = w.add_fact("Rain drums on the awnings.", [ids["The Docks"]], aspect="overview", turn=7)
    assert f.disclosure == "known" and f.revealed_turn == 7
    other = w.add_fact("Quiet stone halls.", [ids["Customs House"]], aspect="overview")
    assert other.disclosure == "hidden"
    plain = w.add_fact("Fishermen mend nets here every morning.", [ids["The Docks"]], aspect="history")
    assert plain.disclosure == "hidden"  # only what is plainly seen on arrival


def test_the_status_names_and_describes_the_place():
    state, ids = harbor()
    state.world.set_scene(ids["The Docks"], [ids["Elian"]], 1)
    page = build(state)
    loc = page["location"]
    assert loc["name"] == "The Docks" and loc["id"] == ids["The Docks"]
    assert [p["name"] for p in loc["path"]] == ["Port Veyra"]
    assert loc["overview"] == "Gulls wheel over wet planks and tarred rope."
    assert loc["time"] == "Day 1, 08:00" and loc["period"] == "morning"
    assert page["items"] == ["A barred cargo hatch."]
    assert [e["name"] for e in page["here"]] == ["Elian"]
    assert page["here"][0]["summary"] == "Elian is a merchant who needs a crate moved."


def test_the_status_lists_places_inside_and_ways_out_that_the_party_knows():
    state, ids = harbor()
    page = build(state)
    assert [p["name"] for p in page["inside"]] == ["Pier Nine"]  # the Hidden Cellar is not discovered
    assert [x["name"] for x in page["exits"]] == ["Customs House"]
    assert page["exits"][0]["route"] == "The Customs House stands up Dock Street from the Docks."


def test_the_table_lists_the_party_and_who_is_present():
    state, ids = harbor()
    rows = build(state)["table"]["rows"]
    assert build(state)["table"]["columns"] == ["Name", "HP", "Conditions", "Who"]
    assert rows[0] == ["Toby", "-", "-", "Party, level 3"] and rows[1] == ["Galvin", "-", "-", "Party, level 1"]
    assert [r[0] for r in rows[2:]] == ["Elian"]  # Captain Vael is not discovered


def test_the_table_shows_hit_points_and_conditions_from_the_sheets():
    state, ids = harbor()
    state.sheets["Toby"] = Sheet("Human Rogue 3", 11, 15, ["prone"], [Section("Gear", ["Dagger"])])
    rows = build(state)["table"]["rows"]
    assert rows[0] == ["Toby", "11/15", "prone", "Party, level 3"]


def test_nothing_hidden_is_in_the_status():
    state, ids = harbor()
    for path, text in sweep(build(state)):
        assert not any(s in text for s in SECRETS), (path, text)


def test_a_game_with_no_scene_has_no_location():
    state, _ = harbor()
    state.world.scene.location = None
    page = build(state)
    assert page["location"] is None and page["here"] == [] and page["items"] == [] and page["exits"] == []
    assert [r[0] for r in page["table"]["rows"]] == ["Toby", "Galvin"]


# ---- the API --------------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None))
    client = TestClient(app)
    state, _ = harbor()
    app.state.sessions.get("default").state = state
    return client


def test_the_route_returns_the_page(api):
    body = api.get("/status").json()
    assert body["session_id"] == "default" and body["phase"] == "adventure"
    assert body["location"]["name"] == "The Docks" and body["table"]["rows"][0][0] == "Toby"


def test_nothing_hidden_leaves_through_the_route(api):
    for path, text in sweep(api.get("/status").json()):
        assert not any(s in text for s in SECRETS), (path, text)


def test_session_zero_has_no_status(client):
    resp = client.get("/status")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "conflict"


def test_entering_the_adventure_in_test_mode_gives_a_described_place(client):
    chat(client, "begin")
    body = client.get("/status").json()
    assert body["location"]["name"] == "Rusty Flagon" and body["location"]["overview"]
    assert body["items"] and body["table"]["rows"][0][3].startswith("Party") and body["table"]["rows"][0][1] == "12/12"
