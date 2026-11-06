"""A place the party stands in is known at once; a curator pass cannot undo a move the GM made while it ran."""

from aigm.compendium import Compendium, detail, entries
from aigm.world import World
from aigm.world.ops import SetScene, apply_ops


def two_places() -> tuple[World, str, str]:
    w = World()
    gate = w.add_entity("Gate", "location")
    hall = w.add_entity("Antechamber", "location", parent=gate.id)
    w.add_fact("SECRET: skeletons wait in the water.", [hall.id], aspect="secret")
    w.set_scene(gate.id)
    return w, gate.id, hall.id


def test_arriving_makes_a_place_discovered_and_listed_before_any_fact_about_it():
    w, gate, hall = two_places()
    assert not w.entities[hall].discovered
    assert hall not in {e["id"] for e in entries(w, Compendium(), "locations")}
    w.set_scene(hall)
    assert w.entities[hall].discovered
    assert hall in {e["id"] for e in entries(w, Compendium(), "locations")}
    entry = detail(w, Compendium(), hall)
    assert entry is not None and entry["facts"] == []
    assert "skeletons" not in str(entry)


def test_a_place_never_visited_stays_hidden():
    w, gate, hall = two_places()
    assert detail(w, Compendium(), hall) is None


def test_a_passes_reading_of_the_scene_is_dropped_when_the_party_moved_meanwhile():
    w, gate, hall = two_places()
    stale = SetScene("Gate", ("Gate",), guard=True, origin=gate)  # read when the party was still at the gate
    w.set_scene(hall)  # the GM moves them while the pass runs
    applied = apply_ops(w, [stale])
    assert w.scene.location == hall
    assert not applied.ops and "moved" in applied.skipped[0]


def test_a_passes_reading_of_the_scene_applies_when_the_party_stayed():
    w, gate, hall = two_places()
    applied = apply_ops(w, [SetScene("Antechamber", guard=True, origin=gate)])
    assert w.scene.location == hall and applied.ops


# ---- the player characters are not people the party meets --------------------------------------------------------


def party_world() -> World:
    from aigm.session.state import GameState

    state = GameState(campaign={"party": [{"name": "Brannoc Ironhale"}, {"name": "Sister Aldreth Vane"}]})
    w = state.world
    gate = w.add_entity("Gate", "location")
    for name in ("Brannoc", "Sister Aldreth"):
        pc = w.add_entity(name, "npc")
        w.add_fact(f"{name} is here.", [pc.id], aspect="role", disclosure="known", source="play", turn=1)
    w.add_entity("Aldreth Voss", "npc")
    w.add_entity("Sister Maud", "npc")
    w.set_scene(gate.id, [e.id for e in w.entities.values() if e.kind == "npc"])
    return w


def test_a_short_form_of_a_pc_name_is_the_pc_but_a_namesake_or_a_title_is_not():
    w = party_world()
    assert [w.is_party(w.find(n)) for n in ("Brannoc", "Sister Aldreth", "Aldreth Voss", "Sister Maud")] == [
        True, True, False, False,
    ]


def test_pcs_are_kept_out_of_the_scene_the_compendium_and_the_status_page():
    from aigm.session.state import GameState
    from aigm.status import build

    w = party_world()
    assert [w.entities[e].name for e in w.scene.present] == ["Aldreth Voss", "Sister Maud"]
    names = {e["name"] for e in entries(w, Compendium(), "characters")}
    assert not names & {"Brannoc", "Sister Aldreth"}
    state = GameState(campaign={"party": [{"name": "Brannoc Ironhale"}, {"name": "Sister Aldreth Vane"}]}, world=w)
    assert {e["name"] for e in build(state)["here"]} <= {"Aldreth Voss", "Sister Maud"}


def test_a_world_loaded_with_pcs_already_present_drops_them():
    from aigm.session.state import GameState

    w = World()
    gate = w.add_entity("Gate", "location")
    pc = w.add_entity("Tamsin", "npc")
    w.set_scene(gate.id, [pc.id])
    assert w.scene.present == [pc.id]
    state = GameState(campaign={"party": [{"name": "Tamsin Quill"}]}, world=w)
    assert state.world.scene.present == []


# ---- objects in a place are listed only once the party has seen them ---------------------------------------------


def test_arriving_shows_the_overview_but_not_the_objects_lying_in_the_place():
    from aigm.status import build
    from aigm.session.state import GameState

    w = World()
    gate = w.add_entity("Gate", "location")
    crypt = w.add_entity("Crypt", "location", parent=gate.id)
    w.add_fact("Dust lies thick on the crypt's steps.", [crypt.id], aspect="overview")
    truth = w.add_fact("The crypt holds a +1 Longsword and two Potions of Healing.", [crypt.id], aspect="items")
    w.set_scene(crypt.id)
    state = GameState(world=w)
    page = build(state)
    assert page["location"]["overview"] == "Dust lies thick on the crypt's steps."
    assert page["items"] == []
    w.add_fact("Two stoppered vials stand on a ledge.", [crypt.id], aspect="items", disclosure="known", source="play")
    assert build(state)["items"] == ["Two stoppered vials stand on a ledge."]
    assert not w.fact(truth.id).disclosure == "known"  # what they are stays the GM's until the party learns it
