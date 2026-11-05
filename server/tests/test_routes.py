"""Places and the ways between them: scales, routes, blocks, visited (docs/TIME.md 5.1 to 5.4, build step 3)."""

import pytest

from aigm.errors import CorruptSave
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch
from aigm.world import Block, World, WorldError
from aigm.world.briefing import build_briefing
from aigm.world.dump import dump_world


@pytest.fixture
def w():
    world = World()
    ashby = world.add_entity("Ashby", "location")
    flagon = world.add_entity("The Rusty Flagon", "location", parent=ashby.id)
    world.add_entity("The Cellar", "location", parent=flagon.id)
    world.add_entity("Harrow Mine", "location")
    world.add_entity("Wren", "npc")
    return world


def ids(w, *names):
    return [w.find(n).id for n in names]


def test_a_route_is_symmetric_and_found_from_either_end(w):
    a, m = ids(w, "Ashby", "Harrow Mine")
    route, new = w.set_route(a, m, 180, "along the toll road", source="seed")
    assert new and route.id == "r001" and route.other(a) == m and route.other(m) == a
    assert w.routes_of(a) == [route] == w.routes_of(m)
    assert w.find_route(m, a, "Along the  toll road") is route


def test_naming_a_route_again_updates_it_and_a_new_how_is_a_second_way(w):
    f, c = ids(w, "The Rusty Flagon", "The Cellar")
    main, _ = w.set_route(f, c, 4, "down the main stair")
    again, new = w.set_route(c, f, 3, "down the main stair")
    assert not new and again is main and main.minutes == 3
    servants, new = w.set_route(f, c, 9, "by the servants' passages")
    assert new and len(w.routes_of(f)) == 2 and servants.id != main.id


def test_a_block_is_set_kept_and_cleared(w):
    f, c = ids(w, "The Rusty Flagon", "The Cellar")
    r, _ = w.set_route(f, c, 4, "down the steps", block=Block("locked", "A locked oak door", "the steward's key"))
    assert r.block.kind == "locked"
    w.set_route(f, c, 5, "down the steps")  # block left out: kept
    assert r.block is not None and r.minutes == 5
    w.set_route(f, c, 5, "down the steps", block=None)
    assert r.block is None


@pytest.mark.parametrize("minutes", [0, True, 10**7])
def test_a_route_refuses_bad_minutes(w, minutes):
    a, m = ids(w, "Ashby", "Harrow Mine")
    with pytest.raises(WorldError, match="minutes"):
        w.set_route(a, m, minutes)


def test_a_route_joins_two_different_places_only(w):
    a, m, wren = ids(w, "Ashby", "Harrow Mine", "Wren")
    with pytest.raises(WorldError, match="different"):
        w.set_route(a, a, 5)
    with pytest.raises(WorldError, match="joins places"):
        w.set_route(a, wren, 5)
    with pytest.raises(WorldError, match="block kind"):
        w.set_route(a, m, 5, block=Block("magic", "A glowing seal"))
    with pytest.raises(WorldError, match="text"):
        w.set_route(a, m, 5, block=Block("locked", "x"))


def test_a_place_has_a_limited_number_of_routes(w):
    hub = w.find("Ashby").id
    for i in range(12):
        w.set_route(hub, w.add_entity(f"Farm {i}", "location").id, 60)
    with pytest.raises(WorldError, match="12 routes"):
        w.set_route(hub, w.add_entity("One more", "location").id, 60)


def test_scale_is_for_places_only(w):
    a = w.find("Ashby").id
    w.set_scale(a, "settlement")
    assert w.entities[a].scale == "settlement"
    with pytest.raises(WorldError, match="only a place"):
        w.set_scale(w.find("Wren").id, "room")
    with pytest.raises(WorldError, match="scale must be"):
        w.set_scale(a, "planet")


def test_arriving_marks_a_place_visited(w):
    f = w.find("The Rusty Flagon")
    assert not f.visited
    w.set_scene(f.id, [])
    assert w.find("The Rusty Flagon").visited and not w.find("Ashby").visited


