import pytest

from aigm.errors import CorruptSave
from aigm.world import World, WorldError, WorldTime
from aigm.world.model import MAX_ENTITY_FACTS, MAX_FACT_WORDS
from aigm.world.text import normalize_name, tokens


@pytest.fixture
def w():
    world = World()
    region = world.add_entity("Thornwood", "location")
    town = world.add_entity("Ashby", "location", parent=region.id)
    mine = world.add_entity("Harrow Mine", "location", aliases=["the old mine", "Harrow"], parent=region.id)
    guild = world.add_entity("Thorn Guild", "faction")
    world.add_fact("Ashby is a market town on the edge of the Thornwood.", [town.id, region.id], aspect="layout")
    world.add_fact(
        "The Harrow Mine lies 3 miles east and 2 miles north of Ashby.", [mine.id, town.id], aspect="approach"
    )
    world.add_fact("The Thorn Guild controls the toll road between Ashby and the Thornwood.", [guild.id, town.id])
    return world


def ids(world):
    return {e.name: e.id for e in world.entities.values()}


# ---- text ---------------------------------------------------------------------------------


def test_normalize_name_ignores_case_punctuation_and_article():
    assert normalize_name("The Old Mine!") == normalize_name("old  mine") == "old mine"
    assert "the" not in tokens("The mine is in the woods") and "mine" in tokens("The mine")


# ---- entities -----------------------------------------------------------------------------


def test_entities_get_sequential_ids_and_are_found_by_name_or_alias(w):
    e = ids(w)
    assert e == {"Thornwood": "e001", "Ashby": "e002", "Harrow Mine": "e003", "Thorn Guild": "e004"}
    assert w.find("harrow").id == w.find("The Old Mine").id == "e003"
    assert w.resolve("e003").name == "Harrow Mine" and w.resolve("Ashby").id == "e002"
    assert w.find("nowhere") is None


def test_name_and_alias_collisions_are_rejected(w):
    with pytest.raises(WorldError, match="already used by 'Harrow Mine'"):
        w.add_entity("The Old Mine", "location")
    with pytest.raises(WorldError, match="already used"):
        w.add_entity("New Place", "location", aliases=["ashby"])
    with pytest.raises(WorldError, match="already used"):
        w.add_alias("e001", "Harrow")
    assert len(w.entities) == 4


def test_add_alias_is_idempotent_for_own_names(w):
    before = w.version
    w.add_alias("e003", "harrow mine")
    assert w.find("harrow mine").aliases == ["the old mine", "Harrow"] and w.version == before
    w.add_alias("e003", "the abandoned dig")
    assert w.find("abandoned dig").id == "e003"


def test_entity_validation(w):
    for kwargs, msg in [
        (dict(name="", kind="npc"), "name"),
        (dict(name="Wren", kind="monster"), "kind must be"),
        (dict(name="x" * 81, kind="npc"), "longer"),
        (dict(name="Wren", kind="npc", parent="e001"), "only locations"),
        (dict(name="Cellar", kind="location", parent="e999"), "unknown parent"),
        (dict(name="Cellar", kind="location", parent="e004"), "only locations"),
    ]:
        with pytest.raises(WorldError, match=msg):
            w.add_entity(**kwargs)
    assert len(w.entities) == 4


def test_containment_helpers(w):
    assert [c.name for c in w.children("e001")] == ["Ashby", "Harrow Mine"]
    cellar = w.add_entity("Smugglers' Cellar", "location", parent="e002")
    assert [p.name for p in w.parent_chain(cellar.id)] == ["Ashby", "Thornwood"]


# ---- facts --------------------------------------------------------------------------------


def test_fact_defaults_and_stamps(w):
    w.advance_time(5)
    f = w.add_fact("The Thorn Guild employs about forty toll collectors.", ["e004"], aspect="resources", turn=7)
    assert f.id == "f0004" and f.disclosure == "hidden" and f.status == "active"
    assert f.created_at == WorldTime(1, 13) and f.turn == 7 and f.subject == "e004"
    assert f.from_time is None and f.until_time is None and f.revealed_turn is None


@pytest.mark.parametrize(
    "kwargs,msg",
    [
        (dict(text=""), "empty"),
        (dict(text="Too short"), "full declarative"),
        (dict(text=" ".join(["word"] * (MAX_FACT_WORDS + 1))), "words"),
        (dict(text="The mine is deep.", disclosure="secret"), "disclosure"),
        (dict(text="The mine is deep.", source="dream"), "source"),
        (dict(text="The mine is deep.", about=[]), "at least one"),
        (dict(text="The mine is deep.", about=["e099"]), "unknown entity"),
        (dict(text="The mine is deep.", aspect="rooms"), "not valid for a location"),
        (dict(text="The mine is deep.", aspect="motivation"), "not valid for a location"),
        (dict(text="The mine is deep.", about=["e003", "e001", "e002", "e004", "e005"]), "at most"),
    ],
)
def test_bad_facts_are_rejected_and_change_nothing(w, kwargs, msg):
    w.add_entity("Fifth", "concept")
    kwargs = {"about": ["e003"], **kwargs}
    version, count = w.version, len(w.facts)
    with pytest.raises(WorldError, match=msg):
        w.add_fact(**kwargs)
    assert w.version == version and len(w.facts) == count


