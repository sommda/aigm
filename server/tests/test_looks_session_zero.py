import json

from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.characters import detail
from aigm.config import Settings
from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.tools import dispatch
from aigm.world import World
from aigm.world.describe import run_looks
from aigm.world.ops import apply_ops
from aigm.world.passes import run_bootstrap
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService
from tests.conftest import chat
from tests.test_looks import make_look
from tests.test_session_zero import APPEARANCE, GOOD, member

HARLAN = {
    "name": "Harlan Voss",
    "role": "Harlan Voss is the Thorn Guild's tax collector in Ashby.",
    "known": False,
    "appearance": "A heavy man in his fifties with a shaved head and a gold signet ring on his left hand.",
}
WREN = {"name": "Wren", "role": "Wren is the barmaid at the Rusty Flagon.", "known": True}


def begin(**over):
    state = GameState(structure="endless")
    out = dispatch("begin_adventure", "t", {**GOOD, **over}, state)
    return state, out


# ---- begin_adventure -------------------------------------------------------------------------


def test_every_party_member_needs_an_appearance():
    for bad in ({"appearance": "Tall."}, {"appearance": None}, {"appearance": ""}):
        state, out = begin(party=[member(**bad)])
        assert out.is_error and "'appearance' is too thin" in out.content and state.phase is Phase.SESSION_ZERO
    state, out = begin(party=[{k: v for k, v in member().items() if k != "appearance"}])
    assert out.is_error and "party member 1 (Bo)" in out.content


def test_the_appearance_is_kept_in_the_campaign_record():
    state, out = begin()
    assert not out.is_error and state.campaign["party"][0]["appearance"] == APPEARANCE
    assert "**Appearance.** A slight elf" in PromptLibrary().campaign_record(state.campaign)


def test_key_characters_are_recorded_and_shown_to_the_gm():
    state, out = begin(characters=[HARLAN, WREN])
    assert not out.is_error
    assert state.campaign["characters"] == [{**HARLAN}, {**WREN, "appearance": ""}]
    text = PromptLibrary().campaign_record(state.campaign)
    assert "### Key people" in text and "a secret: the player has not been told" in text
    assert "**Wren** (the player has been told of them)" in text and "signet ring" in text
    assert "Key people" not in PromptLibrary().campaign_record(begin()[0].campaign)


def test_key_characters_are_checked():
    bad = {
        "not a list": "Harlan",
        "nine": [{**WREN, "name": f"P{i}", "role": f"P{i} is a person here."} for i in range(9)],
        "no name": [{**WREN, "name": " "}],
        "party name": [{**WREN, "name": "ann", "role": "Ann is the barmaid here."}],
        "twice": [WREN, WREN],
        "role without name": [{**WREN, "role": "The barmaid at the Rusty Flagon."}],
        "role too short": [{**WREN, "role": "Wren."}],
        "known missing": [{k: v for k, v in WREN.items() if k != "known"}],
        "addresses the player": [{**WREN, "role": "Wren will help you at the Rusty Flagon."}],
        "appearance not text": [{**WREN, "appearance": 5}],
        "not an object": ["Wren"],
    }
    for label, characters in bad.items():
        state, out = begin(characters=characters)
        assert out.is_error and state.phase is Phase.SESSION_ZERO, label


def test_the_record_must_still_fit():
    big = {**HARLAN, "appearance": "x" * 31_000}
    assert begin(characters=[big])[1].is_error


# ---- bootstrap and the Looks ----------------------------------------------------------------


def campaign(**over):
    return {**GOOD, "characters": [HARLAN, WREN], **over}


async def test_bootstrap_records_the_key_people_as_written():
    cur = ScriptedCurator()
    result = await run_bootstrap(campaign(gm_notes="[[at: Drowned Lantern:location]]"), [{}, {}, {}], cur)
    world = World()
    assert not apply_ops(world, result.ops).skipped
    harlan, wren = world.find("Harlan Voss"), world.find("Wren")
    assert harlan.kind == wren.kind == "npc"
    facts = {f.text: f for f in world.facts.values() if f.subject in (harlan.id, wren.id)}
    assert facts[HARLAN["role"]].disclosure == "hidden" and facts[HARLAN["role"]].aspect == "role"
    assert facts[WREN["role"]].disclosure == "known" and facts[WREN["role"]].source == "seed"


async def test_bootstrap_tells_the_curator_who_is_already_recorded():
    seen = []

    class Spy(ScriptedCurator):
        async def bootstrap(self, request):
            seen.append(request)
            return await super().bootstrap(request)

    await run_bootstrap(campaign(gm_notes="[[at: Drowned Lantern:location]]"), [{}, {}, {}], Spy())
    assert seen[0].characters == [("Harlan Voss", HARLAN["role"]), ("Wren", WREN["role"])]


