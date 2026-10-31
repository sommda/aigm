"""Key items (docs/KEY_ITEMS.md): the holding record, the GM's tools, the briefing and the save."""

import pytest

from aigm.compendium import _visible, known_facts
from aigm.errors import CorruptSave
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch
from aigm.world import CURATOR_KINDS, KINDS, World, WorldError
from aigm.world.briefing import build_briefing
from aigm.world.ops import SetHolding, apply_ops
from aigm.world.passes import frontier


def make() -> tuple[World, str, str]:
    w = World()
    town = w.add_entity("Ashby", "location")
    ledger = w.add_entity("Steward's Ledger", "item", aliases=["the ledger"])
    w.add_fact("The ledger is a thick green-bound book with brass corners.", [ledger.id], aspect="appearance")
    w.add_fact("The ledger proves the steward sold the grain.", [ledger.id], aspect="purpose")
    w.add_fact("Page nine of the ledger is a forgery.", [ledger.id], aspect="secret")
    w.add_fact("The ledger sits in the steward's vault.", [ledger.id, town.id], aspect="whereabouts")
    w.set_scene(town.id, [])
    return w, town.id, ledger.id


@pytest.fixture
def state():
    s = GameState(Phase.ADVENTURE, {"setting": "x"})
    s.world, _, _ = make()
    s.turn = 5
    return s


def facts(w: World, eid: str, disclosure: str = "known") -> list[str]:
    return [f.text for f in w.facts_about(eid) if f.subject == eid and f.disclosure == disclosure]


# ---- the record ---------------------------------------------------------------------------


def test_items_are_a_kind_the_curator_cannot_make():
    assert "item" in KINDS and "item" not in CURATOR_KINDS


def test_a_new_item_is_unfound_and_not_discovered():
    w, _, item = make()
    ent = w.entities[item]
    assert ent.holding.status == "unfound" and not ent.holding.history
    assert not ent.discovered and not _visible(w, item)


def test_a_known_fact_about_an_unfound_item_does_not_show_it():
    w, town, item = make()
    w.add_fact("Villagers say the steward keeps a ledger.", [town, item], disclosure="known")
    assert not w.entities[item].discovered and not _visible(w, item)


def test_learned_makes_it_known_with_a_custody_fact_and_reveals_nothing_else():
    w, _, item = make()
    assert w.set_holding(item, "learned", "Heard of from the harbor master.", turn=3)
    ent = w.entities[item]
    assert ent.holding.status == "known" and ent.holding.since == 3 and ent.discovered and _visible(w, item)
    assert "The party has heard of Steward's Ledger. Heard of from the harbor master." in facts(w, item)
    assert not any("thick green" in t for t in facts(w, item))  # appearance waits for the party to hold it


def test_first_acquisition_reveals_appearance_and_purpose_only():
    w, _, item = make()
    w.set_holding(item, "learned", turn=2)
    assert w.set_holding(item, "acquired", "Taken from the steward's desk.", turn=4)
    known = facts(w, item)
    assert any("thick green-bound" in t for t in known) and any("proves the steward" in t for t in known)
    assert not any("forgery" in t or "vault" in t for t in known)
    assert facts(w, item, "hidden") and w.entities[item].holding.status == "held"


def test_custody_fact_is_replaced_not_piled_up():
    w, _, item = make()
    for event in ("learned", "acquired", "used"):
        w.set_holding(item, event, turn=1)
    custody = [f for f in w.facts_about(item) if f.aspect == "custody"]
    assert len(custody) == 1 and "used up" in custody[0].text


def test_history_and_reacquisition():
    w, _, item = make()
    w.set_holding(item, "acquired", "Found.", turn=2)
    w.set_holding(item, "lost", "Stolen by the harbor guard.", turn=5)
    w.set_holding(item, "acquired", "Taken back.", turn=9)
    hold = w.entities[item].holding
    assert hold.status == "held" and hold.since == 9 and hold.acquired
    assert [(h.turn, h.status, h.note) for h in hold.history] == [
        (2, "held", "Found."), (5, "lost", "Stolen by the harbor guard."), (9, "held", "Taken back."),
    ]
    assert "again" in next(f.text for f in w.facts_about(item) if f.aspect == "custody")


