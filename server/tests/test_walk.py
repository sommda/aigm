"""Walking the graph: choosing between ways, blocks, the unexplored and the guide (docs/TIME.md 5.4, build step 5)."""

import pytest

from aigm import travel
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch
from aigm.world import Block, World, WorldTime


@pytest.fixture
def state():
    """A manor. The Hall joins the Cellar down the Main Stair (a landing between, 2 + 4 minutes) or by the servants'
    passages (3 + 5), the Kitchen opens off the Hall, and Wren is with the party."""
    s = GameState(Phase.ADVENTURE, {"setting": "x", "party": [{"name": "Kit", "sheet": "Rogue"}]})
    w = s.world
    manor = w.add_entity("The Manor", "location")
    rooms = {n: w.add_entity(n, "location", parent=manor.id) for n in
             ("The Hall", "The Landing", "The Servants' Passage", "The Cellar", "The Kitchen")}
    w.add_entity("Wren", "npc")
    hall, landing, passage, cellar, kitchen = (rooms[n].id for n in
        ("The Hall", "The Landing", "The Servants' Passage", "The Cellar", "The Kitchen"))
    w.set_route(hall, landing, 2, "up the main stair")
    w.set_route(landing, cellar.id if hasattr(cellar, "id") else cellar, 4, "down the cellar steps")
    w.set_route(hall, passage, 3, "through the servants' door")
    w.set_route(passage, cellar, 5, "along the servants' passages")
    w.set_route(hall, kitchen, 1, "through the kitchen door")
    for n in ("The Hall", "The Landing", "The Servants' Passage", "The Cellar", "The Kitchen"):
        w.find(n).discovered = True  # the party has heard of them all
    w.set_scene(hall, [w.find("Wren").id])
    s.turn = 5
    return s


def go(state, **kw):
    return dispatch("set_scene", "t1", kw, state)


def at(state):
    return state.world.entities[state.world.scene.location].name


def visit(state, *names):
    for n in names:
        state.world.find(n).visited = True


# ---- which way ------------------------------------------------------------------------------------------------------


def test_two_ways_to_a_place_are_put_to_the_player_and_nothing_moves(state):
    visit(state, "The Landing", "The Servants' Passage")
    start = state.world.time
    out = go(state, location="The Cellar", elapsed_minutes=30)
    assert out.is_error and out.content.startswith("Scene not changed: there is more than one way")
    assert "The Landing (up the main stair) then The Cellar (down the cellar steps): about 6 minutes" in out.content
    assert "The Servants' Passage (through the servants' door) then The Cellar (along the servants' passages)" in out.content
    assert "ask which" in out.content and "`via`" in out.content
    assert at(state) == "The Hall" and state.world.time == start


@pytest.mark.parametrize("via", ["The Landing", "the main stair", "Servants' Passage", "servants' passages"])
def test_via_names_a_place_on_the_way_or_words_from_its_description(state, via):
    visit(state, "The Landing", "The Servants' Passage")
    out = go(state, location="The Cellar", via=via)
    assert not out.is_error and at(state) == "The Cellar"
    minutes = 6 if "ain" in via or via == "The Landing" else 8
    assert state.world.time == WorldTime(1, 8, minutes)


def test_a_via_that_matches_no_way_asks_again(state):
    visit(state, "The Landing", "The Servants' Passage")
    out = go(state, location="The Cellar", via="the roof")
    assert out.is_error and "more than one way" in out.content and at(state) == "The Hall"


def test_one_way_needs_no_via_and_an_unneeded_via_is_ignored(state):
    visit(state, "The Kitchen")
    assert not go(state, location="The Kitchen", via="the moon").is_error and at(state) == "The Kitchen"


def test_a_way_that_is_barely_longer_than_a_few_minutes_is_not_worth_asking_about(state):
    w = state.world
    w.routes.clear()
    w._routes_by_place.clear()
    hall, cellar = w.find("The Hall").id, w.find("The Cellar").id
    w.set_route(hall, cellar, 3, "down the stair")
    w.set_route(hall, cellar, 4, "down the ramp")
    visit(state, "The Cellar")
    out = go(state, location="The Cellar")
    assert not out.is_error and at(state) == "The Cellar" and state.world.time == WorldTime(1, 8, 3)


def test_a_way_through_a_place_the_player_does_not_know_is_not_offered(state):
    state.world.find("The Servants' Passage").discovered = False
    visit(state, "The Landing")
    out = go(state, location="The Cellar")
    assert not out.is_error and at(state) == "The Cellar"  # only the known way, so nothing to ask
    assert state.world.time == WorldTime(1, 8, 6)


def test_the_ways_offered_are_at_most_three_and_none_costs_more_than_twice_the_shortest(state):
    w = state.world
    hall, cellar = w.find("The Hall").id, w.find("The Cellar").id
    w.set_route(hall, cellar, 30, "by the long way round")  # more than twice 6
    ways = travel.plan_ways(w, hall, cellar)
    assert [j.minutes for j in ways] == [6, 8]


def test_two_routes_between_the_same_places_are_two_ways(state):
    w = state.world
    hall, cellar = w.find("The Hall").id, w.find("The Cellar").id
    w.set_route(hall, cellar, 9, "down the coal chute")
    ways = travel.plan_ways(w, hall, cellar)
    assert sorted(j.minutes for j in ways) == [6, 8, 9]


# ---- the unexplored ---------------------------------------------------------------------------------------------------


