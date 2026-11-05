"""How long it takes to get from one place to another (docs/TIME.md 5.3 to 5.6, build step 4)."""

import pytest

from aigm import travel
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch
from aigm.world import World, WorldTime


@pytest.fixture
def w():
    """Thornwood (region) holds Ashby (settlement: Flagon with Cellar and Attic, Smithy, Chapel) and Harrow Mine (a site
    with a Shaft), and Millford (a settlement of its own) lies in a second region, Eastmarch."""
    world = World()
    thorn = world.add_entity("Thornwood", "location")
    ashby = world.add_entity("Ashby", "location", parent=thorn.id)
    flagon = world.add_entity("The Rusty Flagon", "location", parent=ashby.id)
    world.add_entity("The Cellar", "location", parent=flagon.id)
    world.add_entity("The Attic", "location", parent=flagon.id)
    world.add_entity("Smithy", "location", parent=ashby.id)
    world.add_entity("Chapel", "location", parent=ashby.id)
    mine = world.add_entity("Harrow Mine", "location", parent=thorn.id)
    world.add_entity("The Shaft", "location", parent=mine.id)
    east = world.add_entity("Eastmarch", "location")
    world.add_entity("Millford", "location", parent=east.id)
    return world


def p(w, name):
    return w.find(name).id


def test_scales_are_read_from_what_the_world_holds(w):
    got = {n: travel.scale_of(w, p(w, n)) for n in (
        "Thornwood", "Ashby", "The Rusty Flagon", "The Cellar", "Smithy", "Harrow Mine", "The Shaft")}
    assert got == {
        "Thornwood": "region", "Ashby": "settlement", "The Rusty Flagon": "site", "The Cellar": "room",
        "Smithy": "site", "Harrow Mine": "site", "The Shaft": "room",
    }
    w.set_scale(p(w, "Thornwood"), "site")
    assert travel.scale_of(w, p(w, "Thornwood")) == "site"  # a recorded scale wins


def test_a_place_holding_two_settlements_is_a_region(w):
    w.set_scale(p(w, "Ashby"), "settlement")
    w.set_scale(p(w, "Millford"), "settlement")
    root = w.add_entity("The Realm", "location")
    w.entities[p(w, "Ashby")].parent = root.id
    w.entities[p(w, "Millford")].parent = root.id
    w._reindex()
    assert travel.scale_of(w, root.id) == "region"


@pytest.mark.parametrize(
    "a, b, minutes",
    [
        ("The Cellar", "The Cellar", 0),
        ("The Cellar", "The Attic", 5),  # rooms of the same site
        ("The Cellar", "The Rusty Flagon", 5),  # a room and its building
        ("The Rusty Flagon", "Smithy", 20),  # two sites in the same settlement
        ("The Cellar", "Smithy", 25),  # a room of one and another site
        ("The Rusty Flagon", "Ashby", 15),  # a site inside the town
        ("Ashby", "Harrow Mine", 360),  # a settlement and a site in the same region
        ("Millford", "Harrow Mine", 30),  # no shared place: the larger of two sites is a site
    ],
)
def test_the_estimate_between_places_with_no_recorded_way(w, a, b, minutes):
    w.set_scale(p(w, "Thornwood"), "region")
    w.set_scale(p(w, "Eastmarch"), "region")
    assert travel.estimate(w, p(w, a), p(w, b)) == minutes


def test_the_estimate_across_regions_and_between_unrelated_big_places(w):
    w.set_scale(p(w, "Thornwood"), "region")
    w.set_scale(p(w, "Eastmarch"), "region")
    assert travel.estimate(w, p(w, "Thornwood"), p(w, "Eastmarch")) == 24 * 60
    assert travel.estimate(w, p(w, "Ashby"), p(w, "Millford")) == 6 * 60


def test_a_recorded_route_is_the_journey(w):
    a, m = p(w, "Ashby"), p(w, "Harrow Mine")
    w.set_route(a, m, 150, "along the toll road")
    j = travel.plan_journey(w, a, m)
    assert (j.minutes, j.recorded, j.places) == (150, True, [a, m])


