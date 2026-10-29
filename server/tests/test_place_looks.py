"""The Look of a place: validation, who is describable, what the model is shown and the sweep (docs/PLACES.md)."""

import json

import pytest

from aigm.compendium import Compendium, detail
from aigm.looks import PLACE, Look, problems
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.tools import dispatch
from aigm.world import World
from aigm.world.briefing import build_briefing
from aigm.world.curator import CuratorError, PlaceLookRequest
from aigm.world.describe_places import (
    BATCH, MAX_PER_SWEEP, VISUAL_ASPECTS, _subject, describable, needing_places, run_place_looks, too_alike,
)  # fmt: skip
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import LOOK_RETRY_TURNS, CuratorService
from tests.test_looks import make_look

BODY = (
    "{name} is a broad yard of grey gravel ringed by long timber halls with thick turf roofs, some sprouting pale "
    "grass. Smoke leans from stone chimneys and hangs in the cold air. At the center stands a squat stone well capped "
    "with an iron hand-crank, steam curling off the water around it. Beside the well rises a weathered post bristling "
    "with nailed papers gone grey. Hides are stretched on wooden frames along the nearest hall, and a handcart lies "
    "tipped against a trough. Behind the roofs the mountains climb in ragged white and slate. The place is empty and "
    "the light is flat and silver."
)


def make_place_look(name="Icehold Square", **over) -> Look:
    look = Look(
        "A trampled gravel yard ringed by low turf-roofed halls, with a steaming stone well at its center.",
        BODY.format(name=name),
        {"scale": "site", "setting": "urban", "climate": "cold", "architecture": "timber halls, turf roofs",
         "terrain": "trampled gravel", "flora": "pale grass on the roofs", "light": "flat silver",
         "mood": "cold and still", "features": ["stone well", "notice post", "stretched hides"]},
    )  # fmt: skip
    for key, value in over.items():
        setattr(look, key, value)
    return look


def town(world: World | None = None):
    """Icehold, which is known only by rumor, and Icehold Square inside it, which is known by sight."""
    w = world or World()
    region = w.add_entity("Northern Mountains", "location")
    icehold = w.add_entity("Icehold", "location", parent=region.id)
    square = w.add_entity("Icehold Square", "location", parent=icehold.id)
    w.add_fact("The mountains are high and cold.", [region.id], aspect="overview", disclosure="known")
    w.add_fact("Icehold is said to be a hard place.", [icehold.id], aspect="tensions", disclosure="known")
    w.add_fact("A stone well stands at the center of the square.", [square.id], aspect="items", disclosure="known")
    return w, region, icehold, square


# ---- the Look of a place -----------------------------------------------------------------


def test_a_good_place_look_has_no_problems_and_a_persons_tags_are_refused_on_it():
    assert problems(make_place_look(), "Icehold Square", PLACE) == []
    found = problems(make_look("Icehold Square"), "Icehold Square", PLACE)
    assert any("unknown tags" in p and "ancestry" in p for p in found) and any("'scale'" in p for p in found)
    assert any("unknown tags" in p and "scale" in p for p in problems(make_place_look(), "Marta Venn"))


@pytest.mark.parametrize(
    ("change", "expect"),
    [
        ({"tags": {"scale": "planet"}}, "'scale' must be one of"),
        ({"tags": {"scale": "site", "setting": "urban", "climate": "cold", "light": "word " * 13}}, "'light' must be text"),
        ({"tags": {"scale": "site", "setting": "urban", "climate": "cold", "features": ["a"] * 6}}, "'features' must be"),
        ({"description": "Too short."}, "'description' has 2 words"),
        ({"description": BODY.format(name="Icehold Square") + " You can see the party."}, "do not write"),
        ({"description": BODY.format(name="Icehold Square") + " It has 12 hit points."}, "game terms"),
        ({"description": BODY.format(name="Icehold Square") + " A beholder watches."}, "product name"),
        ({"description": BODY.format(name="Somewhere Else")}, "must use the place's name"),
    ],
)
def test_the_content_rules_apply_to_places(change, expect):
    look = make_place_look()
    for key, value in change.items():
        setattr(look, key, value)
    assert any(expect in p for p in problems(look, "Icehold Square", PLACE)), problems(look, "Icehold Square", PLACE)