def test_the_party_is_set_down_in_the_first_place_it_has_not_been(state):
    state.world.find("The Servants' Passage").discovered = False  # so the only known way is the stair, whose landing is new
    out = go(state, location="The Cellar", elapsed_minutes=30, present=["Wren"])
    assert not out.is_error and at(state) == "The Landing"
    assert "stops at The Landing" in out.content and "new to them" in out.content and "no further" in out.content
    assert state.world.time == WorldTime(1, 8, 2)  # only the way to the landing
    assert state.world.scene.present == []  # the people at the cellar are not here
    assert state.world.find("The Landing").visited
    again = go(state, location="The Cellar")  # now that it has been seen, the way on is open
    assert not again.is_error and at(state) == "The Cellar" and state.world.time == WorldTime(1, 8, 6)


def test_arriving_at_the_unvisited_place_next_door_is_allowed(state):
    out = go(state, location="The Kitchen")
    assert not out.is_error and at(state) == "The Kitchen" and "stops at" not in out.content


def test_a_guide_takes_the_party_through_places_it_has_not_been(state):
    state.world.find("The Servants' Passage").discovered = False
    out = go(state, location="The Cellar", guide="Wren", present=["Wren"])
    assert not out.is_error and at(state) == "The Cellar" and "stops at" not in out.content
    assert state.world.find("The Landing").visited  # led through, so now they have been
    assert state.world.time == WorldTime(1, 8, 6)


def test_a_guide_must_be_with_the_party(state):
    state.world.add_entity("Harlan", "npc")
    out = go(state, location="The Cellar", guide="Harlan")
    assert out.is_error and "with the party" in out.content and at(state) == "The Hall"
    assert go(state, location="The Cellar", guide="nobody").is_error


def test_the_places_a_party_is_standing_in_count_as_visited(state):
    w = state.world
    assert travel.has_been(w, w.find("The Manor").id)  # the party is in the hall, which is in the manor


def test_instant_travel_skips_the_walk(state):
    out = go(state, location="The Cellar", pace="instant", how="a teleportation circle")
    assert not out.is_error and at(state) == "The Cellar" and state.world.time == WorldTime(1, 8, 0)


# ---- blocked ways -----------------------------------------------------------------------------------------------------


def lock_the_stair_and_the_passage(state):
    w = state.world
    for a, b, how in (("The Landing", "The Cellar", "down the cellar steps"), ("The Servants' Passage", "The Cellar", "along the servants' passages")):
        w.set_route(w.find(a).id, w.find(b).id, 4, how, block=Block("locked", "A locked oak door", "the steward's key"))


def test_a_way_around_a_block_is_taken(state):
    visit(state, "The Landing", "The Servants' Passage", "The Cellar")
    w = state.world
    w.set_route(w.find("The Landing").id, w.find("The Cellar").id, 4, "down the cellar steps",
                block=Block("locked", "A locked oak door", "the steward's key"))
    out = go(state, location="The Cellar")  # one way is locked, so there is only the servants' way
    assert not out.is_error and at(state) == "The Cellar" and state.world.time == WorldTime(1, 8, 8)


def test_a_block_on_every_way_stops_the_party_before_it(state):
    visit(state, "The Landing", "The Servants' Passage")
    lock_the_stair_and_the_passage(state)
    out = go(state, location="The Cellar", elapsed_minutes=30)
    assert not out.is_error and at(state) == "The Landing"  # the shortest way, as far as it goes
    assert "A locked oak door" in out.content and "the steward's key" in out.content
    assert "no further" in out.content and state.world.time == WorldTime(1, 8, 2)


def test_clearing_the_block_lets_the_party_through(state):
    visit(state, "The Landing", "The Servants' Passage")
    lock_the_stair_and_the_passage(state)
    go(state, location="The Cellar")
    out = dispatch("establish", "t1", {"entities": [{"name": "The Landing", "kind": "location", "routes": [
        {"to": "The Cellar", "minutes": 4, "how": "down the cellar steps", "block": None}]}]}, state)
    assert not out.is_error
    go(state, location="The Cellar")
    assert at(state) == "The Cellar"


def test_a_hidden_way_does_not_exist_for_the_party(state):
    w = state.world
    w.routes.clear()
    w._routes_by_place.clear()
    hall, cellar = w.find("The Hall").id, w.find("The Cellar").id
    w.set_route(hall, cellar, 7, "behind the bookcase", block=Block("hidden", "A secret door behind the bookcase", "pull the third book"))
    out = go(state, location="The Cellar")
    assert out.is_error and "can find no way" in out.content and at(state) == "The Hall"
    assert "bookcase" not in out.content  # nothing about the secret reaches the answer


def test_a_hidden_way_is_ignored_when_there_is_another(state):
    w = state.world
    w.set_route(w.find("The Hall").id, w.find("The Kitchen").id, 1, "behind the pantry",
                block=Block("hidden", "A secret hatch"))
    visit(state, "The Kitchen")
    out = go(state, location="The Kitchen")
    assert not out.is_error and at(state) == "The Kitchen"


# ---- no map ------------------------------------------------------------------------------------------------------------


def test_with_no_routes_there_is_no_walk_and_the_move_is_the_gms(state):
    w = state.world
    w.routes.clear()
    w._routes_by_place.clear()
    out = go(state, location="The Cellar")
    assert not out.is_error and at(state) == "The Cellar"
