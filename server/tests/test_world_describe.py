import copy

import pytest

from aigm.looks import Look, problems
from aigm.prompts import PromptLibrary
from aigm.world import World
from aigm.world.anthropic_curator import LOOK_SCHEMA, parse_looks
from aigm.world.curator import CuratorError, LookRequest, LookSubject
from aigm.world.describe import Given, missing_details, needing, run_looks, too_similar
from aigm.world.ops import SetLook, apply_ops
from aigm.world.render import render_looks
from aigm.world.scripted import ScriptedCurator
from tests.test_looks import make_look
from tests.test_world_curator import curator as model_curator, walk

CAMPAIGN = {
    "setting": "A river town under a grey sky.",
    "party": [
        {"name": "Toby Reed", "sheet": "Human rogue. He is lean.", "background": "A ferryman's son from Ashby."},
        {"name": "Ione", "sheet": "Elf wizard. She reads old maps.", "background": "A scholar of the Thornwood."},
    ],
}


def town():
    world = World()
    ashby = world.add_entity("Ashby", "location")
    marta = world.add_entity("Marta Venn", "npc")
    harlan = world.add_entity("Harlan Voss", "npc")
    wren = world.add_entity("Wren", "npc")
    world.add_fact("Marta Venn keeps the Rusty Flagon.", [marta.id, ashby.id], aspect="role", disclosure="known")
    world.add_fact("Harlan Voss owes the Guild a debt.", [harlan.id], aspect="knowledge")
    world.add_fact("Harlan Voss wears a signet ring on his left hand.", [harlan.id], aspect="appearance")
    world.add_fact("Wren is Marta's niece.", [wren.id], source="background", disclosure="known")
    world.set_scene(ashby.id, [harlan.id])
    return world


# ---- who is described, and in what order ----------------------------------------------------


def test_party_first_then_the_scene_then_recent_narration_then_backgrounds():
    world = town()
    got = needing(world, ["Toby Reed", "Ione"], {}, "Marta Venn waves from behind the bar.")
    assert got == [(True, "Toby Reed"), (True, "Ione"), (False, "Harlan Voss"), (False, "Marta Venn"), (False, "Wren")]


def test_background_people_come_before_the_merely_discovered():
    world = town()
    gus = world.add_entity("Gus", "npc")
    world.add_fact("Gus sells eels.", [gus.id], disclosure="known")
    got = [n for p, n in needing(world, [], {})]
    assert got == ["Harlan Voss", "Wren", "Gus", "Marta Venn"] or got.index("Wren") < got.index("Gus")


def test_those_with_a_look_are_left_out_and_so_are_places():
    world = town()
    world.set_look(world.find("Marta Venn").id, make_look())
    names = [n for _, n in needing(world, ["Toby Reed"], {"Toby Reed": make_look("Toby Reed")})]
    assert "Marta Venn" not in names and "Ashby" not in names and "Toby Reed" not in names


# ---- the sweep -----------------------------------------------------------------------------


async def test_a_sweep_describes_everyone_and_the_ops_apply():
    world, scripted = town(), ScriptedCurator()
    result = await run_looks(world, CAMPAIGN, "D&D", {}, scripted)
    assert set(result.party) == {"Toby Reed", "Ione"} and result.notes == []
    assert all(isinstance(op, SetLook) for op in result.ops) and len(result.ops) == 3
    assert scripted.calls == ["look"]
    for name, look in result.party.items():
        assert problems(look, name) == []
    applied = apply_ops(world, result.ops)
    assert len(applied.ops) == 3 and world.find("Wren").look is not None
    assert result.party["Ione"].tags["ancestry"] == "elf" and result.party["Ione"].tags["gender"] == "feminine"
    assert (await run_looks(world, CAMPAIGN, "D&D", result.party, scripted)).ops == []  # nothing left to do


async def test_a_look_that_exists_is_not_replaced_by_a_set_look_op():
    world = town()
    marta = world.find("Marta Venn")
    world.set_look(marta.id, make_look())
    other = make_look(summary="A different summary entirely.")
    applied = apply_ops(world, [SetLook("Marta Venn", other)])
    assert applied.ops == [] and marta.look.summary != other.summary
    assert len(apply_ops(world, [SetLook("Nobody", other)]).skipped) == 1


async def test_batches_of_six_and_a_limit_per_sweep():
    world = World()
    for i in range(15):
        world.add_entity(f"Person Number{chr(65 + i)}", "npc")
    sizes = []

    class Spy(ScriptedCurator):
        async def look(self, request):
            sizes.append(len(request.subjects))
            return await super().look(request)

    result = await run_looks(world, {"setting": "x"}, "r", {}, Spy())
    assert len(result.ops) == 12 and sizes[:2] == [6, 6]  # a retry of a rejected look may follow
    again = await run_looks(world, {"setting": "x"}, "r", {}, ScriptedCurator(), limit=3)
    assert len(again.ops) == 3


async def test_characters_in_one_sweep_are_different():
    world = town()
    result = await run_looks(world, CAMPAIGN, "D&D", {}, ScriptedCurator())
    looks = [*result.party.values(), *(op.look for op in result.ops)]
    assert not any(too_similar(a, b) for i, a in enumerate(looks) for b in looks[i + 1 :])