def test_routes_scales_and_visited_round_trip_through_a_save(w):
    a, m = ids(w, "Ashby", "Harrow Mine")
    w.set_scale(a, "settlement")
    w.set_route(a, m, 180, "along the toll road", block=Block("collapsed", "A rockfall", "pickaxes"))
    w.set_scene(a, [])
    again = World.from_dict(w.to_dict())
    assert again.to_dict() == w.to_dict()
    assert again.routes_of(a)[0].block.opens_by == "pickaxes" and again.find("Ashby").scale == "settlement"
    assert again.find("Ashby").visited and not again.find("Harrow Mine").visited
    assert again.set_route(a, m, 200, "elsewhere")[0].id == "r002"  # the id counter carried on


def test_a_world_from_before_the_map_has_no_routes_and_counts_discovered_places_as_visited(w):
    w.find("Ashby").discovered = True
    data = w.to_dict()
    del data["routes"]
    for e in data["entities"]:
        del e["visited"], e["scale"]
    del data["next_id"]["r"]
    old = World.from_dict(data)
    assert old.routes == {} and old.find("Ashby").visited and not old.find("Harrow Mine").visited
    assert not old.find("Wren").visited


def test_a_save_with_a_route_to_nowhere_is_refused(w):
    a, m = ids(w, "Ashby", "Harrow Mine")
    w.set_route(a, m, 180)
    data = w.to_dict()
    data["routes"][0]["b"] = "e999"
    with pytest.raises(CorruptSave, match="two recorded places"):
        World.from_dict(data)


# ---- establish -----------------------------------------------------------------------------------------------------


@pytest.fixture
def state():
    s = GameState(Phase.ADVENTURE, {"setting": "x", "party": [{"name": "Kit", "sheet": "Rogue"}]})
    ashby = s.world.add_entity("Ashby", "location")
    flagon = s.world.add_entity("The Rusty Flagon", "location", parent=ashby.id)
    s.world.set_scene(flagon.id, [])
    s.turn = 3
    return s


def establish(state, entities):
    return dispatch("establish", "t1", {"entities": entities}, state)


def test_establish_records_a_place_with_a_scale_and_routes(state):
    out = establish(state, [{
        "name": "Harrow Mine", "kind": "location", "scale": "site",
        "routes": [{"to": "Ashby", "hours": 3, "how": "along the toll road"}],
    }])
    assert not out.is_error and "routes: Harrow Mine to Ashby (3 hours)" in out.content
    mine = state.world.find("Harrow Mine")
    assert mine.scale == "site" and state.world.routes_of(mine.id)[0].how == "along the toll road"
    assert "not on the map" not in out.content


def test_a_new_place_outside_the_party_s_place_is_asked_for_a_route(state):
    out = establish(state, [{"name": "Harrow Mine", "kind": "location"}])
    assert not out.is_error and "not on the map yet: Harrow Mine" in out.content
    assert state.world.find("Harrow Mine") is not None  # asked, not refused


def test_a_new_place_inside_the_party_s_place_needs_no_route(state):
    out = establish(state, [{"name": "The Cellar", "kind": "location", "parent": "The Rusty Flagon"}])
    assert "not on the map" not in out.content


def test_a_route_can_name_a_place_declared_in_the_same_call(state):
    out = establish(state, [
        {"name": "Millford", "kind": "location", "scale": "settlement", "routes": [{"to": "Ashby", "minutes": 120}]},
        {"name": "Millford Mill", "kind": "location", "parent": "Millford", "routes": [{"to": "Millford", "minutes": 10}]},
    ])
    assert not out.is_error and len(state.world.routes) == 2


