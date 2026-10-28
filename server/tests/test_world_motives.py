"""Motives: the record, scene lapse, saves, the briefing, the debug views (docs/ROLEPLAY.md 7, build step 1)."""

import json

import pytest

from aigm import hidden_view
from aigm.errors import CorruptSave
from aigm.session.persistence import HistoryRepository
from aigm.session.state import GameState, Phase
from aigm.world import Motive, World, WorldError
from aigm.world.briefing import build_briefing
from aigm.world.dump import dump_world, render
from tests.test_debug_context import make

FEAR = "Fears the Thorn Guild will learn he sold them a false tally."
WANT = "Wants the party gone before the captain returns at noon."


@pytest.fixture
def w():
    world = World()
    inn = world.add_entity("The Rusty Flagon", "location")
    yard = world.add_entity("The Yard", "location")
    harlan = world.add_entity("Harlan Voss", "npc")
    wren = world.add_entity("Wren", "npc")
    world.add_entity("Thorn Guild", "faction")
    world.add_fact("Harlan Voss keeps the tally books.", [harlan.id], aspect="role", disclosure="known")
    world.set_scene(inn.id, [harlan.id, wren.id])
    world.inn, world.yard, world.harlan, world.wren = inn.id, yard.id, harlan.id, wren.id
    return world


# ---- the record -------------------------------------------------------------------------------


def test_adding_a_motive_records_it_hidden_and_live(w):
    m = w.add_motive(
        w.harlan, FEAR, kind="fear", strength="driven", moved_by=["a promise of silence"],
        resists=["open threats"], tells=["Glances at the cellar door."], turn=4,
    )
    assert m.id == "m001" and m.scope == "underlying" and m.disclosure == "hidden" and m.status == "active"
    assert (m.owner, m.kind, m.strength, m.turn) == (w.harlan, "fear", "driven", 4)
    assert m.moved_by == ("a promise of silence",) and m.tells == ("Glances at the cellar door.",)
    assert w.motives_of(w.harlan) == [m] and w.motive_live(m) and w.motive_state(m) == "active"
    assert w.add_motive(w.harlan, "Dreams of running his own counting house.", kind="want").id == "m002"


def test_only_people_have_motives_and_the_fields_are_checked(w):
    guild = w.find("Thorn Guild").id
    for owner, kwargs, message in [
        (guild, {}, "only people"),
        ("e099", {}, "unknown entity"),
        (w.harlan, {"kind": "hunger"}, "kind must be one of"),
        (w.harlan, {"strength": "mighty"}, "strength must be one of"),
        (w.harlan, {"scope": "forever"}, "scope must be one of"),
        (w.harlan, {"disclosure": "secret"}, "disclosure must be one of"),
        (w.harlan, {"source": "dream"}, "source must be one of"),
        (w.harlan, {"tells": ["a", "b", "c", "d", "e"]}, "at most 4 tells"),
        (w.harlan, {"resists": ["x" * 200]}, "at most 140 characters"),
        (w.harlan, {"moved_by": [""]}, "non-empty"),
    ]:
        with pytest.raises(WorldError, match=message):
            w.add_motive(owner, FEAR, **kwargs)
    for text in ("", "Greedy.", "word " * 61):
        with pytest.raises(WorldError):
            w.add_motive(w.harlan, text)
    assert not w.motives  # nothing was recorded by any failed call


def test_a_person_has_two_lasting_motives_and_one_for_the_scene(w):
    w.add_motive(w.harlan, FEAR)
    w.add_motive(w.harlan, "Hopes to be made head clerk someday.")
    with pytest.raises(WorldError, match="already has 2 underlying"):
        w.add_motive(w.harlan, "Loves his late wife's memory.")
    w.add_motive(w.harlan, WANT, scope="scene")
    with pytest.raises(WorldError, match="already has 1 scene motive"):
        w.add_motive(w.harlan, "Wants a drink very badly right now.", scope="scene")
    w.add_motive(w.wren, WANT, scope="scene")  # the caps are per person