def test_a_repeated_event_changes_nothing():
    w, _, item = make()
    w.set_holding(item, "acquired", turn=2)
    version = w.version
    assert w.set_holding(item, "acquired", turn=3) is False
    assert w.version == version and len(w.entities[item].holding.history) == 1


@pytest.mark.parametrize(
    "steps, event",
    [((), "used"), ((), "lost"), (("acquired",), "learned"), (("learned",), "used"), (("acquired", "used"), "lost")],
)
def test_refused_changes(steps, event):
    w, _, item = make()
    for step in steps:
        w.set_holding(item, step)
    with pytest.raises(WorldError):
        w.set_holding(item, event)


def test_only_items_have_a_holding_and_the_note_is_short():
    w, town, item = make()
    with pytest.raises(WorldError, match="not a key item"):
        w.set_holding(town, "acquired")
    with pytest.raises(WorldError, match="at most"):
        w.set_holding(item, "acquired", "word " * 40)
    with pytest.raises(WorldError, match="event must be"):
        w.set_holding(item, "stolen")


def test_the_op_applies_by_name_and_skips_nonsense():
    w, _, item = make()
    result = apply_ops(w, [SetHolding("the ledger", "acquired", turn=1), SetHolding("Nobody", "lost")])
    assert w.entities[item].holding.status == "held" and len(result.skipped) == 1


def test_the_curator_never_fleshes_out_items():
    w, _, item = make()
    w.set_holding(item, "acquired", turn=1)
    assert all(e.kind != "item" for e, _, _ in frontier(w, 20))


# ---- saving -------------------------------------------------------------------------------


def test_round_trip():
    w, _, item = make()
    w.set_holding(item, "acquired", "Found.", turn=2)
    back = World.from_dict(w.to_dict())
    assert back.entities[item].holding.to_dict() == w.entities[item].holding.to_dict()
    assert back.entities[item].discovered


def test_an_old_save_with_no_holding_loads_and_an_item_gets_one():
    w, _, item = make()
    data = w.to_dict()
    for e in data["entities"]:
        e.pop("holding", None)
    assert World.from_dict(data).entities[item].holding.status == "unfound"


def test_a_holding_on_something_else_is_corrupt():
    w, town, _ = make()
    data = w.to_dict()
    next(e for e in data["entities"] if e["id"] == town)["holding"] = {"status": "held", "since": 0, "history": []}
    with pytest.raises(CorruptSave):
        World.from_dict(data)


# ---- the tools ----------------------------------------------------------------------------


def test_establish_makes_an_item_with_a_hidden_appearance_fact(state):
    out = dispatch(
        "establish", "t", {"entities": [{"name": "Sluice Key", "kind": "item", "look_notes": "a heavy brass key"}]}, state
    )
    assert not out.is_error, out.content
    key = state.world.find("Sluice Key")
    assert key.kind == "item" and key.holding.status == "unfound" and not _visible(state.world, key.id)
    assert facts(state.world, key.id, "hidden") == ["Sluice Key is a heavy brass key."]


@pytest.mark.parametrize("notes", [None, "", "brass", "word " * 31])
def test_establish_requires_good_look_notes_for_an_item(state, notes):
    entity = {"name": "Sluice Key", "kind": "item"}
    if notes is not None:
        entity["look_notes"] = notes
    out = dispatch("establish", "t", {"entities": [entity]}, state)
    assert out.is_error and state.world.find("Sluice Key") is None


def test_establish_allows_two_new_items_a_call(state):
    items = [{"name": n, "kind": "item", "look_notes": "a small thing"} for n in ("Key One", "Key Two", "Key Three")]
    assert dispatch("establish", "t", {"entities": items}, state).is_error
    assert not dispatch("establish", "t", {"entities": items[:2]}, state).is_error


