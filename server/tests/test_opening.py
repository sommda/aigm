"""What the characters already know, and the opening (docs/OPENING.md)."""

import json

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.compendium import Compendium, detail, entries, unseen_totals
from aigm.config import Settings
from aigm.llm.scripted import TEST_CAMPAIGN
from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch
from aigm.world import World
from aigm.world.briefing import build_briefing
from aigm.world.curator import EntityProposal, Extraction, FactProposal
from aigm.world.ops import apply_ops
from aigm.world.passes import PassConfig, run_backfill, run_bootstrap
from aigm.world.scripted import ScriptedCurator
from tests.conftest import chat
from tests.test_session_zero import BACKGROUND, GOOD, SHEET

PARTY = [
    {"name": "Toby", "sheet": SHEET, "background": "Known as the Ghost of the Docks. [[knows: The Docks:location | "
     "The docks of Droon are run by the Silt-Walkers, a guild of dock laborers.]] [[knows: Mags the Fence:npc | "
     "Mags the Fence buys anything that fell off a ship and asks no questions.]]"},
    {"name": "Galvin", "sheet": SHEET, "background": "Raised in the royal chapel. [[knows: The Chapel Royal:location | "
     "The Chapel Royal stands inside the castle walls and serves the court.]]"},
    {"name": "Narvin", "sheet": SHEET, "background": ""},
]


def record(**kw):
    return {**TEST_CAMPAIGN, "party": PARTY, **kw}


async def seeded(cur=None, **kw):
    cur = cur or ScriptedCurator()
    result = await run_bootstrap(record(**kw), [{}, {}, {}], cur)
    world = World()
    assert not apply_ops(world, result.ops).skipped
    return world, cur, result


# ---- begin_adventure ----------------------------------------------------------------------


def test_every_party_member_needs_a_background():
    state = GameState(structure="endless")
    thin = dict(GOOD, party=[{"name": "Ann", "sheet": SHEET, "background": "short"}])
    out = dispatch("begin_adventure", "t", thin, state)
    assert out.is_error and "background" in out.content and state.phase is Phase.SESSION_ZERO
    missing = dict(GOOD, party=[{"name": "Ann", "sheet": SHEET}])
    assert dispatch("begin_adventure", "t", missing, state).is_error


def test_the_background_is_in_the_campaign_record_when_there_is_one():
    lib = PromptLibrary()
    text = lib.campaign_record({**TEST_CAMPAIGN, "party": [{"name": "Ann", "sheet": SHEET, "background": BACKGROUND}]})
    assert f"**Background.** {BACKGROUND}" in text
    old = lib.campaign_record({**TEST_CAMPAIGN, "party": [{"name": "Ann", "sheet": SHEET}]})
    assert "Background" not in old


def test_the_prompts_ask_for_backgrounds_and_the_two_part_opening():
    lib = PromptLibrary()
    assert "background" in lib.system_prompt("session_zero").lower()
    role = lib.system_prompt("adventure")
    assert "overview of the setting" in role and "80 to 150 words" in role
    assert "overview" in lib.begin_cue()
    assert "familiarity" in lib.world_prompt("familiarity").lower() or "already know" in lib.world_prompt("familiarity")


# ---- the familiarity pass -----------------------------------------------------------------


async def test_what_the_characters_know_is_known_attributed_and_new():
    world, cur, _ = await seeded()
    assert "familiarity" in cur.calls and cur.calls.index("familiarity") < cur.calls.index("expand")
    docks = world.find("The Docks")
    assert docks.discovered and docks.parent == world.find("The Test Marches").id
    fact = next(f for f in world.facts.values() if "Silt-Walkers" in f.text)
    assert (fact.disclosure, fact.source, fact.via) == ("known", "background", ("Toby",))
    assert fact.learned_seq > 0  # new to the player, though not to the characters
    seed = next(f for f in world.facts.values() if f.source == "seed" and f.disclosure == "known")
    assert seed.learned_seq == 0 and seed.via == ()


async def test_the_compendium_shows_it_as_new_until_seen():
    world, _, _ = await seeded()
    comp = Compendium()
    names = {r["name"]: r["status"] for cat in ("locations", "characters") for r in entries(world, comp, cat)}
    assert names["The Docks"] == "new" and names["Mags the Fence"] == "new" and names["The Test Marches"] is None
    assert unseen_totals(world, comp)["new"] >= 3
    body = detail(world, comp, world.find("The Docks").id)
    assert body["facts"][0]["via"] == ["Toby"] and body["facts"][0]["new"] is True
    comp.mark_seen(world, [world.find("The Docks").id])
    assert detail(world, comp, world.find("The Docks").id)["status"] is None


