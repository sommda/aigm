"""The Attempts block of the GM's notes (docs/ATTEMPTS.md 5)."""

from aigm.game import Game
from aigm.session.state import GameState, Phase
from aigm.world import World, WorldTime
from aigm.world.briefing import attempt_lines, build_briefing


def world():
    w = World()
    hall = w.add_entity("Great hall", "location")
    vault = w.add_entity("Vault door", "concept")
    cliff = w.add_entity("Far cliff", "location")
    w.set_scene(hall.id, [])
    return w, hall, vault, cliff


def test_nothing_shown_without_attempts():
    w, *_ = world()
    assert attempt_lines(w, [w.scene.location]) == [] and "Attempts" not in build_briefing(w)


def test_closed_and_open_attempts_are_listed_for_the_gm():
    w, hall, vault, cliff = world()
    a = w.add_attempt("Kit", "lock", "pick the vault lock", hall.id, status="closed", failure="a pick snapped")
    w.set_attempt_status(a.id, "closed", reopens_if="Better picks, or the key.")
    w.retry_attempt(a.id)
    w.add_attempt("Mira", "climb", "climb the cliff", hall.id, failure="the rope frays")
    text = build_briefing(w)
    assert "Attempts here (GM only)." in text and "Do not roll a closed attempt again" in text
    assert "- CLOSED: Kit tried to pick the vault lock (2 tries; a pick snapped). Reopens if: Better picks, or the key." in text
    assert "- OPEN: Mira tried to climb the cliff (1 try; the rope frays). A retry costs about 15 minutes" in text
    lines = attempt_lines(w, [hall.id])
    assert lines[1].startswith("- OPEN: Mira")  # newest first


def test_only_attempts_that_matter_here_are_shown_and_resolved_ones_are_not():
    w, hall, vault, cliff = world()
    w.add_attempt("Kit", "climb", "climb the far cliff", cliff.id)
    done = w.add_attempt("Kit", "lock", "pick the vault lock", hall.id)
    w.set_attempt_status(done.id, "resolved")
    assert attempt_lines(w, [w.scene.location]) == []
    assert attempt_lines(w, [w.scene.location, cliff.id])[1].startswith("- OPEN: Kit tried to climb the far cliff [Far cliff]")


def test_attempts_on_an_item_in_hand_and_on_a_present_person_are_shown():
    w, hall, vault, cliff = world()
    key = w.add_entity("Sluice Key", "item")
    w.set_holding(key.id, "acquired")
    steward = w.add_entity("Steward Hale", "npc")
    w.scene.present = [steward.id]
    w.add_attempt("Kit", "repair", "mend the sluice key", key.id)
    w.add_attempt("Kit", "social", "win over the steward", steward.id, status="closed")
    text = "\n".join(attempt_lines(w, [w.scene.location, steward.id]))
    assert "mend the sluice key [Sluice Key]" in text and "win over the steward [Steward Hale]" in text


def test_a_closure_whose_clock_has_run_out_is_shown_as_open_again():
    w, hall, *_ = world()
    a = w.add_attempt("Kit", "social", "win over the steward", hall.id, status="closed")
    w.set_attempt_status(a.id, "closed", reopens_if="New facts.", reopens_at=WorldTime(1, 12))
    assert "CLOSED" in "\n".join(attempt_lines(w, [hall.id])) and "Or at Day 1, 12:00" in "\n".join(attempt_lines(w, [hall.id]))
    w.set_time(WorldTime(1, 13))
    assert "Closed, now open again (time has passed)" in "\n".join(attempt_lines(w, [hall.id]))


def test_a_closure_to_everyone_says_so_and_the_block_is_capped():
    w, hall, *_ = world()
    w.add_attempt("Kit", "lock", "pick the vault lock", hall.id, status="closed", scope="anyone")
    assert "Closed to everyone." in "\n".join(attempt_lines(w, [hall.id]))
    for i in range(8):
        w.add_attempt("Mira", "climb", f"climb wall number {i}", hall.id)
    assert len(attempt_lines(w, [hall.id])) == 6  # the heading and five attempts


def test_the_game_adds_the_places_of_active_quests():
    w, hall, vault, cliff = world()
    w.add_attempt("Kit", "climb", "climb the far cliff", cliff.id)
    state = GameState(Phase.ADVENTURE, {"setting": "x"}, w)
    assert "far cliff" not in Game().briefing(state, "", "")
    from aigm.story import Chapter, Milestone, Story

    state.structure = "short"
    state.story = Story("short", None, [Chapter("One", "p")], [Milestone("m01", 1, "A", "b", entities=[cliff.id], status="active")])
    assert "climb the far cliff [Far cliff]" in Game().briefing(state, "", "")


def test_recall_and_the_dump_show_every_attempt():
    from aigm.tools import dispatch
    from aigm.world.dump import dump_world

    state = GameState(Phase.ADVENTURE, {"setting": "x"})
    hall = state.world.add_entity("Great hall", "location")
    state.world.set_scene(hall.id, [])
    a = state.world.add_attempt("Kit", "lock", "pick the vault lock", hall.id, status="closed", failure="a pick snapped")
    state.world.set_attempt_status(a.id, "closed", reopens_if="Better picks.")
    out = dispatch("recall", "t1", {"about": "Great hall"}, state)
    assert "Attempt a001 (closed): Kit tried to pick the vault lock, 1 try; a pick snapped. Reopens if: Better picks" in out.content
    assert "reopens if: Better picks." in dump_world(state.world)["attempts"][0]
