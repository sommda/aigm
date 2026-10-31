"""The compendium (docs/COMPENDIUM.md): what the player may see, what is new, and the API."""

import json

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.compendium import Compendium, detail, entries, summary
from aigm.config import Settings
from aigm.errors import CorruptSave
from aigm.session.state import GameState, Phase
from aigm.world import World
from tests.conftest import chat

SECRETS = ("SECRET", "Vael", "smugglers", "Hidden Vault", "true name")


def build() -> World:
    """A world with known, hidden, hinted and superseded facts and an undiscovered entity."""
    w = World()
    vale = w.add_entity("Ashby Vale", "location")
    wood = w.add_entity("Thornwood", "location", parent=vale.id)
    mine = w.add_entity("Harrow Mine", "location", aliases=["the old mine", "Old Dread"], parent=wood.id)
    vault = w.add_entity("Hidden Vault", "location", parent=mine.id)
    wren = w.add_entity("Wren", "npc", aliases=["Wren Tallow", "true name Mara"])
    vael = w.add_entity("Captain Vael", "npc")
    guild = w.add_entity("Thorn Guild", "faction")
    omen = w.add_entity("The Pale Omen", "concept")
    kw = {"source": "seed", "turn": 0}
    w.add_fact("Ashby Vale is a farming valley along the old toll road.", [vale.id], aspect="history", disclosure="known", **kw)
    w.add_fact("The Thornwood is a dark forest east of Ashby.", [wood.id, vale.id], aspect="approach", disclosure="known", **kw)
    w.add_fact("Wren runs the common room of the Rusty Flagon.", [wren.id], aspect="role", disclosure="known", **kw)
    w.add_fact("The mine lies deep in the Thornwood, and locals call it the old mine.", [mine.id, wood.id],
               aspect="approach", disclosure="known", source="play", turn=3)
    w.add_fact("SECRET: the mine's lower gallery joins the smugglers' cellar.", [mine.id], aspect="secret")
    w.add_fact("SECRET: Wren's true name is Mara and she serves Captain Vael.", [wren.id, vael.id], aspect="knowledge")
    w.add_fact("SECRET: the Hidden Vault holds the Pale Omen.", [vault.id, omen.id], aspect="secret")
    w.add_fact("Someone whispers about a debt owed to Vael.", [guild.id, vael.id], aspect="goals", disclosure="hinted")
    return w


def state(world: World | None = None) -> GameState:
    return GameState(Phase.ADVENTURE, {"party": [], "level": 1}, world or build())


def ids(world: World) -> dict[str, str]:
    return {e.name: e.id for e in world.entities.values()}