def test_a_scene_motive_needs_a_scene_location(w):
    w.set_scene(None)
    with pytest.raises(WorldError, match="scene location"):
        w.add_motive(w.harlan, WANT, scope="scene")


def test_absolute_motives_are_underlying_written_ahead_of_play_and_one_per_person(w):
    m = w.add_motive(w.harlan, "Would die before breaking his oath to Lord Ashby.", kind="loyalty", strength="absolute")
    assert m.strength == "absolute"
    with pytest.raises(WorldError, match="at most one"):
        w.add_motive(w.harlan, "Will never forgive the Guild.", kind="grudge", strength="absolute")
    with pytest.raises(WorldError, match="must be underlying"):
        w.add_motive(w.wren, WANT, scope="scene", strength="absolute")
    for source in ("improvised", "play"):
        with pytest.raises(WorldError, match="ahead of play"):
            w.add_motive(w.wren, "Holds a sacred vow of silence.", strength="absolute", source=source)
    w.add_motive(w.wren, "Holds a sacred vow of silence.", strength="absolute", source="seed")


# ---- scene motives lapse ----------------------------------------------------------------------


def test_a_scene_motive_lapses_when_the_party_leaves_or_hours_pass(w):
    lasting = w.add_motive(w.harlan, FEAR)
    scene = w.add_motive(w.harlan, WANT, scope="scene", kind="want", strength="driven")
    assert scene.scene_location == w.inn and w.motives_of(w.harlan) == [lasting, scene]
    w.advance_time(1)
    assert w.motive_live(scene)
    w.advance_time(1)  # two hours: it has lapsed, and nothing was written to the record to do it
    assert not w.motive_live(scene) and w.motive_state(scene) == "expired" and scene.status == "active"
    assert w.motives_of(w.harlan) == [lasting]
    assert w.motives_of(w.harlan, live_only=False) == [lasting, scene]
    # a lapsed scene motive no longer counts toward the cap
    again = w.add_motive(w.harlan, "Wants to learn who sent the party here.", scope="scene")
    assert w.motives_of(w.harlan) == [lasting, again]


def test_a_scene_motive_lapses_when_the_party_moves_and_does_not_come_back(w):
    scene = w.add_motive(w.harlan, WANT, scope="scene")
    w.set_scene(w.yard, [w.harlan])
    assert not w.motive_live(scene)
    w.set_scene(w.inn, [w.harlan])
    assert w.motive_live(scene)  # back in the same place within the two hours: the moment is still on
    w.advance_time(3)
    assert not w.motive_live(scene)


def test_resolved_and_superseded_motives_are_not_live(w):
    m = w.add_motive(w.harlan, FEAR)
    m.status = "satisfied"
    assert w.motives_of(w.harlan) == [] and w.motives_of(w.harlan, live_only=False) == []
    assert w.motive_state(m) == "satisfied"


def test_motives_are_listed_lasting_first_then_strongest(w):
    weak = w.add_motive(w.harlan, "Likes the quiet of the evenings.", strength="leaning")
    strong = w.add_motive(w.harlan, FEAR, strength="driven")
    scene = w.add_motive(w.harlan, WANT, scope="scene", strength="driven")
    assert w.motives_of(w.harlan) == [strong, weak, scene]


# ---- saves and staging ------------------------------------------------------------------------


def with_motives(w):
    w.add_motive(w.harlan, FEAR, kind="fear", strength="driven", tells=["Glances at the door."], turn=2)
    w.add_motive(w.harlan, WANT, scope="scene", strength="leaning")
    w.add_motive(w.wren, "Would never betray the Guild.", kind="loyalty", strength="absolute")
    return w


def test_motives_round_trip_and_a_copy_is_independent(w):
    with_motives(w)
    again = World.from_dict(json.loads(json.dumps(w.to_dict())))
    assert again == w and again.motives["m002"].scene_location == w.inn
    assert again.motives["m001"].tells == ("Glances at the door.",) and again.next_id["m"] == 4
    staged = w.copy()
    staged.add_motive(staged.wren, "Wants out of this town.", kind="want")
    assert len(w.motives) == 3 and len(staged.motives) == 4  # a failed turn's staged world is just dropped