def test_a_place_may_be_named_loosely_but_a_person_must_be_named_in_full():
    look = make_place_look(name="the pass above the old quarry")
    assert problems(look, "Pass above the old quarry", PLACE) == []
    assert any("name" in p for p in problems(make_place_look(name="Quarry"), "Pass above the old quarry", PLACE))


def test_the_search_text_of_a_place_is_stable_and_names_its_tags():
    text = make_place_look().search_text(PLACE)
    assert text == (
        "site urban cold | A trampled gravel yard ringed by low turf-roofed halls, with a steaming stone well at its "
        "center. | timber halls, turf roofs; trampled gravel; pale grass on the roofs; flat silver; cold and still | "
        "stone well, notice post, stretched hides"
    )
    assert make_place_look().search_text(PLACE) == text


def test_places_that_would_be_painted_alike_are_told_apart():
    a, b = make_place_look(), make_place_look("Elsewhere")
    assert too_alike(a, b)  # the same scale, setting, climate, architecture and terrain
    b.tags["architecture"], b.tags["terrain"] = "white towers", "sea cliff"
    b.summary = "A harbor of white towers above a grey sea."
    assert not too_alike(a, b)


# ---- who is describable ------------------------------------------------------------------


def test_a_place_is_describable_by_a_known_fact_of_a_visual_aspect_about_itself_and_by_nothing_else():
    w, region, icehold, square = town()
    assert describable(w, region) and describable(w, square)  # overview, items
    assert not describable(w, icehold)  # only a rumor: a known fact of the aspect `tensions`
    for aspect in VISUAL_ASPECTS:
        place = w.add_entity(f"Place {aspect}", "location")
        w.add_fact(f"Some fact about {aspect}.", [place.id], aspect=aspect, disclosure="known")
        assert describable(w, place), aspect
    for aspect in (None, "history", "inhabitants", "secret", "hazards", "discovery", "notable_places"):
        place = w.add_entity(f"Other {aspect}", "location")
        w.add_fact("A known fact.", [place.id], aspect=aspect, disclosure="known")
        assert not describable(w, place), aspect


def test_hidden_and_hinted_facts_and_facts_about_something_else_do_not_make_a_place_describable():
    w, region, icehold, square = town()
    vault = w.add_entity("Old Vault", "location")
    w.add_fact("The vault is a round stone chamber.", [vault.id], aspect="overview", disclosure="hidden")
    w.add_fact("Something is whispered about the vault.", [vault.id], aspect="layout", disclosure="hinted")
    assert not describable(w, vault)
    other = w.add_entity("Elsewhere", "location")
    w.add_fact("Elsewhere lies beyond the vault.", [other.id, vault.id], aspect="overview", disclosure="known")
    assert describable(w, other) and not describable(w, vault)  # a mention is not the place's own fact
    npc = w.add_entity("Wren", "npc")
    w.add_fact("Wren is tall and grey.", [npc.id], aspect="appearance", disclosure="known")
    assert not describable(w, npc)  # only places


def test_places_are_described_here_first_then_those_in_the_narration_then_the_newest():
    w = World()
    old = w.add_entity("Old Mill", "location")
    here = w.add_entity("The Flagon", "location")
    named = w.add_entity("Harrow Mine", "location")
    new = w.add_entity("Tallow Row", "location")
    for place in (old, here, named, new):
        w.add_fact(f"{place.name} looks like something.", [place.id], aspect="overview", disclosure="known")
    w.set_scene(here.id, [])
    assert needing_places(w) == ["The Flagon", "Tallow Row", "Harrow Mine", "Old Mill"]  # then the newest first
    assert needing_places(w, "Far off they could see Harrow Mine.")[:2] == ["The Flagon", "Harrow Mine"]
    w.set_look(here.id, make_place_look("The Flagon"))
    assert "The Flagon" not in needing_places(w)


# ---- what the model is shown -------------------------------------------------------------