def test_key_item_tool_moves_an_item_and_reports(state):
    out = dispatch("key_item", "t", {"events": [{"name": "the ledger", "event": "acquired", "note": "Found."}]}, state)
    assert not out.is_error and "now in the party's hands" in out.content
    ent = state.world.find("Steward's Ledger")
    assert ent.holding.status == "held" and ent.holding.history[0].turn == 5


def test_key_item_tool_is_all_or_nothing_and_explains(state):
    events = [
        {"name": "Steward's Ledger", "event": "acquired"},
        {"name": "Ashby", "event": "acquired"},
        {"name": "Missing", "event": "lost"},
        {"name": "Steward's Ledger", "event": "used"},
    ]
    out = dispatch("key_item", "t", {"events": events[:3]}, state)
    assert out.is_error and "not a key item" in out.content and "establish" in out.content
    assert state.world.find("Steward's Ledger").holding.status == "unfound"
    bad = dispatch("key_item", "t", {"events": [{"name": "Steward's Ledger", "event": "used"}]}, state)
    assert bad.is_error and "cannot be used" in bad.content
    assert dispatch("key_item", "t", {"events": []}, state).is_error


# ---- the briefing -------------------------------------------------------------------------


def test_the_briefing_lists_items_by_standing():
    w, _, item = make()
    text = build_briefing(w)
    assert "not yet in play" in text and "- Steward's Ledger" in text and "Key items the party has" not in text
    w.set_holding(item, "learned")
    assert "looking for" in build_briefing(w) and "sluice" not in build_briefing(w).lower()
    w.set_holding(item, "acquired")
    text = build_briefing(w)
    assert "Key items the party has:\n- Steward's Ledger: The ledger is a thick green-bound book" in text
    w.set_holding(item, "lost")
    assert "Key items the party has" not in build_briefing(w)


def test_a_dump_shows_the_holding():
    from aigm.world.dump import dump_world

    w, _, item = make()
    w.set_holding(item, "acquired", "Found.", turn=2)
    entry = next(e for e in dump_world(w)["entities"] if e["id"] == item)
    assert entry["holding"]["status"] == "held"


# ---- the compendium (docs/KEY_ITEMS.md 4.3, 9) ---------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from aigm.app import create_app  # noqa: E402
from aigm.compendium import Compendium, detail, entries, summary  # noqa: E402
from aigm.config import Settings  # noqa: E402


def shelf() -> tuple[World, dict[str, str]]:
    """A town, a person and four items: unfound, known, held and lost."""
    w = World()
    town = w.add_entity("Ashby", "location")
    wren = w.add_entity("Wren", "npc")
    w.add_fact("Ashby is a market town.", [town.id], aspect="overview", disclosure="known", source="seed")
    w.add_fact("Wren keeps the Flagon.", [wren.id], aspect="role", disclosure="known", source="seed")
    ids = {}
    for name in ("Hidden Chest Key", "Sluice Key", "Steward's Ledger", "Old Map"):
        item = w.add_entity(name, "item")
        ids[name] = item.id
        w.add_fact(f"{name} looks old and worn.", [item.id], aspect="appearance")
        w.add_fact(f"SECRET {name} is cursed.", [item.id], aspect="secret")
    w.add_fact("Wren says the Sluice Key hangs in the gatehouse.", [wren.id, ids["Sluice Key"]], disclosure="known")
    w.add_fact("Wren once owned the Hidden Chest Key.", [wren.id, ids["Hidden Chest Key"]], disclosure="known")
    w.add_fact("The Old Map shows Ashby.", [ids["Old Map"], town.id], aspect="contents", disclosure="hidden")
    w.set_holding(ids["Sluice Key"], "learned", turn=2)
    w.set_holding(ids["Steward's Ledger"], "acquired", "Found.", turn=3)
    w.set_holding(ids["Old Map"], "acquired", turn=1)
    w.set_holding(ids["Old Map"], "lost", "Stolen.", turn=4)
    ids["Ashby"], ids["Wren"] = town.id, wren.id
    return w, ids