def test_establish_adds_and_clears_a_block_on_an_existing_place(state):
    establish(state, [{"name": "The Cellar", "kind": "location", "parent": "The Rusty Flagon",
                       "routes": [{"to": "The Rusty Flagon", "minutes": 4, "how": "down the steps"}]}])
    out = establish(state, [{"name": "The Cellar", "kind": "location", "routes": [{
        "to": "The Rusty Flagon", "minutes": 4, "how": "down the steps",
        "block": {"kind": "locked", "text": "A locked oak door", "opens_by": "the steward's key"}}]}])
    route = state.world.routes_of(state.world.find("The Cellar").id)[0]
    assert not out.is_error and route.block.kind == "locked" and len(state.world.routes) == 1
    out = establish(state, [{"name": "The Cellar", "kind": "location", "routes": [
        {"to": "The Rusty Flagon", "minutes": 4, "how": "down the steps", "block": None}]}])
    assert not out.is_error and state.world.routes_of(state.world.find("The Cellar").id)[0].block is None


@pytest.mark.parametrize(
    "way, why",
    [
        ({"to": "Nowhere", "minutes": 5}, "not recorded"),
        ({"to": "Ashby"}, "how long"),
        ({"to": "Ashby", "minutes": 5, "hours": 1}, "not both"),
        ({"to": "Ashby", "minutes": 0}, "minutes"),
        ({"to": "Ashby", "hours": 1.5}, "whole number"),
        ({"to": "Ashby", "minutes": 5, "block": {"kind": "magic", "text": "A seal"}}, "block kind"),
        ({"to": "Ashby", "minutes": 5, "block": "locked"}, "block"),
        ({"to": "Harrow Mine", "minutes": 5}, "different"),
    ],
)
def test_establish_refuses_a_bad_route_and_records_nothing(state, way, why):
    out = establish(state, [{"name": "Harrow Mine", "kind": "location", "routes": [way]}])
    assert out.is_error and "Nothing was recorded" in out.content and why in out.content
    assert state.world.find("Harrow Mine") is None and not state.world.routes


def test_scale_and_routes_are_ignored_on_things_that_are_not_places(state):
    out = establish(state, [{"name": "Wren", "kind": "npc", "scale": "room", "routes": [{"to": "Ashby", "minutes": 5}]}])
    assert not out.is_error and "only places have one" in out.content and not state.world.routes


def test_a_bad_scale_is_refused(state):
    out = establish(state, [{"name": "Harrow Mine", "kind": "location", "scale": "planet"}])
    assert out.is_error and "scale must be" in out.content


# ---- what the GM sees ----------------------------------------------------------------------------------------------


def test_the_briefing_lists_the_ways_out_with_blocks_and_unvisited_places(state):
    w = state.world
    f = w.find("The Rusty Flagon").id
    cellar = w.add_entity("The Cellar", "location", parent=f)
    mine = w.add_entity("Harrow Mine", "location")
    w.set_route(f, cellar.id, 4, "down the steps", block=Block("locked", "A locked oak door", "the steward's key"))
    w.set_route(f, mine.id, 180, "along the toll road")
    mine.visited = True
    line = next(ln for ln in build_briefing(w).splitlines() if ln.startswith("From here:"))
    assert "The Cellar, 4 minutes down the steps (locked: A locked oak door; opens by: the steward's key; not yet visited)" in line
    assert line.endswith("Harrow Mine, 3 hours along the toll road")


def test_recall_lists_the_ways_from_a_place(state):
    w = state.world
    f = w.find("The Rusty Flagon").id
    mine = w.add_entity("Harrow Mine", "location")
    w.set_route(f, mine.id, 90, "along the toll road")
    w.set_scale(f, "site")
    out = dispatch("recall", "t1", {"about": "The Rusty Flagon"}, state)
    assert "a site" in out.content and "Ways from here: Harrow Mine, 1 hour 30 minutes along the toll road" in out.content


def test_the_debug_dump_shows_the_map(state):
    w = state.world
    f = w.find("The Rusty Flagon").id
    mine = w.add_entity("Harrow Mine", "location")
    w.set_route(f, mine.id, 90, "along the toll road", block=Block("collapsed", "A rockfall", "pickaxes"))
    dump = dump_world(w)
    assert dump["routes"] == [
        "[r001 improvised] The Rusty Flagon <-> Harrow Mine: 90 minutes, along the toll road"
        " | collapsed: A rockfall (opens by: pickaxes)"
    ]
    assert "routes" not in dump_world(w, known_only=True)
    entry = next(e for e in dump["entities"] if e["name"] == "The Rusty Flagon")
    assert entry["visited"] is True