def sweep(value, path=""):
    """Every string in a response, to look for leaks anywhere in it."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from sweep(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from sweep(v, f"{path}[{i}]")


# ---- the filter ------------------------------------------------------------------------------


def test_only_discovered_entities_are_listed():
    w = build()
    names = {e["name"] for c in ("locations", "characters", "other") for e in entries(w, Compendium(), c)}
    assert names == {"Ashby Vale", "Thornwood", "Harrow Mine", "Wren"}


def test_nothing_hidden_appears_in_any_response():
    w = build()
    comp = Compendium()
    out = [summary(w, comp)]
    for cat in ("locations", "characters", "other"):
        for sort in ("name", "recent", "tree"):
            out.append(entries(w, comp, cat, sort=sort))
    for eid in w.entities:
        out.append(detail(w, comp, eid))
    for path, text in sweep(out):
        for secret in SECRETS:
            assert secret not in text, (path, text)


def test_a_fact_that_becomes_known_appears_and_the_entity_with_it():
    w = build()
    ids_ = ids(w)
    secret = next(f for f in w.facts.values() if f.text.startswith("SECRET: the Hidden Vault"))
    w.reveal(secret.id, turn=9)
    d = detail(w, Compendium(), ids_["Hidden Vault"])
    assert d["facts"][0]["text"] == secret.text
    assert d["parent"]["name"] == "Harrow Mine"
    assert detail(w, Compendium(), ids_["The Pale Omen"])["facts"][0]["text"] == secret.text


def test_an_undiscovered_entity_looks_like_one_that_does_not_exist():
    w = build()
    comp = Compendium()
    assert detail(w, comp, ids(w)["Captain Vael"]) is None
    assert detail(w, comp, "e999") is None


def test_aliases_are_shown_only_once_they_appear_in_a_known_fact():
    w = build()
    d = detail(w, Compendium(), ids(w)["Harrow Mine"])
    assert d["aliases"] == ["the old mine"]  # "Old Dread" was never spoken
    assert detail(w, Compendium(), ids(w)["Wren"])["aliases"] == []
    assert entries(w, Compendium(), "locations", q="dread") == []
    assert [r["name"] for r in entries(w, Compendium(), "locations", q="OLD MINE")] == ["Harrow Mine"]


def test_a_parent_the_player_does_not_know_is_not_shown():
    w = World()
    wood = w.add_entity("Thornwood", "location")
    mine = w.add_entity("Harrow Mine", "location", parent=wood.id)
    w.add_fact("The Thornwood hides a secret.", [wood.id], aspect="secret")
    w.add_fact("The mine is abandoned.", [mine.id], aspect="history", disclosure="known", turn=2)
    d = detail(w, Compendium(), mine.id)
    assert d["parent"] is None and d["path"] == []
    assert [r["parent"] for r in entries(w, Compendium(), "locations")] == [None]


def test_a_superseded_known_fact_is_replaced_by_the_new_one():
    w = build()
    ids_ = ids(w)
    old = next(f for f in w.facts.values() if f.text.startswith("Wren runs"))
    w.supersede(old.id, "Wren owns the Rusty Flagon outright.", allow_known=True, turn=5)
    texts = [f["text"] for f in detail(w, Compendium(), ids_["Wren"])["facts"]]
    assert texts == ["Wren owns the Rusty Flagon outright."]


def test_categories_group_the_kinds_and_carry_the_kind():
    w = build()
    ids_ = ids(w)
    for name, text in (("Thorn Guild", "The Thorn Guild controls the toll road."), ("The Pale Omen", "The Pale Omen is a legend.")):
        w.add_fact(text, [ids_[name]], disclosure="known", source="play", turn=4)
    other = entries(w, Compendium(), "other")
    assert {(r["name"], r["kind"]) for r in other} == {("Thorn Guild", "faction"), ("The Pale Omen", "concept")}


def test_facts_read_in_checklist_order_subject_facts_first():
    w = build()
    ids_ = ids(w)
    w.add_fact("Wren has a burn scar on one hand.", [ids_["Wren"]], aspect="appearance", disclosure="known", turn=6)
    w.add_fact("Wren is feared by the Thorn Guild.", [ids_["Thorn Guild"], ids_["Wren"]], disclosure="known", turn=6)
    facts = detail(w, Compendium(), ids_["Wren"])["facts"]
    assert [f["label"] for f in facts] == ["Role", "Appearance", None]
    assert facts[-1]["text"] == "Wren is feared by the Thorn Guild."
    assert [r["name"] for r in detail(w, Compendium(), ids_["Wren"])["related"]] == ["Thorn Guild"]


def test_the_tree_puts_parents_first_and_the_orphan_of_an_unknown_parent_is_a_root():
    w = build()
    tree = entries(w, Compendium(), "locations", sort="tree")
    assert [(r["name"], r["depth"]) for r in tree] == [("Ashby Vale", 0), ("Thornwood", 1), ("Harrow Mine", 2)]
    filtered = entries(w, Compendium(), "locations", q="mine", sort="tree")
    assert [(r["name"], r["depth"]) for r in filtered] == [("Harrow Mine", 0)]


def test_long_summaries_are_cut_on_a_word():
    w = World()
    e = w.add_entity("Wren", "npc")
    w.add_fact("Wren " + "talks about the weather and the roads " * 8, [e.id], aspect="role", disclosure="known", turn=1)
    summary_ = entries(w, Compendium(), "characters")[0]["summary"]
    assert summary_.endswith("…") and len(summary_) <= 141


# ---- what is new -----------------------------------------------------------------------------


def test_what_the_player_set_up_in_session_zero_is_never_new():
    w = build()
    rows = {r["name"]: r["status"] for r in entries(w, Compendium(), "locations")}
    assert rows["Ashby Vale"] is None
    assert all(r["status"] is None for r in entries(w, Compendium(), "characters"))


def test_new_updated_and_seen():
    w = build()
    ids_ = ids(w)
    comp = Compendium()
    rows = {r["name"]: r for r in entries(w, comp, "locations")}
    assert rows["Harrow Mine"]["status"] == "new"
    assert rows["Thornwood"]["status"] == "updated"  # the new fact about the mine mentions it
    assert rows["Ashby Vale"]["status"] is None
    w.add_fact("Wren hums when she counts coin.", [ids_["Wren"]], aspect="manner", disclosure="known", turn=7)
    wren = {r["name"]: r for r in entries(w, comp, "characters")}["Wren"]
    assert wren["status"] == "updated" and wren["unseen_count"] == 1
    assert [f["new"] for f in detail(w, comp, ids_["Wren"])["facts"]] == [False, True]
    comp.mark_seen(w, [ids_["Wren"]])
    assert entries(w, comp, "characters")[0]["status"] is None
    s = summary(w, comp)
    assert (s["new"], s["updated"]) == (1, 1)
    comp.mark_all(w)
    assert entries(w, comp, "locations", status="unseen") == []
    assert (summary(w, comp)["new"], summary(w, comp)["updated"]) == (0, 0)


def test_a_reveal_makes_an_entity_new_and_marks_never_go_down():
    w = build()
    ids_ = ids(w)
    comp = Compendium()
    comp.mark_all(w)
    before = comp.all_through
    secret = next(f for f in w.facts.values() if f.text.startswith("SECRET: the Hidden Vault"))
    w.reveal(secret.id, turn=11)
    assert detail(w, comp, ids_["Hidden Vault"])["status"] == "new"
    comp.mark_seen(w, [ids_["Hidden Vault"], "e999", ids_["Captain Vael"]])  # unknown and hidden ids are ignored
    assert detail(w, comp, ids_["Hidden Vault"])["status"] is None
    assert "e999" not in comp.seen and ids_["Captain Vael"] not in comp.seen
    comp.mark_all(World())
    assert comp.all_through >= before


def test_the_reading_state_validates_and_round_trips():
    comp = Compendium(4, {"e001": 7})
    assert Compendium.from_dict(comp.to_dict()) == comp
    assert Compendium.from_dict(None) == Compendium()
    for bad in ([], {"all_through": -1}, {"seen": {"e1": "x"}}, {"all_through": True}):
        with pytest.raises(CorruptSave):
            Compendium.from_dict(bad)


def test_learned_numbers_survive_a_save_and_copy():
    w = build()
    again = World.from_dict(json.loads(json.dumps(w.to_dict())))
    assert again == w and again.learn_seq == w.learn_seq == 1
    assert [f.learned_seq for f in again.facts.values()].count(1) == 1
    state_ = state(w)
    state_.compendium.mark_all(w)
    assert GameState.from_dict(json.loads(json.dumps(state_.to_dict()))).compendium == state_.compendium
    copied = state_.copy()
    copied.compendium.seen["e001"] = 5
    assert "e001" not in state_.compendium.seen


def test_an_old_save_opens_with_nothing_new():
    data = build().to_dict()
    data.pop("learn_seq")
    for f in data["facts"]:
        f.pop("learned_seq")
    w = World.from_dict(data)
    assert summary(w, Compendium())["new"] == 0 and summary(w, Compendium())["updated"] == 0
    old = GameState(Phase.ADVENTURE, {"party": []}, w).to_dict()
    old.pop("compendium")
    assert GameState.from_dict(old).compendium == Compendium()


# ---- the API ---------------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None))
    client = TestClient(app)
    session = app.state.sessions.get("default")
    session.state = state()
    client.session = session
    return client


def test_the_overview_counts_each_category(api):
    body = api.get("/compendium").json()
    assert body["phase"] == "adventure"
    assert {c["id"]: (c["count"], c["new"]) for c in body["categories"]} == {
        "locations": (3, 1), "characters": (1, 0), "items": (0, 0), "other": (0, 0),
    }
    assert (body["new"], body["updated"]) == (1, 1)


def test_session_zero_has_an_empty_compendium(client):
    body = client.get("/compendium").json()
    assert body["new"] == 0 and all(c["count"] == 0 for c in body["categories"])
    assert client.get("/compendium/locations").json()["entries"] == []


def test_lists_filter_and_sort(api):
    body = api.get("/compendium/locations", params={"sort": "tree"}).json()
    assert body["title"] == "Locations" and body["count"] == 3
    assert [e["name"] for e in body["entries"]] == ["Ashby Vale", "Thornwood", "Harrow Mine"]
    assert [e["name"] for e in api.get("/compendium/locations", params={"status": "new"}).json()["entries"]] == [
        "Harrow Mine"
    ]
    assert api.get("/compendium/locations", params={"q": "thorn"}).json()["count"] == 1
    assert api.get("/compendium/characters", params={"sort": "tree"}).status_code == 200  # falls back to name


def test_bad_requests(api):
    assert api.get("/compendium/dragons").status_code == 404
    assert api.get("/compendium/locations", params={"status": "bogus"}).status_code == 422
    assert api.get("/compendium/locations", params={"sort": "bogus"}).status_code == 422
    assert api.get("/compendium/entities/not-an-id").status_code == 422
    for body in ({}, {"all": False}, {"entities": ["e001"], "all": True}, {"entities": ["bad id!"]}):
        assert api.post("/compendium/seen", json=body).status_code == 422, body


def test_a_hidden_entity_gets_the_same_404_as_a_missing_one(api):
    vael = ids(api.session.state.world)["Captain Vael"]
    hidden, missing = api.get(f"/compendium/entities/{vael}"), api.get("/compendium/entities/e999")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json()["error"]["message"].replace(vael, "ID") == missing.json()["error"]["message"].replace("e999", "ID")


def test_nothing_hidden_leaves_through_the_api(api):
    world = api.session.state.world
    bodies = [api.get("/compendium").text, api.get("/chat/history").text]
    for cat in ("locations", "characters", "other"):
        bodies.append(api.get(f"/compendium/{cat}").text)
    for eid in world.entities:
        bodies.append(api.get(f"/compendium/entities/{eid}").text)
    for text in bodies:
        for secret in SECRETS:
            assert secret not in text


def test_marking_seen_returns_the_new_summary(api):
    mine = ids(api.session.state.world)["Harrow Mine"]
    body = api.post("/compendium/seen", json={"entities": [mine, "e999"]}).json()
    assert (body["new"], body["updated"]) == (0, 1)  # the mine is read; the Thornwood page still has news
    assert api.get(f"/compendium/entities/{mine}").json()["status"] is None
    assert api.session.state.compendium.seen == {mine: api.session.state.world.learn_seq}


def test_marking_all_seen(api):
    assert api.post("/compendium/seen", json={"all": True}).json()["new"] == 0


def test_a_mark_sent_during_a_turn_waits_for_the_turn_to_end(api):
    session = api.session
    mine = ids(session.state.world)["Harrow Mine"]
    session.busy = True
    body = api.post("/compendium/seen", json={"entities": [mine]}).json()
    assert body["new"] == 0 and session.pending_seen == [[mine]]  # shown as seen at once ...
    assert session.state.compendium.seen == {}  # ... but not written into the state a turn will replace
    session.busy = False
    session.drain_pending()
    assert session.state.compendium.seen == {mine: 1} and session.pending_seen == []
    session.reset_world_work()
    assert session.pending_seen == []


def test_message_end_history_and_health_report_the_unseen_counts(api):
    assert api.get("/health").json()["compendium"] is True
    assert api.get("/chat/history").json()["compendium"] == {"new": 1, "updated": 1}
    from tests.conftest import parse_sse

    text = api.post("/chat", json={"message": "hi"}).text
    end = [d for n, d in parse_sse(text) if n == "message_end"][0]
    assert end["compendium"] == {"new": 1, "updated": 1}


def test_restoring_a_save_reports_the_counts(api):
    api.put("/history/c/save")
    assert api.post("/history/c/restore").json()["compendium"] == {"new": 1, "updated": 1}


def test_entering_the_adventure_in_test_mode_builds_a_compendium(client):
    chat(client, "begin")
    body = client.get("/compendium").json()
    assert sum(c["count"] for c in body["categories"]) > 0


def test_a_person_who_has_been_met_is_listed_with_only_their_look():
    from aigm.looks import Look

    w = build()
    tam = w.add_entity("Tam Orrin", "npc")
    tam.look = Look("A freckled boy.", "Tam is a freckled boy of ten with a gap in his teeth. " * 3, {})
    comp = Compendium()
    assert "Tam Orrin" not in [e["name"] for e in entries(w, comp, "characters")]  # not met: no entry
    assert detail(w, comp, tam.id) is None
    w.set_scene(None, [tam.id])  # now the player can see him
    row = next(e for e in entries(w, comp, "characters") if e["name"] == "Tam Orrin")
    assert row["summary"] == "A freckled boy." and row["fact_count"] == 0 and row["status"] is None
    page = detail(w, comp, tam.id)
    assert page["facts"] == [] and page["look"] == {"summary": tam.look.summary, "description": tam.look.description}
    assert sorted(page["look"]) == ["description", "summary"]  # nothing internal
    assert summary(w, comp)["categories"][1]["count"] == 2  # Wren and Tam
    assert entries(w, comp, "characters", sort="recent")


def test_a_met_person_without_a_look_yet_stays_out_and_other_kinds_never_show_a_look_alone():
    w = build()
    tam = w.add_entity("Tam Orrin", "npc")
    w.set_scene(None, [tam.id])
    assert detail(w, Compendium(), tam.id) is None  # discovered, but nothing to show yet
    hidden = w.add_entity("Unmet", "npc")
    assert not hidden.discovered  # a hidden person in no scene is not shown, whatever their look