def test_duplicate_facts_are_rejected_ignoring_case_and_punctuation(w):
    with pytest.raises(WorldError, match="already recorded as fact f0002"):
        w.add_fact("the harrow mine lies 3 miles east, and 2 miles north of ASHBY", ["e003"])
    w.add_fact("The Harrow Mine lies 3 miles east and 2 miles north of Ashby.", ["e002"])  # other subject: fine


def test_per_entity_cap(w):
    for i in range(MAX_ENTITY_FACTS - 1):  # the guild already has one
        w.add_fact(f"The guild keeps ledger number {i} in a locked chest.", ["e004"])
    with pytest.raises(WorldError, match="already has"):
        w.add_fact("The guild owns a ship called the Gull.", ["e004"])
    # facts that merely mention the guild do not count against it
    w.add_fact("The mine pays a yearly toll to the Thorn Guild.", ["e003", "e004"])


def test_known_facts_stamp_discovery(w):
    assert not w.entity("e003").discovered
    f = w.add_fact("The Harrow Mine was abandoned forty years ago.", ["e003", "e002"], disclosure="known", turn=4)
    assert f.revealed_turn == 4 and w.entity("e003").discovered and w.entity("e002").discovered
    assert not w.entity("e004").discovered


def test_reveal(w):
    f = w.add_fact("The mine's lower gallery connects to a cellar under Ashby.", ["e003"], aspect="secret")
    assert w.reveal(f.id, turn=9) is True
    assert (f.disclosure, f.revealed_turn) == ("known", 9) and w.entity("e003").discovered
    assert w.reveal(f.id, turn=12) is False and f.revealed_turn == 9
    with pytest.raises(WorldError, match="unknown fact"):
        w.reveal("f9999", 1)


def test_supersede_keeps_the_trail_and_the_indexes_current(w):
    old = w.add_fact("The mine's shaft is flooded to the first gallery.", ["e003"], aspect="hazards")
    new = w.supersede(old.id, "The mine's shaft was drained last spring.", source="play", turn=20)
    assert old.status == "superseded" and old.superseded_by == new.id and new.status == "active"
    assert (new.about, new.aspect, new.disclosure, new.source) == (["e003"], "hazards", "hidden", "play")
    assert old not in w.facts_about("e003") and new in w.facts_about("e003")
    assert old in w.facts_about("e003", include_superseded=True)
    assert new in w.search("shaft drained") and old not in w.search("flooded gallery")
    w.add_fact("The mine's shaft is flooded to the first gallery.", ["e003"])  # text is free again
    with pytest.raises(WorldError, match="already superseded"):
        w.supersede(old.id, "The shaft is dry and solid.")


def test_known_facts_resist_supersession_unless_allowed(w):
    k = w.add_fact("The Harrow Mine was abandoned forty years ago.", ["e003"], disclosure="known")
    with pytest.raises(WorldError, match="known to the player"):
        w.supersede(k.id, "The Harrow Mine was abandoned last year.")
    assert k.active
    new = w.supersede(k.id, "The Harrow Mine was abandoned last year.", allow_known=True)
    assert new.disclosure == "known" and k.status == "superseded"


def test_failed_supersede_leaves_the_old_fact_alone(w):
    old = w.add_fact("The mine's shaft is flooded to the first gallery.", ["e003"])
    with pytest.raises(WorldError):
        w.supersede(old.id, "Nope")
    with pytest.raises(WorldError):
        w.supersede(old.id, "The mine is deep.", about=["e099"])
    assert old.active and old.superseded_by is None and old in w.search("flooded")


# ---- queries ------------------------------------------------------------------------------


def test_search_ranks_by_shared_words_then_recency(w):
    hits = w.search("toll road Ashby")
    assert hits[0].text.startswith("The Thorn Guild controls the toll road")
    assert w.search("zzz") == []
    assert len(w.search("Ashby", limit=1)) == 1


def test_mentioned_finds_entities_by_name_and_alias_in_order(w):
    text = "We head for the old mine, then back through Ashby."
    assert [e.name for e in w.mentioned(text)] == ["Harrow Mine", "Ashby"]
    assert w.mentioned("Harrowing tales of Ashbyville") == []


def test_graph_neighbors_and_distances(w):
    cellar = w.add_entity("Smugglers' Cellar", "location", parent="e002")
    w.add_fact("The Smugglers' Cellar is entered through a trapdoor in a chandlery.", [cellar.id])
    assert w.neighbors("e002") == {"e001", "e003", "e004", cellar.id}  # parent, via facts, child
    d = w.distances("e003")
    assert d["e003"] == 0 and d["e002"] == 1 and d["e001"] == 1 and d["e004"] == 2 and d[cellar.id] == 2
    assert w.distances("nope") == {}