# ---- one place holds the world (docs/TIME.md 5.1) --------------------------------------------------------------------


def test_a_root_takes_in_every_place_that_had_no_parent_and_scales_as_a_region(w):
    root = w.add_entity("The Test Marches", "location")
    w.set_root(root.id)
    assert w.root == root.id and root.scale == "region"
    assert {w.find(n).parent for n in ("Ashby", "Harrow Mine")} == {root.id}
    assert w.find("The Rusty Flagon").parent == w.find("Ashby").id  # places with a parent stay where they were
    assert root.parent is None
    for name in ("The Cellar", "Harrow Mine"):  # any two places now share an ancestor
        assert travel_shared(w, name)


def travel_shared(w, name):
    from aigm.travel import shared_ancestor

    return shared_ancestor(w, w.find(name).id, w.find("Ashby").id) is not None


def test_only_a_place_with_nothing_above_it_can_be_the_root(w):
    with pytest.raises(WorldError, match="cannot be the root"):
        w.set_root(w.find("The Cellar").id)
    with pytest.raises(WorldError, match="cannot be the root"):
        w.set_root(w.find("Wren").id)


def test_a_new_place_with_no_parent_goes_inside_the_root_but_a_person_does_not(w):
    root = w.add_entity("The Test Marches", "location")
    w.set_root(root.id)
    assert w.default_parent("location", None) == root.id
    assert w.default_parent("location", w.find("Ashby").id) == w.find("Ashby").id
    assert w.default_parent("npc", None) is None
    assert World().default_parent("location", None) is None  # a world made before this has no root


def test_moving_a_place_inside_another_never_makes_a_loop(w):
    ashby, flagon, cellar = ids(w, "Ashby", "The Rusty Flagon", "The Cellar")
    w.set_parent(cellar, ashby)
    assert w.find("The Cellar").parent == ashby and cellar not in [c.id for c in w.children(flagon)]
    assert cellar in [c.id for c in w.children(ashby)]
    with pytest.raises(WorldError, match="loop"):
        w.set_parent(ashby, flagon)
    with pytest.raises(WorldError, match="loop"):
        w.set_parent(ashby, ashby)


def test_the_root_round_trips_and_an_old_world_has_none(w):
    root = w.add_entity("The Test Marches", "location")
    w.set_root(root.id)
    assert World.from_dict(w.to_dict()).root == root.id
    data = w.to_dict()
    del data["root"]
    assert World.from_dict(data).root is None
    data["root"] = w.find("The Cellar").id
    with pytest.raises(CorruptSave, match="root"):
        World.from_dict(data)


def test_establish_puts_a_place_with_no_parent_in_the_root_and_a_later_parent_moves_it(state):
    w = state.world
    root = w.add_entity("The Test Marches", "location")
    w.set_root(root.id)
    out = establish(state, [{"name": "Chapel", "kind": "location"}])
    assert not out.is_error and "placed directly in The Test Marches: Chapel" in out.content
    assert state.world.find("Chapel").parent == root.id
    out = establish(state, [{"name": "Chapel", "kind": "location", "parent": "Ashby"}])
    assert not out.is_error and state.world.find("Chapel").parent == state.world.find("Ashby").id
    # a place that was put somewhere deliberately is not moved by a later mention
    establish(state, [{"name": "Chapel", "kind": "location", "parent": "The Rusty Flagon"}])
    assert state.world.find("Chapel").parent == state.world.find("Ashby").id


def test_establish_in_a_world_with_no_root_leaves_a_place_without_a_parent(state):
    out = establish(state, [{"name": "Chapel", "kind": "location"}])
    assert state.world.find("Chapel").parent is None and "placed directly" not in out.content