def test_places_without_routes_are_lifted_to_the_ones_that_have_them(w):
    a, m = p(w, "Ashby"), p(w, "Harrow Mine")
    w.set_route(a, m, 150, "along the toll road")
    cellar, shaft = p(w, "The Cellar"), p(w, "The Shaft")
    j = travel.plan_journey(w, cellar, shaft)
    # cellar to Ashby (25 minutes: a room in a site in the town is 5 + the site to the town 15, here the estimate),
    # the road, then the mine to the shaft (5)
    assert j.recorded and j.minutes == travel.estimate(w, cellar, a) + 150 + travel.estimate(w, m, shaft)
    assert j.places == [cellar, a, m, shaft]


def test_the_shortest_recorded_path_wins_over_a_longer_one(w):
    a, m, s = p(w, "Ashby"), p(w, "Harrow Mine"), p(w, "Smithy")
    w.set_route(a, m, 300, "the long way round")
    w.set_route(a, s, 10, "down the lane")
    w.set_route(s, m, 20, "past the forge")
    j = travel.plan_journey(w, a, m)
    assert (j.minutes, j.places) == (30, [a, s, m])


def test_a_blocked_route_can_be_left_out_of_the_search(w):
    a, m, s = p(w, "Ashby"), p(w, "Harrow Mine"), p(w, "Smithy")
    w.set_route(a, m, 300, "the long way round")
    w.set_route(a, s, 10, "down the lane")
    w.set_route(s, m, 20, "past the forge")
    j = travel.plan_journey(w, a, m, usable=lambda r: r.how != "past the forge")
    assert j.minutes == 300


def test_with_no_recorded_path_the_journey_is_the_estimate(w):
    a, m = p(w, "Ashby"), p(w, "Harrow Mine")
    j = travel.plan_journey(w, a, m)
    assert not j.recorded and j.minutes == travel.estimate(w, a, m) and j.places == [a, m]


@pytest.mark.parametrize("pace, minutes", [("normal", 100), ("fast", 50), ("instant", 0)])
def test_pace(pace, minutes):
    assert travel.paced(100, pace) == minutes
    assert travel.paced(1, "fast") == 1 and travel.paced(0, "fast") == 0


# ---- set_scene ------------------------------------------------------------------------------------------------------


@pytest.fixture
def state(w):
    s = GameState(Phase.ADVENTURE, {"setting": "x", "party": [{"name": "Kit", "sheet": "Rogue"}]})
    s.world = w
    s.world.set_scene(p(w, "The Rusty Flagon"), [])
    s.turn = 4
    return s


def go(state, **kw):
    return dispatch("set_scene", "t1", kw, state)


def test_a_move_takes_the_time_of_the_way(state):
    w = state.world
    w.set_route(p(w, "Ashby"), p(w, "Harrow Mine"), 150, "along the toll road")
    start = w.time
    out = go(state, location="Harrow Mine")
    assert not out.is_error and state.world.time == start.plus_minutes(
        travel.estimate(w, p(w, "The Rusty Flagon"), p(w, "Ashby")) + 150
    )
    assert "takes about" in out.content and "clock is moved" not in out.content
    assert state.world.time_log[-1]["why"] == "the way to Harrow Mine"


def test_a_move_the_gm_under_reported_is_raised_and_the_gm_is_told(state):
    w = state.world
    w.set_route(p(w, "Ashby"), p(w, "Harrow Mine"), 360, "along the toll road")
    out = go(state, location="Harrow Mine", elapsed_minutes=60)
    assert state.world.time > WorldTime(1, 14, 0) and "the clock is moved to match" in out.content


def test_a_move_the_gm_over_reported_stands(state):
    w = state.world
    w.set_route(p(w, "Ashby"), p(w, "Harrow Mine"), 60, "along the toll road")
    start = w.time
    out = go(state, location="Harrow Mine", elapsed_hours=10)
    assert state.world.time == start.plus_minutes(600) and "clock is moved" not in out.content


def test_the_first_placement_of_the_party_costs_no_travel():
    s = GameState(Phase.ADVENTURE, {"setting": "x", "party": [{"name": "Kit", "sheet": "Rogue"}]})
    s.world.add_entity("Ashby", "location")
    go(s, location="Ashby")
    assert s.world.time == WorldTime(1, 8, 0) and s.world.scene.location == s.world.find("Ashby").id