def test_the_model_is_shown_what_the_player_knows_and_never_a_hidden_fact():
    w, region, icehold, square = town()
    w.add_fact("SECRET: the well hides a smugglers' shaft.", [square.id], aspect="secret", disclosure="hidden")
    w.add_fact("SECRET: the square is watched.", [square.id], aspect="overview", disclosure="hidden")  # even an overview
    w.add_fact("SECRET: a hinted door.", [square.id], aspect="entry", disclosure="hinted")
    w.add_fact("SECRET: the region hides a lich.", [region.id], aspect="secret", disclosure="hidden")
    w.add_fact("A notice post stands beside the well.", [square.id], aspect="items", disclosure="known")
    w.add_fact("Wren runs the square's inn.", [w.add_entity("Wren", "npc").id, square.id], aspect="role", disclosure="known")
    sub = _subject(w, "Icehold Square", "")
    seen = json.dumps([sub.name, sub.facts, sub.context, sub.narration])
    assert "SECRET" not in seen and "smugglers" not in seen and "lich" not in seen
    assert "[items] A stone well stands at the center of the square." in sub.facts
    assert any(f.startswith("[mentioned] Wren runs") for f in sub.facts)
    assert sub.context[0].startswith("Northern Mountains: The mountains are high") and sub.context[1].startswith("Icehold: Icehold is said")


def test_a_parent_the_player_has_not_met_is_not_named_to_the_model():
    w = World()
    unknown = w.add_entity("The Hidden Duchy", "location")  # no known fact: the player does not know it
    mid = w.add_entity("Ashby", "location", parent=unknown.id)
    place = w.add_entity("Ashby Green", "location", parent=mid.id)
    w.add_fact("Ashby is a village.", [mid.id], aspect="overview", disclosure="known")
    w.add_fact("A green with an oak.", [place.id], aspect="overview", disclosure="known")
    w.add_fact("The duchy is secret.", [unknown.id], aspect="overview", disclosure="hidden")
    sub = _subject(w, "Ashby Green", "")
    assert len(sub.context) == 1 and sub.context[0].startswith("Ashby:") and "Duchy" not in json.dumps(sub.context)


def test_the_narration_that_names_a_place_is_passed_on():
    w, _, _, square = town()
    sub = _subject(w, "Icehold Square", "They crossed Icehold Square at dawn. The well was steaming. Nobody spoke.")
    assert sub.narration and "Icehold Square" in sub.narration[0]


# ---- the sweep ---------------------------------------------------------------------------


class Recording(ScriptedCurator):
    def __init__(self):
        super().__init__()
        self.requests: list[PlaceLookRequest] = []

    async def place_look(self, request):
        self.requests.append(request)
        return await super().place_look(request)


async def sweep(world, curator=None, **kw):
    return await run_place_looks(world, {"setting": "A cold north."}, "D&D 5.5e", curator or ScriptedCurator(), **kw)


async def test_the_sweep_describes_describable_places_and_only_those():
    w, region, icehold, square = town()
    curator = Recording()
    result = await sweep(w, curator)
    assert sorted(op.entity for op in result.ops) == ["Icehold Square", "Northern Mountains"]
    assert all(problems(op.look, op.entity, PLACE) == [] for op in result.ops)
    assert "Icehold" not in [op.entity for op in result.ops]
    assert not result.notes and len(curator.requests) == 1 and curator.requests[0].setting == "A cold north."
    assert {op.look.source for op in result.ops} == {"generated"} and {op.look.state for op in result.ops} == {"provisional"}


async def test_the_scripted_places_are_varied_within_a_sweep():
    w = World()
    for n in range(8):
        p = w.add_entity(f"Place Number {n}", "location")
        w.add_fact(f"Place {n} has something to see.", [p.id], aspect="overview", disclosure="known")
    result = await sweep(w)
    assert len(result.ops) == 8
    assert len({op.look.tags["architecture"] for op in result.ops}) > 3