def test_coverage_counts_only_active_subject_facts(w):
    assert w.coverage("e003") == {"approach"}
    assert w.coverage("e002") == {"layout"}  # the fact about the mine mentions Ashby but is not about it
    old = w.facts_about("e003")[0]
    w.supersede(old.id, "The Harrow Mine lies far north of Ashby.", aspect="history")
    assert w.coverage("e003") == {"history"}


# ---- scene and clock ----------------------------------------------------------------------


def test_scene_validation(w):
    w.set_scene("e003", ["e004", "e003", "e004"])
    assert (w.scene.location, w.scene.present) == ("e003", ["e004"])
    with pytest.raises(WorldError):
        w.set_scene("e004")  # a faction is not a location
    with pytest.raises(WorldError):
        w.set_scene("e003", ["e099"])
    assert w.scene.location == "e003"


def test_clock_only_moves_forward_in_whole_hours():
    w = World()
    assert w.time == WorldTime(1, 8)
    assert w.advance_time(20) == WorldTime(2, 4)
    assert w.advance_time(0) == WorldTime(2, 4) and w.advance_time(48) == WorldTime(4, 4)
    for bad in (-1, 1.5, True, "2"):
        with pytest.raises(WorldError):
            w.advance_time(bad)
    with pytest.raises(WorldError, match="cannot go back"):
        w.set_time(WorldTime(4, 3))
    assert w.set_time(WorldTime(5, 18)).total_hours == 4 * 24 + 18
    with pytest.raises(WorldError):
        WorldTime(0, 5)
    with pytest.raises(WorldError):
        WorldTime(1, 24)
    assert str(WorldTime(3, 9)) == "Day 3, 09:00"


def test_processed_through_is_monotonic():
    w = World()
    w.mark_processed(5)
    w.mark_processed(5)
    with pytest.raises(WorldError):
        w.mark_processed(4)
    assert w.processed_through == 5


def test_version_counts_changes(w):
    v = w.version
    w.advance_time(1)
    w.add_fact("Ashby has a stone bridge over the river Ash.", ["e002"])
    assert w.version == v + 2
    w.find("Ashby")
    w.search("bridge")
    assert w.version == v + 2


# ---- serialization ------------------------------------------------------------------------


def full_world(w):
    old = w.add_fact("The mine's shaft is flooded to the first gallery.", ["e003"], aspect="hazards")
    w.supersede(old.id, "The mine's shaft was drained last spring.", turn=3)
    w.add_fact("Ashby's mayor owns the only ferry.", ["e002"], disclosure="known", turn=2)
    w.set_scene("e002", ["e004"])
    w.advance_time(30)
    w.mark_processed(6)
    w.facts["f0004"].from_time = WorldTime(10, 0)  # reserved fields must survive a round trip
    w.facts["f0004"].until_time = WorldTime(12, 6)
    return w


def test_round_trip_preserves_everything_and_rebuilds_indexes(w):
    w = full_world(w)
    again = World.from_dict(w.to_dict())
    assert again == w and again.to_dict() == w.to_dict()
    assert again.find("old mine").id == "e003" and again.search("drained")[0].id == "f0005"
    assert again.facts["f0004"].until_time == WorldTime(12, 6)
    assert again.scene.location == "e002" and again.processed_through == 6 and again.time == w.time
    again.add_fact("Ashby holds a market every sixth day.", ["e002"])  # ids carry on
    assert again.facts["f0007"].created_at == w.time


def test_copy_is_independent(w):
    c = w.copy()
    c.add_fact("Ashby has a stone bridge over the river Ash.", ["e002"])
    c.add_entity("Wren", "npc")
    assert len(w.facts) == 3 and len(w.entities) == 4 and c != w
    assert w.find("Wren") is None and c.find("Wren") is not None


def test_empty_and_none():
    assert World.from_dict(None) == World() and World().is_empty
    assert World.from_dict(World().to_dict()).is_empty


def corrupt(w, mutate):
    data = full_world(w).to_dict()
    mutate(data)
    with pytest.raises(CorruptSave, match="world"):
        World.from_dict(data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(time={"day": 0, "hour": 1}),
        lambda d: d.update(processed_through=-1),
        lambda d: d.pop("facts"),
        lambda d: d["entities"][0].update(kind="monster"),
        lambda d: d["entities"].append(dict(d["entities"][0])),
        lambda d: d["entities"][1].update(parent="e099"),
        lambda d: d["entities"][0].update(parent="e002"),  # loop: e001 -> e002 -> e001
        lambda d: d["entities"][1].update(name="Thornwood"),
        lambda d: d["facts"][0].update(about=[]),
        lambda d: d["facts"][0].update(about=["e099"]),
        lambda d: d["facts"][0].update(disclosure="secret"),
        lambda d: d["facts"][0].update(text=""),
        lambda d: d["facts"][0].update(status="superseded"),
        lambda d: d["facts"][0].update(superseded_by="f0999", status="superseded"),
        lambda d: d["scene"].update(location="e099"),
        lambda d: d["next_id"].update(f=1),
        lambda d: d.update(entities="nope"),
    ],
)
def test_corrupt_worlds_are_rejected(w, mutate):
    corrupt(w, mutate)


def test_world_must_be_an_object():
    with pytest.raises(CorruptSave):
        World.from_dict([])
