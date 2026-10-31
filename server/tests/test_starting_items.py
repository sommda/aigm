"""Key items the party starts with or knows of (docs/KEY_ITEMS.md 5.3): from Session 0 to the first compendium."""

import pytest

from aigm.compendium import Compendium, detail, entries
from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch
from aigm.world import World
from aigm.world.briefing import build_briefing
from aigm.world.ops import apply_ops
from aigm.world.passes import run_bootstrap
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService
from tests.test_session_zero import GOOD

MAP = {"name": "the old mine map", "appearance": "a creased sheet of vellum with a hand-drawn plan of the mine",
       "purpose": "The old mine map shows the way to the lower gallery.", "status": "held"}
KEY = {"name": "the cellar key", "appearance": "a small iron key on a leather thong", "status": "known"}


def begin(**extra):
    state = GameState(Phase.SESSION_ZERO)
    state.structure = "endless"
    out = dispatch("begin_adventure", "t", {**GOOD, **extra}, state)
    return state, out


def test_key_items_are_recorded_in_the_campaign():
    state, out = begin(key_items=[MAP, KEY])
    assert not out.is_error, out.content
    items = state.campaign["key_items"]
    assert [(i["name"], i["status"]) for i in items] == [("the old mine map", "held"), ("the cellar key", "known")]
    assert items[1]["purpose"] == ""


def test_a_game_without_key_items_records_none():
    state, out = begin()
    assert not out.is_error and "key_items" not in state.campaign


@pytest.mark.parametrize(
    "item, fragment",
    [
        ({**MAP, "status": "lost"}, "'status' must be held or known"),
        ({**MAP, "appearance": "map"}, "2 to 30 words"),
        ({**MAP, "appearance": "word " * 40}, "2 to 30 words"),
        ({**MAP, "purpose": "no"}, "'purpose'"),
        ({**MAP, "name": ""}, "'name'"),
        ({**MAP, "name": "Ann"}, "already used"),
    ],
)
def test_bad_key_items_are_refused_with_the_reason(item, fragment):
    state, out = begin(key_items=[item])
    assert out.is_error and fragment in out.content and state.phase is Phase.SESSION_ZERO


def test_too_many_or_repeated_key_items_are_refused():
    assert begin(key_items=[MAP] * 2)[1].is_error  # the same name twice
    many = [{**MAP, "name": f"item {n}"} for n in range(5)]
    assert "at most 4" in begin(key_items=many)[1].content
    assert begin(key_items="a map")[1].is_error


def test_the_gms_record_of_session_zero_lists_them():
    state, _ = begin(key_items=[MAP, KEY])
    text = PromptLibrary().campaign_record(state.campaign)
    assert "### Key items" in text and "the party has it" in text and "is looking for" in text
    assert "a creased sheet of vellum" in text
    assert "### Key items" not in PromptLibrary().campaign_record(begin()[0].campaign)


async def seeded_world():
    state, _ = begin(key_items=[MAP, KEY])
    result = await run_bootstrap(state.campaign, [{}], ScriptedCurator())
    world = World()
    apply_ops(world, result.ops)
    return world


async def test_bootstrap_makes_the_held_item_held_and_the_known_one_known_and_awards_nothing():
    world = await seeded_world()
    held, known = world.find("the old mine map"), world.find("the cellar key")
    assert held.holding.status == "held" and held.holding.history[0].turn == 0 and held.holding.owed is None
    assert known.holding.status == "known" and known.holding.owed is None
    assert all(f.learned_seq == 0 for f in world.facts.values() if f.subject in (held.id, known.id))  # nothing is "new"
    texts = [f.text for f in world.facts_about(held.id) if f.disclosure == "known"]
    assert "the old mine map is a creased sheet of vellum with a hand-drawn plan of the mine." in texts
    assert "The old mine map shows the way to the lower gallery." in texts


async def test_they_show_in_the_compendium_from_the_first_moment_and_the_gm_is_told():
    world = await seeded_world()
    rows = {r["name"]: r for r in entries(world, Compendium(), "items")}
    assert rows["the old mine map"]["holding"] == "held" and rows["the cellar key"]["holding"] == "known"
    assert rows["the old mine map"]["status"] is None  # not marked new
    assert detail(world, Compendium(), world.find("the cellar key").id)["look"] is None
    text = build_briefing(world, turn=1)
    assert "Key items the party has:\n- the old mine map" in text and "is looking for" in text
    assert "Unawarded" not in build_briefing(world, turn=1) + build_briefing(world, turn=2)


async def test_the_held_item_is_described_by_the_first_sweep_and_the_known_one_is_not():
    world = await seeded_world()
    session_state = GameState(Phase.ADVENTURE, {"setting": "x"})
    session_state.world = world
    from aigm.session.store import Session

    session = Session("s")
    session.state = session_state
    session_state.turn = 1
    assert await CuratorService(ScriptedCurator()).run_item_looks_if_due(session)
    assert world.find("the old mine map").look is not None and world.find("the cellar key").look is None
