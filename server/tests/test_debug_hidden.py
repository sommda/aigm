"""The debug-only hidden view of the world (docs/COMPENDIUM.md 11)."""

from tests.test_compendium import SECRETS, build, ids, state
from tests.test_debug_context import make


def seed(app):
    world = build()
    session = app.state.sessions.get("default")
    session.state = state(world)
    return world, ids(world)


def test_a_normal_server_has_no_hidden_routes(tmp_path):
    app, client = make(tmp_path)
    world, by_name = seed(app)
    assert client.get("/debug/hidden").status_code == 404
    assert client.get(f"/debug/hidden/{by_name['Wren']}").status_code == 404


def test_the_list_has_every_entity_with_hidden_or_hinted_facts_of_any_kind(tmp_path):
    app, client = make(tmp_path, debug=True)
    world, by_name = seed(app)
    body = client.get("/debug/hidden").json()
    names = [e["name"] for e in body["entries"]]
    # not the Thornwood or Ashby Vale: they only have known facts
    assert names == ["Captain Vael", "Harrow Mine", "Hidden Vault", "The Pale Omen", "Thorn Guild", "Wren"]
    assert body["count"] == len(names)
    kinds = {e["name"]: e["kind"] for e in body["entries"]}
    assert kinds["Wren"] == "npc" and kinds["Thorn Guild"] == "faction" and kinds["The Pale Omen"] == "concept"
    rows = {e["name"]: e for e in body["entries"]}
    assert rows["Hidden Vault"]["discovered"] is False and rows["Harrow Mine"]["discovered"] is True
    assert rows["Harrow Mine"]["hidden_count"] == 1 and rows["Harrow Mine"]["hinted_count"] == 0
    assert rows["Thorn Guild"]["hidden_count"] == 0 and rows["Thorn Guild"]["hinted_count"] == 1
    assert rows["Harrow Mine"]["motive_count"] == 0


def test_the_list_can_be_filtered_by_name_or_alias(tmp_path):
    app, client = make(tmp_path, debug=True)
    seed(app)
    assert [e["name"] for e in client.get("/debug/hidden", params={"q": "wren tallow"}).json()["entries"]] == ["Wren"]
    assert client.get("/debug/hidden", params={"q": "nobody"}).json()["entries"] == []


def test_the_detail_lists_hidden_and_hinted_facts_with_their_disclosure(tmp_path):
    app, client = make(tmp_path, debug=True)
    world, by_name = seed(app)
    mine = client.get(f"/debug/hidden/{by_name['Harrow Mine']}").json()
    assert [(f["disclosure"], f["aspect"]) for f in mine["facts"]] == [("hidden", "secret")]
    assert "smugglers" in mine["facts"][0]["text"] and mine["motives"] == []
    guild = client.get(f"/debug/hidden/{by_name['Thorn Guild']}").json()
    assert [f["disclosure"] for f in guild["facts"]] == ["hinted"]
    assert {e["name"] for e in guild["facts"][0]["about"]} == {"Thorn Guild", "Captain Vael"}
    wren = client.get(f"/debug/hidden/{by_name['Wren']}").json()
    assert "true name Mara" in wren["aliases"]  # nothing is filtered in the debug view
    assert any("Mara" in f["text"] for f in wren["facts"])


def test_known_and_superseded_facts_are_not_in_the_hidden_view(tmp_path):
    app, client = make(tmp_path, debug=True)
    world, by_name = seed(app)
    detail = client.get(f"/debug/hidden/{by_name['Harrow Mine']}").json()
    assert all("abandoned" not in f["text"] and "deep in the Thornwood" not in f["text"] for f in detail["facts"])
    secret = next(f for f in world.facts.values() if f.text.startswith("SECRET: the mine"))
    secret.status = "superseded"
    assert client.get(f"/debug/hidden/{by_name['Harrow Mine']}").status_code == 404
    assert by_name["Harrow Mine"] not in [e["id"] for e in client.get("/debug/hidden").json()["entries"]]


def test_an_entity_without_hidden_facts_or_an_unknown_id_is_not_found(tmp_path):
    app, client = make(tmp_path, debug=True)
    world, by_name = seed(app)
    assert client.get(f"/debug/hidden/{by_name['Thornwood']}").status_code == 404
    assert client.get("/debug/hidden/e999").status_code == 404
    assert client.get("/debug/hidden/nope").status_code == 422


def test_the_compendium_still_hides_everything_on_a_debug_server(tmp_path):
    app, client = make(tmp_path, debug=True)
    seed(app)
    text = client.get("/compendium/locations").text + client.get("/compendium/characters").text
    assert not any(secret in text for secret in SECRETS)