async def test_the_players_appearance_is_given_to_the_describer_for_people_and_party():
    world = World()
    apply_ops(world, (await run_bootstrap(campaign(gm_notes="[[at: Drowned Lantern:location]]"), [{}, {}, {}], ScriptedCurator())).ops)
    result = await run_looks(world, campaign(), "D&D", {}, ScriptedCurator())
    harlan = next(op.look for op in result.ops if op.entity == "Harlan Voss")
    assert "gold signet ring" in harlan.description and harlan.source == "session_zero" and harlan.state == "provisional"
    wren = next(op.look for op in result.ops if op.entity == "Wren")
    assert wren.source == "generated"
    ann = result.party["Ann"]
    assert "cropped black hair" in ann.description and (ann.state, ann.source) == ("fixed", "session_zero")


def test_a_new_test_game_has_appearance_looks_end_to_end(tmp_path):
    settings = Settings(test_mode=True, test_delay=0, save_dir=tmp_path, _env_file=None)
    client = TestClient(create_app(settings))
    chat(client, "begin")
    client.put("/history/g/save")
    saved = json.loads((tmp_path / "g.json").read_text())
    hero = saved["looks"]["Test Hero"]
    assert "crooked nose" in hero["description"] and hero["state"] == "fixed" and hero["source"] == "session_zero"


# ---- establish look_notes -------------------------------------------------------------------


def play_state():
    state = GameState(Phase.ADVENTURE, {"setting": "x", "party": [{"name": "Ann", "sheet": "s"}]})
    state.world.add_entity("Ashby", "location")
    return state


def test_look_notes_are_kept_for_the_describer_but_only_for_people():
    state = play_state()
    out = dispatch(
        "establish", "t",
        {"entities": [{"name": "Old Tam", "kind": "npc", "look_notes": "  tall, one-eyed,\n in a guard's tabard "},
                      {"name": "The Mill", "kind": "location", "look_notes": "grey stone"}]},
        state,
    )  # fmt: skip
    assert not out.is_error and state.look_hints == {"old tam": "tall, one-eyed, in a guard's tabard"}
    assert "ignored" in out.content and "The Mill" in out.content
    assert state.world.find("Old Tam").look is None  # the note is not the Look


def test_look_notes_for_a_person_who_exists_but_has_no_look_yet():
    state = play_state()
    tam = state.world.add_entity("Old Tam", "npc")
    dispatch("establish", "t", {"entities": [{"name": "Old Tam", "kind": "npc", "look_notes": "a limp"}]}, state)
    assert state.look_hints == {"old tam": "a limp"}
    state.world.set_look(tam.id, make_look("Old Tam"))
    state.look_hints.clear()
    dispatch("establish", "t", {"entities": [{"name": "Old Tam", "kind": "npc", "look_notes": "a limp"}]}, state)
    assert state.look_hints == {}  # he already has a look


def test_a_rejected_call_keeps_no_hints_and_a_long_note_is_refused():
    state = play_state()
    out = dispatch("establish", "t", {"entities": [{"name": "Old Tam", "kind": "npc", "look_notes": "word " * 41}]}, state)
    assert out.is_error and "look_notes" in out.content and state.look_hints == {}
    assert state.world.find("Old Tam") is None
    out = dispatch(
        "establish", "t",
        {"entities": [{"name": "Old Tam", "kind": "npc", "look_notes": "a limp"}],
         "facts": [{"text": "Old Tam ferries people.", "about": ["Nobody"]}]},
        state,
    )  # fmt: skip
    assert out.is_error and state.look_hints == {}


async def test_the_sweep_uses_the_notes_and_then_forgets_them():
    session = Session("s")
    session.state = play_state()
    session.state.turn = 2
    dispatch("establish", "t", {"entities": [{"name": "Old Tam", "kind": "npc", "look_notes": "a braided silver beard"}]}, session.state)
    assert await CuratorService(ScriptedCurator()).run_looks_if_due(session)
    look = session.state.world.find("Old Tam").look
    assert "braided silver beard" in look.description and look.source == "narration"
    assert session.state.look_hints == {}


def test_hints_survive_the_turns_working_copy_but_are_not_saved():
    state = play_state()
    state.look_hints["old tam"] = "a limp"
    assert state.copy().look_hints == {"old tam": "a limp"}
    assert "look_hints" not in state.to_dict()


# ---- the party page -------------------------------------------------------------------------


def test_a_party_members_page_has_their_look_and_nothing_for_npcs():
    state = GameState(Phase.ADVENTURE, {"setting": "x", "party": [{"name": "Ann", "sheet": "s"}]})
    assert detail(state, "Ann")["look"] is None
    state.set_look("Ann", make_look("Ann"))
    page = detail(state, "Ann")
    assert page["look"] == {"summary": make_look("Ann").summary, "description": make_look("Ann").description}