async def test_only_party_names_appear_in_via_and_the_hidden_stay_hidden():
    world, _, _ = await seeded()
    comp = Compendium()
    party = {"Toby", "Galvin", "Narvin"}
    for cat in ("locations", "characters", "other"):
        for row in entries(world, comp, cat):
            for fact in detail(world, comp, row["id"])["facts"]:
                assert set(fact["via"]) <= party
                assert "reports every guest" not in fact["text"]


class Odd:
    """A curator whose familiarity answer is whatever the test hands it; the rest is scripted."""

    def __init__(self, *answers, fail=False):
        self.inner, self.answers, self.fail, self.asked = ScriptedCurator(), list(answers), fail, []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def familiarity(self, request):
        self.asked.append(request)
        if self.fail:
            raise RuntimeError("boom")
        return self.answers.pop(0) if self.answers else Extraction()


def answer(*facts, entities=()):
    return Extraction(entities=list(entities), facts=list(facts))


async def test_bad_facts_are_dropped_and_good_ones_kept():
    good = FactProposal("Mags the Fence buys what fell off a ship.", ["Mags the Fence"], "role", "hidden", via=["toby", "Nobody"])
    named = FactProposal("Toby once robbed Mags the Fence.", ["Mags the Fence"], None, "known", via=["Toby"])
    second = FactProposal("You know Mags the Fence.", ["Mags the Fence"], None, "known", via=["Toby"])
    lost = FactProposal("A fact about a thing nobody listed.", ["Ghost Thing"], None, "known", via=["Toby"])
    cur = Odd(answer(good, named, second, lost, entities=[EntityProposal("Mags the Fence", "npc")]))
    world, _, result = await seeded(cur)
    fact = next(f for f in world.facts.values() if "Mags" in f.text)
    assert fact.disclosure == "known" and fact.via == ("Toby",)  # never hidden; names fixed up; strangers dropped
    assert [f.text for f in world.facts.values() if f.source == "background"] == [good.text]
    assert sum("dropped familiar fact" in n for n in result.notes) == 3


async def test_a_member_with_a_background_but_no_facts_is_asked_for_once():
    first = answer(FactProposal("The docks are loud.", ["The Docks"], None, "known", via=["Toby"]),
                   entities=[EntityProposal("The Docks", "location")])
    cur = Odd(first)  # the second answer is empty
    world, _, _ = await seeded(cur)
    assert len(cur.asked) == 2 and cur.asked[1].only == ["Galvin"]  # Narvin has no background: not asked for
    assert world.find("The Docks")


async def test_caps_hold():
    ents = [EntityProposal(f"Place {i}", "location") for i in range(10)]
    facts = [FactProposal(f"Place {i} is a known landmark.", [f"Place {i}"], None, "known", via=["Toby"]) for i in range(10)]
    world = World()
    cur = Odd(answer(*facts, entities=ents), answer())
    result = await run_bootstrap(record(), [{}], cur, config=PassConfig(familiar_entities=3, familiar_facts=4))
    apply_ops(world, result.ops)
    assert len([e for e in world.entities.values() if e.name.startswith("Place ")]) == 3
    assert len([f for f in world.facts.values() if f.source == "background"]) <= 4


async def test_a_failed_familiarity_pass_does_not_fail_the_bootstrap():
    world, _, result = await seeded(Odd(fail=True))
    assert world.find("Rusty Flagon") and not [f for f in world.facts.values() if f.source == "background"]
    assert any("familiarity skipped" in n for n in result.notes)


async def test_a_game_with_no_backgrounds_still_bootstraps():
    cur = ScriptedCurator()
    result = await run_bootstrap(
        {**TEST_CAMPAIGN, "party": [{"name": "Test Hero", "sheet": SHEET}]}, [{}], cur
    )
    assert result.ops and cur.calls.count("familiarity") >= 1


# ---- the model, the briefing, saving -------------------------------------------------------