async def test_the_players_appearance_is_kept_and_makes_a_fixed_look():
    campaign = copy.deepcopy(CAMPAIGN)
    campaign["party"][0]["appearance"] = "Toby has a broken nose and a bright yellow scarf."
    result = await run_looks(town(), campaign, "D&D", {}, ScriptedCurator())
    toby, ione = result.party["Toby Reed"], result.party["Ione"]
    assert "broken nose" in toby.description and (toby.state, toby.source) == ("fixed", "session_zero")
    assert (ione.state, ione.source) == ("provisional", "generated")


async def test_narration_details_are_kept_and_marked():
    given = {"wren": Given(["a braided silver beard"], "narration", "the narration")}
    result = await run_looks(town(), CAMPAIGN, "D&D", {}, ScriptedCurator(), given=given)
    wren = next(op.look for op in result.ops if op.entity == "Wren")
    assert "braided silver beard" in wren.description and wren.source == "narration"


class Recording:
    """A curator that records its requests and answers from a script."""

    def __init__(self, *answers):
        self.requests, self.answers = [], list(answers)

    async def look(self, request):
        self.requests.append(request)
        answer = self.answers.pop(0) if self.answers else None
        if isinstance(answer, Exception):
            raise answer
        return answer(request) if callable(answer) else (answer or {})


def good(request):
    return {i: make_look(s.name) for i, s in enumerate(request.subjects)}


async def test_the_request_has_facts_with_disclosure_but_only_the_relevant_aspects():
    rec = Recording(good)
    world = town()
    await run_looks(world, {"setting": "A river town."}, "D&D", {}, rec, limit=1)
    (request,) = rec.requests
    (sub,) = request.subjects
    assert sub.name == "Harlan Voss" and not sub.party
    assert "[known]" not in " ".join(sub.facts)
    assert any(f.startswith("[hidden]") and "signet ring" in f for f in sub.facts)
    assert not any("owes the Guild" in f for f in sub.facts)  # a secret is not about appearance
    assert request.setting == "A river town." and request.existing == []


async def test_a_rejected_look_is_asked_for_again_with_the_reasons():
    def bad_then_good(request):
        return {0: make_look("Harlan Voss", summary="")}

    rec = Recording(bad_then_good, good)
    result = await run_looks(town(), {"setting": "x"}, "r", {}, rec, limit=1)
    assert len(result.ops) == 1 and result.notes == []
    retry = rec.requests[1]
    assert [s.name for s in retry.subjects] == ["Harlan Voss"] and "summary" in " ".join(retry.feedback[0])


async def test_after_two_failures_the_character_is_skipped_and_noted():
    rec = Recording(lambda r: {0: make_look("Harlan Voss", summary="")}, lambda r: {})
    result = await run_looks(town(), {"setting": "x"}, "r", {}, rec, limit=1)
    assert result.ops == [] and len(rec.requests) == 2
    assert "no look for Harlan Voss" in result.notes[0] and "summary" in result.notes[0]


async def test_a_curator_failure_never_raises():
    for error in (CuratorError("boom"), RuntimeError("down")):
        result = await run_looks(town(), CAMPAIGN, "r", {}, Recording(error))
        assert result.ops == [] and result.party == {} and "looks skipped" in result.notes[0]


async def test_a_curator_without_looks_does_nothing():
    class Bare:
        pass

    result = await run_looks(town(), CAMPAIGN, "r", {}, Bare())
    assert result.ops == [] and result.notes == []


async def test_a_copy_of_another_character_is_rejected():
    world = World()
    world.add_entity("Ann Mill", "npc")
    world.add_entity("Bob Hill", "npc")

    def twins(request):
        return {i: make_look(s.name) for i, s in enumerate(request.subjects)}

    rec = Recording(twins, lambda r: {0: make_look(r.subjects[0].name, summary="A bald giant with a rusted helm.",
                                                    description=make_look().description.replace("Marta Venn", r.subjects[0].name),
                                                    )})  # fmt: skip
    result = await run_looks(world, {"setting": "x"}, "r", {}, rec)
    assert len(result.ops) == 1 and "too like" in " ".join(rec.requests[1].feedback[0])


async def test_a_look_too_like_one_already_in_the_game_is_rejected():
    world = World()
    marta = world.add_entity("Marta Venn", "npc")
    world.set_look(marta.id, make_look())
    world.add_entity("Ann Mill", "npc")
    rec = Recording(lambda r: {0: make_look("Ann Mill")}, lambda r: {})
    result = await run_looks(world, {"setting": "x"}, "r", {}, rec)
    assert result.ops == [] and "Marta Venn" in result.notes[0]
    assert rec.requests[0].existing == [f"Marta Venn: {make_look().summary}"]