def test_a_move_inside_a_place_costs_a_few_minutes(state):
    out = go(state, location="The Cellar")
    assert not out.is_error and state.world.time == WorldTime(1, 8, 5)


def test_fast_and_instant_travel_need_the_means(state):
    for pace in ("fast", "instant"):
        out = go(state, location="Harrow Mine", pace=pace)
        assert out.is_error and "needs `how`" in out.content and state.world.scene.location == p(state.world, "The Rusty Flagon")
    assert go(state, location="Harrow Mine", pace="warp", how="a spell").is_error


def test_fast_travel_halves_the_time_and_instant_takes_none(state):
    w = state.world
    w.set_route(p(w, "Ashby"), p(w, "Harrow Mine"), 360, "along the toll road")
    full = travel.plan_journey(w, p(w, "The Rusty Flagon"), p(w, "Harrow Mine")).minutes
    start = w.time
    go(state, location="Harrow Mine", pace="fast", how="Mira's horses")
    assert state.world.time == start.plus_minutes(round(full / 2))
    assert "(Mira's horses)" in state.world.time_log[-1]["why"]
    state.world.set_scene(p(state.world, "The Rusty Flagon"), [])
    before = state.world.time
    out = go(state, location="Harrow Mine", pace="instant", how="the teleportation circle")
    assert not out.is_error and state.world.time == before and state.world.scene.location == p(state.world, "Harrow Mine")


def test_a_long_trip_between_places_with_no_route_is_learned(state):
    w = state.world
    ashby, mine = p(w, "Ashby"), p(w, "Harrow Mine")
    estimate = travel.estimate(w, p(w, "The Rusty Flagon"), mine)
    go(state, location="Harrow Mine", elapsed_minutes=estimate + 120)
    learned = state.world.find_route(p(w, "The Rusty Flagon"), mine)
    assert learned is not None and learned.source == "play" and learned.minutes == estimate + 120
    # and the next trip back takes the same time
    state.world.set_scene(p(w, "The Rusty Flagon"), [])
    back = go(state, location="Harrow Mine")
    assert not back.is_error and travel.plan_journey(state.world, p(w, "The Rusty Flagon"), mine).minutes == estimate + 120


def test_a_trip_that_is_no_longer_than_the_estimate_is_not_learned(state):
    w = state.world
    go(state, location="Harrow Mine", elapsed_minutes=1)
    assert not state.world.routes


def test_a_recorded_route_is_never_changed_by_play(state):
    w = state.world
    f, mine = p(w, "The Rusty Flagon"), p(w, "Harrow Mine")
    w.set_route(f, mine, 200, "")
    go(state, location="Harrow Mine", elapsed_minutes=900)
    assert w.find_route(f, mine).minutes == 200 and len(state.world.routes) == 1


def test_a_gate_and_a_square_in_a_town_are_sites_and_the_hills_around_are_a_region():
    """The shape of a world made before scales: it must not take a square inside a town for another town."""
    w = World()
    kingdom = w.add_entity("Kingdom", "location")
    hills = w.add_entity("Northern Hills", "location", parent=kingdom.id)
    town = w.add_entity("Icehold", "location", parent=hills.id)
    square = w.add_entity("Icehold Square", "location", parent=town.id)
    for n in ("Icehold Gate", "Healer's House"):
        w.add_entity(n, "location", parent=town.id)
    w.add_entity("Hesk's Well", "location", parent=square.id)
    w.add_entity("Saint Wren's Cairn", "location", parent=square.id)
    w.add_entity("Old Quarry", "location", parent=hills.id)
    got = {n: travel.scale_of(w, w.find(n).id) for n in ("Kingdom", "Northern Hills", "Icehold", "Icehold Square", "Hesk's Well", "Old Quarry")}
    assert got == {"Kingdom": "region", "Northern Hills": "region", "Icehold": "settlement", "Icehold Square": "site",
                   "Hesk's Well": "room", "Old Quarry": "site"}
    assert travel.estimate(w, square.id, town.id) == 15  # a square inside the town, not a six-hour trip