def names(rows):
    return [r["name"] for r in rows]


def test_only_items_that_entered_play_are_listed_in_the_order_held_known_lost():
    w, _ = shelf()
    rows = entries(w, Compendium(), "items")
    assert names(rows) == ["Steward's Ledger", "Sluice Key", "Old Map"]
    assert [r["holding"] for r in rows] == ["held", "known", "lost"]
    assert [c["count"] for c in summary(w, Compendium())["categories"]] == [1, 1, 3, 0]


def test_the_unfound_item_leaks_nowhere():
    w, ids = shelf()
    comp = Compendium()
    key = ids["Hidden Chest Key"]
    assert detail(w, comp, key) is None
    assert entries(w, comp, "items", q="chest") == []
    for eid in (ids["Wren"], ids["Ashby"]):  # a known fact mentions it, but it is not related or a child
        page = detail(w, comp, eid)
        assert key not in {r["id"] for r in page["related"]}
    assert "Hidden Chest Key" not in str(entries(w, comp, "characters")) + str(entries(w, comp, "locations"))


def test_a_known_item_shows_facts_but_no_look_secret_or_picture_data():
    w, ids = shelf()
    page = detail(w, Compendium(), ids["Sluice Key"])
    assert page["holding"]["status"] == "known" and page["look"] is None
    text = [f["text"] for f in page["facts"]]
    assert "The party has heard of Sluice Key." in text and any("gatehouse" in t for t in text)
    assert not any("old and worn" in t or "SECRET" in t for t in text)  # appearance waits for the party to hold it


def test_a_held_item_shows_its_appearance_and_history_and_never_the_secret():
    w, ids = shelf()
    page = detail(w, Compendium(), ids["Steward's Ledger"])
    texts = [f["text"] for f in page["facts"]]
    assert any("old and worn" in t for t in texts) and not any("SECRET" in t for t in texts)
    assert page["holding"] == {"status": "held", "since": 3, "history": [{"turn": 3, "status": "held", "note": "Found."}]}
    lost = detail(w, Compendium(), ids["Old Map"])["holding"]
    assert lost["status"] == "lost" and [h["status"] for h in lost["history"]] == ["held", "lost"]


def test_a_summary_line_prefers_what_the_item_looks_like():
    w, ids = shelf()
    rows = {r["name"]: r["summary"] for r in entries(w, Compendium(), "items")}
    assert rows["Steward's Ledger"] == "Steward's Ledger looks old and worn."
    assert rows["Sluice Key"] == "Wren says the Sluice Key hangs in the gatehouse."


def test_each_change_of_holding_marks_the_entry_new_then_updated():
    w, ids = shelf()
    comp = Compendium()
    key = ids["Sluice Key"]
    row = next(r for r in entries(w, comp, "items") if r["id"] == key)
    assert row["status"] == "new"
    comp.mark_seen(w, [key])
    assert next(r for r in entries(w, comp, "items") if r["id"] == key)["status"] is None
    w.set_holding(key, "acquired", turn=9)
    assert next(r for r in entries(w, comp, "items") if r["id"] == key)["status"] == "updated"


def test_items_can_be_found_by_name_and_listed_over_http(tmp_path):
    app = create_app(Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None))
    client = TestClient(app)
    session = app.state.sessions.get("default")
    session.state = GameState(Phase.ADVENTURE, {"setting": "x"})
    session.state.world, ids = shelf()
    body = client.get("/compendium/items").json()
    assert body["title"] == "Key Items" and body["count"] == 3
    assert names(client.get("/compendium/items", params={"q": "sluice"}).json()["entries"]) == ["Sluice Key"]
    assert client.get(f"/compendium/entities/{ids['Hidden Chest Key']}").status_code == 404
    page = client.get(f"/compendium/entities/{ids['Steward\'s Ledger']}").json()
    assert page["holding"]["status"] == "held" and page["category"] == "items"