def test_a_world_saved_before_motives_loads_with_none(w):
    data = w.to_dict()
    del data["motives"]
    del data["next_id"]["m"]
    loaded = World.from_dict(data)
    assert loaded.motives == {} and loaded.next_id["m"] == 1
    assert loaded.add_motive(loaded.find("Harlan Voss").id, FEAR).id == "m001"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["motives"][0].update(owner="e099"),
        lambda d: d["motives"][0].update(owner="e005"),  # the faction
        lambda d: d["motives"][0].update(kind="hunger"),
        lambda d: d["motives"][0].update(strength="mighty"),
        lambda d: d["motives"][0].update(scope="forever"),
        lambda d: d["motives"][0].update(status="expired"),  # computed, never stored
        lambda d: d["motives"][0].update(text=" "),
        lambda d: d["motives"][0].update(id="x1"),
        lambda d: d["motives"][0].update(tells=[3]),
        lambda d: d["motives"][0].update(status="superseded"),
        lambda d: d["motives"][0].update(superseded_by="m099", status="superseded"),
        lambda d: d["motives"][1].update(scene_location=None),
        lambda d: d["motives"][2].update(scope="scene", scene_location="e001"),  # absolute and scene
        lambda d: d["motives"].append(dict(d["motives"][0])),
        lambda d: d["next_id"].update(m=1),
        lambda d: d.update(motives="nope"),
    ],
)
def test_corrupt_motives_are_rejected(w, mutate):
    with_motives(w)
    data = w.to_dict()
    mutate(data)
    with pytest.raises(CorruptSave, match="world"):
        World.from_dict(data)


async def test_motives_survive_a_saved_game(tmp_path):
    repo = HistoryRepository(tmp_path / "saves")
    state = GameState(Phase.ADVENTURE, {"setting": "x"})
    w = state.world
    inn = w.add_entity("The Rusty Flagon", "location")
    harlan = w.add_entity("Harlan Voss", "npc")
    w.set_scene(inn.id, [harlan.id])
    w.add_motive(harlan.id, FEAR, kind="fear", strength="driven")
    messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    await repo.save("g", messages, state, "m")
    _, loaded, _ = await repo.load("g")
    assert loaded.world == w and loaded.world.motives["m001"].kind == "fear"


# ---- the briefing -----------------------------------------------------------------------------


def test_the_briefing_shows_the_motives_of_the_people_present_as_gm_only(w):
    w.add_motive(
        w.harlan, FEAR, kind="fear", strength="driven", moved_by=["a promise of silence", "someone else to blame"],
        resists=["open threats"], tells=["Glances at the cellar door.", "Over-explains the tally."],
    )
    w.add_motive(w.harlan, WANT, scope="scene", strength="leaning")
    text = build_briefing(w)
    assert "GM only: play them from this, show tells, never state a motive" in text
    assert f"- Harlan Voss: fear (driven, underlying): {FEAR} Moved by: a promise of silence; someone else to blame. " in text
    assert "Resists: open threats. Tells: Glances at the cellar door.; Over-explains the tally." in text
    assert "want (leaning, scene, lapses when the party leaves or after 2 hours)" in text
    assert text.index(FEAR) < text.index(WANT)  # lasting motives first


def test_the_briefing_omits_motives_of_people_who_are_absent_or_lapsed(w):
    w.add_motive(w.harlan, FEAR)
    scene = w.add_motive(w.wren, WANT, scope="scene")
    w.set_scene(w.inn, [w.wren])  # Harlan has left the scene
    assert FEAR not in build_briefing(w) and WANT in build_briefing(w)
    w.advance_time(2)
    assert "What the people present want" not in build_briefing(w) and not w.motive_live(scene)