async def test_a_big_catch_up_is_batched_and_capped():
    w = World()
    for n in range(MAX_PER_SWEEP + 5):
        p = w.add_entity(f"Hall {n}", "location")
        w.add_fact(f"Hall {n} stands there.", [p.id], aspect="overview", disclosure="known")
    curator = Recording()
    result = await sweep(w, curator)
    assert len(result.ops) == MAX_PER_SWEEP and len(curator.requests) == -(-MAX_PER_SWEEP // BATCH)
    assert all(len(r.subjects) <= BATCH for r in curator.requests)


async def test_a_rejected_answer_is_retried_once_with_the_reasons():
    class BadFirst(Recording):
        async def place_look(self, request):
            out = await super().place_look(request)
            if len(self.requests) == 1:
                out[0].description = "Far too short."
            return out

    w, _, _, _ = town()
    curator = BadFirst()
    result = await sweep(w, curator)
    assert len(result.ops) == 2 and len(curator.requests) == 2
    retry = curator.requests[1]
    assert len(retry.subjects) == 1 and any("description" in why for why in next(iter(retry.feedback.values())))


async def test_a_place_that_keeps_failing_is_left_for_later_with_a_note():
    class AlwaysBad(ScriptedCurator):
        async def place_look(self, request):
            out = await super().place_look(request)
            out[0].description = "No."
            return out

    w = World()
    p = w.add_entity("Ashby Green", "location")
    w.add_fact("A green lies beside the road.", [p.id], aspect="overview", disclosure="known")
    result = await sweep(w, AlwaysBad())
    assert result.ops == [] and any("no look for Ashby Green" in n for n in result.notes)


@pytest.mark.parametrize("error", [CuratorError("bad json"), RuntimeError("down")])
async def test_a_model_failure_never_raises(error):
    class Down(ScriptedCurator):
        async def place_look(self, request):
            raise error

    w, _, _, _ = town()
    result = await sweep(w, Down())
    assert result.ops == [] and result.notes


async def test_a_curator_without_place_looks_does_nothing():
    class Plain:
        pass

    w, _, _, _ = town()
    assert (await run_place_looks(w, {}, "x", Plain())).ops == []  # type: ignore[arg-type]


async def test_two_alike_places_in_one_sweep_do_not_both_get_the_same_picture():
    class Same(ScriptedCurator):
        async def place_look(self, request):
            return {i: make_place_look(s.name) for i, s in enumerate(request.subjects)}

    w = World()
    for n in ("North Hall", "South Hall"):
        p = w.add_entity(n, "location")
        w.add_fact(f"{n} stands.", [p.id], aspect="overview", disclosure="known")
    result = await sweep(w, Same())
    assert len(result.ops) <= 1  # the second is "too like" the first and is retried, then left for the next sweep


# ---- applying them, and the service ------------------------------------------------------


def adventure(turn=3):
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, {"setting": "A cold north.", "party": [{"name": "Toby Reed", "sheet": "Rogue."}]})
    town(session.state.world)
    session.state.turn = turn
    session.messages = [{"role": "assistant", "content": [{"type": "text", "text": "You reach Icehold Square."}]}]
    return session


async def test_the_service_describes_places_after_a_turn_and_then_goes_quiet():
    session, svc = adventure(), CuratorService(ScriptedCurator())
    assert svc.place_looks_due(session)
    assert await svc.run_place_looks_if_due(session)
    world = session.state.world
    assert world.find("Icehold Square").look is not None and world.find("Northern Mountains").look is not None
    assert world.find("Icehold").look is None  # a rumor only
    assert not svc.place_looks_due(session) and not await svc.run_place_looks_if_due(session)
    assert not session.curating


def test_not_due_in_session_zero_while_busy_or_curating_or_without_support():
    svc = CuratorService(ScriptedCurator())
    assert not svc.place_looks_due(Session("z"))
    for attr in ("busy", "curating"):
        session = adventure()
        setattr(session, attr, True)
        assert not svc.place_looks_due(session)

    class Plain(ScriptedCurator):
        place_look = None  # type: ignore[assignment]

    assert not CuratorService(Plain()).place_looks_due(adventure())


async def test_a_failing_sweep_backs_off_for_a_few_turns():
    class Down(ScriptedCurator):
        async def place_look(self, request):
            raise RuntimeError("down")

    session, svc = adventure(turn=5), CuratorService(Down())
    assert not await svc.run_place_looks_if_due(session)
    assert session.place_looks_retry_turn == 5 + LOOK_RETRY_TURNS and not svc.place_looks_due(session)
    session.state.turn += LOOK_RETRY_TURNS
    assert svc.place_looks_due(session)


async def test_results_for_a_game_that_was_replaced_are_dropped():
    session = adventure()

    class Replacing(ScriptedCurator):
        async def place_look(self, request):
            session.reset_world_work()
            return await super().place_look(request)

    assert not await CuratorService(Replacing()).run_place_looks_if_due(session)
    assert session.state.world.find("Icehold Square").look is None


# ---- what the GM and the player see ------------------------------------------------------


def test_the_gm_is_told_how_the_current_place_looks_in_every_briefing():
    w, _, _, square = town()
    w.set_scene(square.id, [])
    assert "Looks:" not in build_briefing(w)
    w.set_look(square.id, make_place_look())
    text = build_briefing(w)
    assert "Location: Icehold Square" in text and f"  Looks: {make_place_look().summary}" in text
    tiny = build_briefing(w, budget_tokens=1)
    assert "Looks:" in tiny  # not dropped for lack of room: the narration must stay within it