def test_the_briefing_says_whose_knowledge_it_is():
    w = World()
    place = w.add_entity("The Docks", "location")
    w.scene.location = place.id
    w.add_fact("The Silt-Walkers run the docks.", [place.id], disclosure="known", source="background", via=["Toby"])
    w.add_fact("Gulls nest on the cranes.", [place.id], disclosure="known", source="background", via=["Toby", "Galvin"])
    w.add_fact("The quay floods at spring tide.", [place.id], disclosure="known")
    text = build_briefing(w)
    assert "The Silt-Walkers run the docks. (Toby knows this)" in text
    assert "(Toby, Galvin know this)" in text
    assert "floods at spring tide.\n" in text + "\n"


def test_via_survives_saving_and_old_worlds_load_without_it():
    w = World()
    place = w.add_entity("The Docks", "location")
    w.add_fact("The Silt-Walkers run the docks.", [place.id], disclosure="known", source="background", via=["Toby"])
    data = json.loads(json.dumps(w.to_dict()))
    assert World.from_dict(data).facts["f0001"].via == ("Toby",)
    for raw in data["facts"]:
        del raw["via"]
    assert World.from_dict(data).facts["f0001"].via == ()
    data["facts"][0]["via"] = [3]
    with pytest.raises(Exception):
        World.from_dict(data)


# ---- the backfill ---------------------------------------------------------------------------


async def test_backfill_adds_to_an_existing_world_without_touching_it():
    world, _, _ = await seeded(Odd())  # a world made without any familiarity
    before = len(world.facts)
    campaign = record()
    result = await run_backfill(world, campaign, ScriptedCurator())
    assert len(world.facts) == before  # the world given is untouched
    assert not apply_ops(world, result.ops).skipped
    assert any(f.via == ("Toby",) for f in world.facts.values())
    again = await run_backfill(world, campaign, ScriptedCurator())
    assert not [o for o in again.ops if type(o).__name__ == "AddFact"]  # a second run finds nothing new


def make_app(tmp_path, **kw):
    settings = Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None, **kw)
    return create_app(settings)


def test_the_backfill_route_is_debug_only_and_marks_the_facts_new(tmp_path):
    client = TestClient(make_app(tmp_path, debug=True))
    assert client.post("/debug/backfill", json={}).status_code == 409  # no adventure yet
    chat(client, "structure endless")
    chat(client, "begin")
    session = client.app.state.sessions.get("default")
    session.state.campaign["party"][0].pop("background", None)
    body = client.post(
        "/debug/backfill",
        json={"backgrounds": {"test hero": "A marsh guide. [[knows: Fen Road:location | The Fen Road runs between the inns.]]"}},
    ).json()
    assert body["facts_added"] == 1 and body["compendium"]["new"] >= 1
    assert session.state.campaign["party"][0]["background"].startswith("A marsh guide")
    assert client.app.state.sessions.get("default").state.world.find("Fen Road")
    plain = TestClient(make_app(tmp_path / "plain"))
    assert plain.post("/debug/backfill", json={}).status_code == 404


def test_the_scripted_game_starts_with_a_populated_compendium(tmp_path):
    client = TestClient(make_app(tmp_path))
    chat(client, "structure endless")
    chat(client, "begin")
    body = client.get("/compendium/characters").json()
    tam = next(e for e in body["entries"] if e["name"] == "Old Tam")
    assert tam["status"] == "new"
    assert client.get(f"/compendium/entities/{tam['id']}").json()["facts"][0]["via"] == ["Test Hero"]


# ---- the model-driven curator -----------------------------------------------------------------


async def test_the_model_curator_asks_with_the_familiarity_prompt_and_reads_via():
    from aigm.world.anthropic_curator import FAMILIARITY_SCHEMA
    from aigm.world.curator import FamiliarityRequest
    from tests.test_world_curator import curator as model_curator, walk

    walk(FAMILIARITY_SCHEMA)
    reply = {
        "entities": [{"name": "The Docks", "kind": "location", "aliases": [], "parent": None}],
        "facts": [{"text": "The Silt-Walkers run the docks.", "about": ["The Docks"], "aspect": None, "via": ["Toby"]}],
    }
    cur, fake = model_curator(reply, expand_model="the-strong-one")
    request = FamiliarityRequest("A port.", "At the pier.", 1, [("Toby", "sheet", "Ghost of the Docks")], [], [], "notes")
    out = await cur.familiarity(request)
    assert out.facts[0].via == ["Toby"] and out.facts[0].disclosure == "known"
    call = fake.calls[0]
    assert call["model"] == "the-strong-one" and "Ghost of the Docks" in call["messages"][0]["content"]
    assert "player characters" in call["system"][0]["text"].lower()
