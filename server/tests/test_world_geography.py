"""The world-builder gives its places a scale and routes (docs/TIME.md 5.1 and 5.2, build step 6)."""

import pytest

from aigm.world import World
from aigm.world.anthropic_curator import BOOTSTRAP_SCHEMA, EXPAND_SCHEMA, FAMILIARITY_SCHEMA, PLOT_SCHEMA
from aigm.world.curator import EntityProposal, Extraction, FactProposal, RouteProposal
from aigm.world.ops import SetRoute, SetScale, apply_ops
from aigm.world.passes import PassConfig, PassResult, _plan_expansion, geography_ops, run_bootstrap
from aigm.world.scripted import ScriptedCurator
from tests.test_world_bootstrap import campaign
from tests.test_world_curator import curator, walk


@pytest.mark.parametrize("schema", [BOOTSTRAP_SCHEMA, EXPAND_SCHEMA, FAMILIARITY_SCHEMA, PLOT_SCHEMA])
def test_the_builders_schemas_ask_for_scale_and_routes_and_stay_closed(schema):
    walk(schema)
    entity = schema["properties"]["entities"]["items"]["properties"]
    assert set(entity["scale"]["anyOf"][0]["enum"]) == {"room", "site", "settlement", "region"}
    assert set(entity["routes"]["items"]["properties"]) == {"to", "minutes", "how"}


async def test_the_curator_s_places_come_back_with_scale_and_routes():
    reply = {
        "entities": [
            {"name": "Ashby", "kind": "location", "aliases": [], "parent": None, "scale": "settlement",
             "routes": [{"to": "Harrow Mine", "minutes": 180, "how": "along the toll road"},
                        {"to": "Nowhere", "minutes": 0, "how": "bad"}, {"to": 3, "minutes": 5, "how": "bad"}]},
            {"name": "Wren", "kind": "npc", "aliases": [], "parent": None, "scale": None, "routes": []},
            {"name": "Mill", "kind": "location", "aliases": [], "parent": "Ashby", "scale": "planet", "routes": "none"},
        ],
        "facts": [], "location": None, "present": None, "start_hour": None,
    }  # fmt: skip
    cur, _ = curator(reply)
    from aigm.world.curator import BootstrapRequest

    ex = await cur.bootstrap(BootstrapRequest("A setting.", "", 1, [], "", []))
    ashby, wren, mill = ex.entities
    assert ashby.scale == "settlement" and ashby.routes == [RouteProposal("Harrow Mine", 180, "along the toll road")]
    assert wren.scale is None and wren.routes == []
    assert mill.scale is None and mill.routes == []  # a scale that is not one, and routes that are not a list


def test_geography_ops_cover_places_only():
    props = [
        EntityProposal("Ashby", "location", scale="settlement", routes=[RouteProposal("Mine", 90, "road")]),
        EntityProposal("Wren", "npc", scale="room", routes=[RouteProposal("Mine", 5)]),
    ]
    assert geography_ops(props, "seed") == [SetScale("Ashby", "settlement"), SetRoute("Ashby", "Mine", 90, "road", "seed")]


def test_ops_set_a_scale_and_a_route_and_skip_what_names_nothing():
    w = World()
    w.add_entity("Ashby", "location")
    w.add_entity("Mine", "location")
    applied = apply_ops(w, [SetScale("Ashby", "settlement"), SetRoute("Ashby", "Mine", 90, "road", "seed"),
                            SetRoute("Ashby", "Nowhere", 5), SetScale("Wren", "room"), SetScale("Ashby", "planet")])
    assert len(applied.ops) == 2 and len(applied.skipped) == 3
    assert w.find("Ashby").scale == "settlement" and w.routes_of(w.find("Ashby").id)[0].source == "seed"


async def test_a_bootstrap_with_routes_makes_a_map():
    class Mapped(ScriptedCurator):
        async def bootstrap(self, request):
            return Extraction(
                entities=[
                    EntityProposal("Thornwood", "location", scale="region"),
                    EntityProposal("Ashby", "location", parent="Thornwood", scale="settlement"),
                    EntityProposal("Harrow Mine", "location", parent="Thornwood", scale="site",
                                   routes=[RouteProposal("Ashby", 180, "along the toll road")]),
                ],
                facts=[FactProposal("Harrow Mine lies east of Ashby.", ["Harrow Mine"], None, "known")],
                location="Ashby",
            )

    result = await run_bootstrap(campaign(), [{}], Mapped())
    w = World()
    apply_ops(w, result.ops)
    mine = w.find("Harrow Mine")
    assert mine.scale == "site" and w.find("Ashby").scale == "settlement"
    [route] = w.routes_of(mine.id)
    assert route.other(mine.id) == w.find("Ashby").id and route.minutes == 180 and route.source == "seed"


async def test_a_bootstrap_route_to_nowhere_is_skipped_without_losing_the_world():
    class Bad(ScriptedCurator):
        async def bootstrap(self, request):
            return Extraction(
                entities=[EntityProposal("Ashby", "location", routes=[RouteProposal("Atlantis", 60, "swim")])],
                facts=[FactProposal("Ashby is a market town.", ["Ashby"], None, "known")],
                location="Ashby",
            )

    result = await run_bootstrap(campaign(), [{}], Bad())
    w = World()
    apply_ops(w, result.ops)
    assert w.find("Ashby") is not None and not [r for r in w.routes.values() if r.source == "seed"]


def test_the_plotters_places_get_routes_recorded_as_the_plotters():
    w = World()
    root = w.add_entity("Thornwood", "location")
    w.add_entity("Ashby", "location", parent=root.id)
    out = Extraction(
        entities=[EntityProposal("Vane's Keep", "location", parent="Thornwood", scale="site",
                                 routes=[RouteProposal("Ashby", 240, "up the old road")])],
        facts=[FactProposal("Vane's Keep stands above the old road from Ashby.", ["Vane's Keep", "Ashby"], None, "hidden")],
    )
    ops = _plan_expansion(w, out, 1, PassConfig(), 8, 20, PassResult(), source="plotter")
    apply_ops(w, ops)
    [route] = w.routes_of(w.find("Vane's Keep").id)
    assert route.source == "plotter" and route.minutes == 240


def test_a_new_place_joined_to_the_world_only_by_a_route_counts_as_connected():
    w = World()
    root = w.add_entity("Thornwood", "location")
    w.add_entity("Ashby", "location", parent=root.id)
    out = Extraction(entities=[EntityProposal("Far Barrow", "location", routes=[RouteProposal("Ashby", 600, "over the moor")])])
    result = PassResult()
    ops = _plan_expansion(w, out, 1, PassConfig(), 8, 20, result, source="generated")
    apply_ops(w, ops)
    assert w.find("Far Barrow") is not None and not [n for n in result.notes if "unconnected" in n]


def test_a_builder_stating_a_way_from_both_ends_makes_one_route():
    w = World()
    w.add_entity("Ashby", "location")
    w.add_entity("Millford", "location")
    applied = apply_ops(w, [SetRoute("Ashby", "Millford", 300, "along the road to Millford", "seed"),
                            SetRoute("Millford", "Ashby", 310, "along the road to Ashby", "seed")])
    assert len(w.routes) == 1 and len(applied.ops) == 1
    # the GM can still record a second way between them (`improvised`), which is a different thing
    apply_ops(w, [SetRoute("Ashby", "Millford", 120, "by the river path", "improvised")])
    assert len(w.routes) == 2