def test_a_place_page_in_the_compendium_carries_its_look_and_recall_shows_all_of_it():
    w, _, _, square = town()
    w.set_look(square.id, make_place_look())
    page = detail(w, Compendium(), square.id)
    assert page["look"] == {"summary": make_place_look().summary, "description": make_place_look().description}
    state = GameState(Phase.ADVENTURE, {"party": []}, w)
    out = dispatch("recall", "t1", {"about": "Icehold Square"}, state)
    assert "Look (what anyone can see; stay within it)" in out.content and "squat stone well" in out.content


def test_a_places_look_is_saved_with_the_world_and_survives_a_copy():
    w, _, _, square = town()
    w.set_look(square.id, make_place_look())
    again = World.from_dict(json.loads(json.dumps(w.to_dict())))
    assert again.find("Icehold Square").look.tags["scale"] == "site"
    assert w.copy().find("Icehold Square").look.description == make_place_look().description


def test_over_http_a_known_place_is_described_and_its_page_shows_it_and_one_known_only_by_an_unaspected_fact_is_not(tmp_path):
    from fastapi.testclient import TestClient

    from aigm.app import create_app
    from aigm.config import Settings
    from tests.conftest import chat

    client = TestClient(create_app(Settings(test_mode=True, test_delay=0, save_dir=tmp_path, _env_file=None)))
    chat(client, "begin")
    chat(client, "look around")
    world = client.app.state.sessions.get("default").state.world
    flagon, marches = world.find("Rusty Flagon"), world.find("The Test Marches")
    assert flagon.look is not None and marches.look is None
    page = client.get(f"/compendium/entities/{flagon.id}").json()
    assert page["look"]["summary"] == flagon.look.summary
    assert client.get(f"/compendium/entities/{marches.id}").json()["look"] is None


def test_every_prompt_the_model_curator_asks_for_exists_and_the_schema_matches_the_tags():
    from aigm.looks import PLACE_CONTROLLED_TAGS, PLACE_LIST_TAGS, PLACE_TEXT_TAGS
    from aigm.prompts import PromptLibrary
    from aigm.world.anthropic_curator import PLACE_LOOK_SCHEMA, AnthropicCurator

    curator = AnthropicCurator(api_key="x", prompts=PromptLibrary())
    assert "describe_place" in curator.system and "painter" in curator.system["describe_place"]
    tags = PLACE_LOOK_SCHEMA["properties"]["looks"]["items"]["properties"]["tags"]["properties"]
    assert set(tags) == {*PLACE_CONTROLLED_TAGS, *PLACE_TEXT_TAGS, *PLACE_LIST_TAGS}
    assert tags["scale"]["enum"] == list(PLACE_CONTROLLED_TAGS["scale"])


# ---- a batch the model cannot answer ------------------------------------------------------


async def test_a_batch_the_model_cannot_answer_is_split_in_two_and_each_half_asked_again():
    class TooMuch(Recording):
        async def place_look(self, request):
            self.requests.append(request)
            if len(request.subjects) > 3:
                raise CuratorError("describe_place: the model stopped with max_tokens")
            return await ScriptedCurator.place_look(self, request)

    w = World()
    for n in range(5):
        p = w.add_entity(f"Mill Number {n}", "location")
        w.add_fact(f"Mill {n} stands there.", [p.id], aspect="overview", disclosure="known")
    curator = TooMuch()
    result = await sweep(w, curator)
    assert len(result.ops) == 5  # all five came through in the end
    assert [len(r.subjects) for r in curator.requests] == [5, 2, 3]  # the whole batch, then each half
    assert any("trying two smaller" in n for n in result.notes)


async def test_a_half_that_fails_too_is_not_split_forever():
    class Never(Recording):
        async def place_look(self, request):
            self.requests.append(request)
            raise CuratorError("describe_place: the model stopped with max_tokens")

    w = World()
    for n in range(4):
        p = w.add_entity(f"Mill Number {n}", "location")
        w.add_fact(f"Mill {n} stands there.", [p.id], aspect="overview", disclosure="known")
    curator = Never()
    result = await sweep(w, curator)
    assert result.ops == [] and len(curator.requests) == 3  # the batch and its two halves, and no more