async def test_a_decided_detail_that_is_lost_is_rejected():
    given = {"harlan voss": Given(["a livid scar across the throat"], "narration", "the narration")}
    rec = Recording(lambda r: {0: make_look("Harlan Voss")}, lambda r: {0: make_look("Harlan Voss")})
    result = await run_looks(town(), {"setting": "x"}, "r", {}, rec, given=given, limit=1)
    assert result.ops == [] and "livid scar" in result.notes[0]


def test_missing_details_compare_by_word_stems():
    look = make_look()
    assert missing_details(look, ["white hair tied back"]) == []
    assert missing_details(look, ["a braided beard"]) == ["a braided beard"]
    assert missing_details(look, []) == []


def test_two_looks_with_the_same_tags_and_coloring_are_the_same_person():
    a, b = make_look(), make_look("Other Name")
    assert too_similar(a, b)
    b.summary, b.tags["hair"] = "A square-jawed brawler.", "black"
    assert not too_similar(a, b)


# ---- the model-backed curator ---------------------------------------------------------------


def test_the_look_schema_is_closed_and_uses_only_supported_features():
    walk(LOOK_SCHEMA)


def test_the_describer_prompt_exists():
    text = PromptLibrary().world_prompt("describe")
    assert "never put anything from a hidden fact" in text and "90 to 140 words" in text


def test_render_shows_each_character_with_its_index_and_feedback():
    request = LookRequest(
        [
            LookSubject("Toby Reed", True, sheet="Rogue.", background="A ferryman's son.", given=["a yellow scarf"],
                        given_by="the player in Session 0"),
            LookSubject("Wren", False, aliases=["the barmaid"], facts=["[hidden] Wren is a spy."]),
        ],
        "A river town.", "D&D 5.5 Edition", ["Marta Venn: A stooped old woman."], {1: ["too long"]},
    )  # fmt: skip
    text = render_looks(request)
    assert "### 0: Toby Reed (player character)" in text and "### 1: Wren (person)" in text
    assert "Already decided by the player in Session 0" in text and "- a yellow scarf" in text
    assert "[hidden] Wren is a spy." in text and "- Marta Venn: A stooped old woman." in text
    assert "rejected" in text and "- too long" in text and "D&D 5.5 Edition" in text


def reply(index=0, **over):
    look = make_look()
    item = {"index": index, "summary": look.summary, "description": look.description,
            "tags": {**{k: "" for k in ("skin", "clothing", "expression")}, **look.tags}}  # fmt: skip
    item["tags"].update(over)
    return {"looks": [item]}


async def test_the_anthropic_curator_asks_with_the_schema_and_parses_the_answer():
    cur, messages = model_curator(reply())
    got = await cur.look(LookRequest([LookSubject("Marta Venn", False)], "x", "r"))
    params = messages.calls[0]
    assert params["output_config"]["format"]["schema"] is LOOK_SCHEMA
    assert "costume and portrait designer" in params["system"][0]["text"]
    look = got[0]
    assert look.tags["ancestry"] == "human" and "skin" not in look.tags  # empty tags are dropped
    assert look.tags["marks"] == ["clouded left eye", "tremor in the right hand"]


def test_parse_ignores_what_it_cannot_use():
    good_item = reply()["looks"][0]
    data = {"looks": ["x", {**good_item, "index": 7}, {**good_item, "index": True}, {**good_item, "tags": "no"},
                      {**good_item, "index": 1}, {**good_item, "index": 1}]}  # fmt: skip
    assert list(parse_looks(data, 2)) == [1] and parse_looks({}, 2) == {}
    assert isinstance(parse_looks({"looks": [good_item]}, 1)[0], Look)


# ---- batches run at the same time ---------------------------------------------------------------


async def test_batches_run_concurrently_up_to_the_limit():
    import asyncio

    world = World()
    for i in range(24):
        world.add_entity(f"Person Number{chr(65 + i)}", "npc")
    live, peak = 0, 0

    class Slow(ScriptedCurator):
        async def look(self, request):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.01)
            live -= 1
            return await super().look(request)

    result = await run_looks(world, {"setting": "x"}, "r", {}, Slow(), limit=24)
    assert len(result.ops) >= 20 and 2 <= peak <= 4  # the scripted looks run out of variety near 24


async def test_a_look_too_like_one_from_another_batch_is_described_again():
    world = World()
    for i in range(7):
        world.add_entity(f"Person Number{chr(65 + i)}", "npc")
    calls = []

    class Twins(ScriptedCurator):
        async def look(self, request):
            calls.append([s.name for s in request.subjects])
            if len(calls) <= 2:  # the first round: both batches answer with the same person
                return {i: make_look(s.name) for i, s in enumerate(request.subjects[:1])} | {
                    i: make_look(s.name, summary=f"Someone entirely different number {i} {s.name}",
                                 tags={**make_look().tags, "hair": f"hair {i}{s.name[-1]}", "eyes": f"eyes {s.name[-1]}"})
                    for i, s in enumerate(request.subjects) if i
                }  # fmt: skip
            return await super().look(request)

    result = await run_looks(world, {"setting": "x"}, "r", {}, Twins())
    assert len(result.ops) == 7  # the clash was found across batches and sorted out in the second round
    assert any(len(c) == 1 for c in calls[2:]) or len(calls) > 2