def test_a_briefing_without_motives_is_unchanged(w):
    assert "want" not in build_briefing(w).lower()


def test_motives_are_cut_before_facts_when_the_budget_is_tight(w):
    for i in range(14):
        w.add_fact(f"The Rusty Flagon has curious fact number {i} about its cellar stairs.", [w.inn])
    w.add_motive(w.harlan, FEAR)
    roomy = build_briefing(w, budget_tokens=2000)
    assert FEAR in roomy
    tight = build_briefing(w, budget_tokens=150)
    assert FEAR not in tight and "curious fact number 0" in tight


# ---- the debug views --------------------------------------------------------------------------


def test_the_hidden_view_lists_people_with_only_motives_and_names_their_type(w):
    w.add_motive(w.harlan, FEAR, kind="fear", strength="driven", tells=["Glances at the door."])
    w.add_motive(w.harlan, WANT, scope="scene", kind="want")
    w.advance_time(2)  # the scene motive lapses
    rows = {r["name"]: r for r in hidden_view.entries(w)}
    assert set(rows) == {"Harlan Voss"} and rows["Harlan Voss"]["motive_count"] == 2
    assert rows["Harlan Voss"]["hidden_count"] == 0
    detail = hidden_view.detail(w, w.harlan)
    by_id = {m["id"]: m for m in detail["motives"]}
    assert by_id["m001"]["kind"] == "fear" and by_id["m001"]["strength"] == "driven"
    assert by_id["m001"]["status"] == "active" and by_id["m001"]["tells"] == ["Glances at the door."]
    assert by_id["m002"]["kind"] == "want" and by_id["m002"]["scope"] == "scene" and by_id["m002"]["status"] == "expired"
    assert detail["facts"] == []


def test_the_hidden_route_serves_motives_on_a_debug_server_only(tmp_path):
    for debug, expected in ((True, 200), (False, 404)):
        app, client = make(tmp_path / str(debug), debug=debug)
        session = app.state.sessions.get("default")
        world = session.state.world
        loc = world.add_entity("The Rusty Flagon", "location")
        harlan = world.add_entity("Harlan Voss", "npc")
        world.set_scene(loc.id, [harlan.id])
        world.add_motive(harlan.id, FEAR, kind="fear", strength="driven")
        got = client.get(f"/debug/hidden/{harlan.id}")
        assert got.status_code == expected
        if debug:
            assert got.json()["motives"][0]["kind"] == "fear" and client.get("/debug/hidden").json()["count"] == 1


def test_the_dump_shows_motives_but_not_in_the_known_only_view(w):
    w.add_motive(w.harlan, FEAR, kind="fear", strength="driven", tells=["Glances at the door."])
    entry = next(e for e in dump_world(w)["entities"] if e["name"] == "Harlan Voss")
    assert entry["motives"] == [f"[fear|driven|underlying|hidden|m001] {FEAR}  (tells: Glances at the door.)"]
    assert FEAR not in render(w, known_only=True)


def test_nothing_a_player_may_read_shows_a_motive(tmp_path):
    app, client = make(tmp_path, debug=True)
    session = app.state.sessions.get("default")
    world = session.state.world
    loc = world.add_entity("The Rusty Flagon", "location")
    harlan = world.add_entity("Harlan Voss", "npc")
    world.add_fact("Harlan Voss keeps the tally books.", [harlan.id], aspect="role", disclosure="known")
    world.add_fact("The Rusty Flagon is a coaching inn.", [loc.id], aspect="overview", disclosure="known")
    world.set_scene(loc.id, [harlan.id])
    world.add_motive(harlan.id, FEAR, kind="fear", strength="driven", tells=["Glances at the cellar door."])
    session.state.phase = Phase.ADVENTURE
    for path in ("/compendium/characters", f"/compendium/entities/{harlan.id}", "/compendium/locations", "/status",
                 "/chat/history"):
        body = client.get(path).text
        assert "false tally" not in body and "cellar door" not in body, path
