import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from aigm.game import Game
from aigm.llm.scripted import ScriptedLLM, TEST_CAMPAIGN
from aigm.llm.loop import run_turn
from aigm.world.model import ARRIVAL_ASPECTS
from aigm.models import ErrorEvent, MessageEnd, Status
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.world import World, WorldTime
from aigm.world.anthropic_curator import BOOTSTRAP_SCHEMA, AnthropicCurator
from aigm.world.curator import EntityProposal, Extraction, FactProposal
from aigm.world.ops import StartClock, apply_ops
from aigm.world.passes import PassConfig, run_bootstrap
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService
from aigm.prompts import PromptLibrary
from aigm.world.model import WorldError
from tests.conftest import chat, names, parse_sse
from tests.test_world_curator import FakeCurator, curator as model_curator, walk


def campaign(**kw):
    return {**TEST_CAMPAIGN, **kw}


# ---- the bootstrap pass -------------------------------------------------------------------


async def test_bootstrap_seeds_a_world_with_known_and_hidden_facts_and_expands_the_opening():
    cur = ScriptedCurator()
    progress = []
    result = await run_bootstrap(campaign(), [{}, {}, {}], cur, progress=progress.append)
    world = World()
    assert not apply_ops(world, result.ops).skipped
    assert cur.calls[0] == "bootstrap" and "expand" in cur.calls
    region, flagon = world.find("The Test Marches"), world.find("Rusty Flagon")
    assert region and flagon.parent == region.id and world.find("Innkeeper").kind == "npc"
    assert world.scene.location == flagon.id and world.scene.present == [world.find("Innkeeper").id]
    assert world.time == WorldTime(1, 18) and world.processed_through == 3
    seeds = [f for f in world.facts.values() if f.source == "seed"]
    assert {f.disclosure for f in seeds} == {"known", "hidden"}
    assert any(f.disclosure == "hidden" and "reports every guest" in f.text for f in seeds)
    assert all(f.turn == 0 for f in seeds)
    gen = [f for f in world.facts.values() if f.source == "generated"]
    # what can be seen where the party stands is known; the rest of the expansion is secret
    here = world.scene.location
    assert gen and all(
        f.disclosure == ("known" if f.aspect in ARRIVAL_ASPECTS and f.subject == here else "hidden") for f in gen
    )
    assert progress[0] == "Building the setting..." and any(p.startswith("Detailing ") for p in progress[1:])


async def test_bootstrap_orders_containers_first_and_ignores_a_bad_hour():
    ex = Extraction(
        entities=[
            EntityProposal("Tavern", "location", parent="Town"),
            EntityProposal("Town", "location", parent="Region"),
            EntityProposal("Region", "location"),
        ],
        facts=[FactProposal("The Region is wild and thinly settled.", ["Region"], None, "known"),
               FactProposal("The Tavern is the town's oldest building.", ["Tavern"], "history", "bogus")],
        location="Tavern", start_hour=30,
    )  # fmt: skip
    result = await run_bootstrap(campaign(), [{}], extraction_for_bootstrap(ex), config=PassConfig(max_expand_entities=0))
    world = World()
    assert not apply_ops(world, result.ops).skipped
    assert world.find("Tavern").parent == world.find("Town").id and world.find("Town").parent == world.find("Region").id
    assert world.time == WorldTime(1, 8)  # 30 is not an hour of the day
    assert [f.disclosure for f in world.facts.values()] == ["known", "hidden"]


class _Boot(FakeCurator):
    boot = None

    async def bootstrap(self, request):
        self.requests.append(request)
        return self.boot


def extraction_for_bootstrap(ex):
    cur = _Boot()
    cur.boot = ex
    return cur


async def test_bootstrap_with_nothing_recorded_fails():
    cur = _Boot()
    cur.boot = Extraction()
    with pytest.raises(ValueError, match="recorded nothing"):
        await run_bootstrap(campaign(), [{}], cur)


async def test_bootstrap_request_carries_the_record():
    cur = _Boot()
    cur.boot = Extraction(entities=[EntityProposal("Here", "location")], facts=[FactProposal("Here is a place of note.", ["Here"])], location="Here")
    await run_bootstrap(campaign(), [{}], cur, config=PassConfig(max_expand_entities=0))
    req = cur.requests[0]
    assert req.setting.startswith("The Test Marches") and req.level == 1 and "innkeeper is a spy" in req.gm_notes
    assert req.party[0][0] == "Test Hero" and req.opening.startswith("The party shelters")


async def test_bootstrap_drops_facts_that_address_the_player():
    cur = _Boot()
    cur.boot = Extraction(
        entities=[EntityProposal("Here", "location")],
        facts=[FactProposal("You will love Here.", ["Here"]), FactProposal("Here is a place of note.", ["Here"])],
        location="Here",
    )
    result = await run_bootstrap(campaign(), [{}], cur, config=PassConfig(max_expand_entities=0))
    world = World()
    apply_ops(world, result.ops)
    assert [f.text for f in world.facts.values()] == ["Here is a place of note."]


def test_the_clock_can_only_be_started_on_a_fresh_world():
    w = World()
    w.start_clock(18)
    assert w.time == WorldTime(1, 18)
    w.add_fact("Someplace is far away.", [w.add_entity("Someplace", "location").id])
    with pytest.raises(WorldError):
        w.start_clock(6)
    assert apply_ops(w, [StartClock(5)]).skipped


# ---- in the turn loop ---------------------------------------------------------------------


def make_client(tmp_path, curator=None, **kw):
    settings = Settings(test_mode=True, test_delay=0, save_dir=tmp_path, _env_file=None, **kw)
    return TestClient(create_app(settings, curator=curator))


def test_begin_streams_progress_then_the_opening(tmp_path):
    client = make_client(tmp_path)
    events = chat(client, "begin")
    events = [(n, d) for n, d in events if not (n == "status" and d["stage"] == "tool")]  # tool-call notices
    order = names(events)
    first, last = order.index("status"), len(order) - 1 - order[::-1].index("status")
    assert order.index("tool_call") < first < last < order.index("phase_change") < order.index("message_end")
    statuses = [d for n, d in events if n == "status"]
    assert statuses[0] == {"stage": "world", "message": "Preparing the world...", "done": False}
    assert statuses[-1] == {"stage": "world", "message": "The world is ready.", "done": True}
    assert [s["done"] for s in statuses].count(True) == 1 and any("Detailing" in s["message"] for s in statuses)
    opening = "".join(d["delta"] for n, d in events[last:] if n == "text")
    assert "The adventure begins" in opening  # the first scene comes after the world is ready


def test_the_seeded_world_is_in_the_saved_game_and_the_notes_leave_the_prompt(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    client.put("/history/g/save")
    saved = json.loads((tmp_path / "g.json").read_text())
    world = saved["world"]
    assert world["time"] == {"day": 1, "hour": 18} and world["processed_through"] == 3
    names_ = {e["name"] for e in world["entities"]}
    assert {"The Test Marches", "Rusty Flagon", "Innkeeper"} <= names_
    assert any("reports every guest to the baron" in f["text"] and f["disclosure"] == "hidden" for f in world["facts"])
    state = GameState.from_dict(saved)
    assert "## GM notes" not in Game().system(state)  # the notes now live in the world
    assert "## GM notes" in Game().system(GameState(Phase.ADVENTURE, state.campaign))  # no world: still given


def test_without_a_curator_the_notes_stay_in_the_prompt_and_no_status_is_sent(tmp_path):
    client = make_client(tmp_path)
    client.app.state.curator = None
    events = chat(client, "begin")
    assert not [d for n, d in events if n == "status" and d["stage"] == "world"] and "phase_change" in names(events)
    client.put("/history/n/save")
    assert json.loads((tmp_path / "n.json").read_text())["world"]["entities"] == []


class Exploding(ScriptedCurator):
    fail = True

    async def bootstrap(self, request):
        if self.fail:
            raise RuntimeError("model down")
        return await super().bootstrap(request)


def test_a_failed_bootstrap_rolls_the_whole_turn_back_and_can_be_retried(tmp_path):
    cur = Exploding()
    client = make_client(tmp_path, CuratorService(cur))
    events = chat(client, "begin")
    assert names(events)[-1] == "error" and "phase_change" not in names(events)
    err = events[-1][1]
    assert err["code"] == "upstream_error" and err["retryable"] is True and "world could not be prepared" in err["message"]
    state = client.get("/chat/history").json()
    assert state["phase"] == "session_zero" and state["campaign"] is None and state["messages"] == []
    client.put("/history/r/save")
    assert json.loads((tmp_path / "r.json").read_text())["world"]["facts"] == []
    cur.fail = False
    events = chat(client, "begin")
    assert names(events)[-1] == "message_end" and client.get("/chat/history").json()["phase"] == "adventure"


async def test_closing_the_stream_mid_bootstrap_cancels_the_work():
    started, cancelled = asyncio.Event(), asyncio.Event()

    class Slow(ScriptedCurator):
        async def bootstrap(self, request):
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

    session = Session("s")
    gen = run_turn(session=session, user_text="begin", llm=ScriptedLLM(delay=0), game=Game(), max_iters=4, curator=CuratorService(Slow()))
    statuses = 0
    async for ev in gen:
        if isinstance(ev, Status) and ev.stage == "world":
            statuses += 1
            if statuses == 2:  # "Building the setting...": the curator is now running
                await asyncio.wait_for(started.wait(), 5)
                break
    await gen.aclose()
    await asyncio.wait_for(cancelled.wait(), 5)
    assert session.state.phase is Phase.SESSION_ZERO and session.messages == []


async def test_a_turn_without_a_phase_change_never_seeds():
    cur = ScriptedCurator()
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, campaign())
    events = [e async for e in run_turn(session=session, user_text="echo hi", llm=ScriptedLLM(delay=0), game=Game(), max_iters=4, curator=CuratorService(cur))]
    assert isinstance(events[-1], MessageEnd) and "bootstrap" not in cur.calls


def test_the_first_scene_is_written_with_the_seeded_world_in_view(tmp_path):
    seen = []

    class Spy(ScriptedLLM):
        async def stream(self, *, system, messages, tools):
            seen.append(messages[-1]["content"][-1].get("text", ""))
            async for ev in super().stream(system=system, messages=messages, tools=tools):
                yield ev

    settings = Settings(test_mode=True, test_delay=0, save_dir=tmp_path, _env_file=None)
    client = TestClient(create_app(settings, llm=Spy(delay=0), curator=CuratorService(ScriptedCurator())))
    chat(client, "begin")
    assert seen[-1].startswith("<world_notes>") and "Rusty Flagon" in seen[-1] and "reports every guest" in seen[-1]
    assert "Time: Day 1, 18:00 (evening)" in seen[-1]


# ---- the model-backed bootstrap -----------------------------------------------------------


def test_bootstrap_schema_is_closed():
    walk(BOOTSTRAP_SCHEMA)


async def test_model_bootstrap_request_and_parsing():
    reply = {
        "entities": [{"name": "Dunmere", "kind": "location", "aliases": [], "parent": None}],
        "facts": [{"text": "Dunmere is a river town.", "about": ["Dunmere"], "aspect": "layout", "disclosure": "known", "evidence": "q"},
                  {"text": "The mayor of Dunmere is a vampire.", "about": ["Dunmere"], "aspect": None, "disclosure": "hidden", "evidence": ""}],
        "location": "Dunmere", "present": None, "start_hour": 18,
    }  # fmt: skip
    cur, calls = model_curator(reply)
    from aigm.world.curator import BootstrapRequest

    out = await cur.bootstrap(BootstrapRequest("A river land.", "At dusk.", 3, [("Ana", "A rogue.")], "The mayor is a vampire."))
    (params,) = calls.calls
    assert params["model"] == "claude-haiku-5-5" and params["output_config"]["format"]["schema"] == BOOTSTRAP_SCHEMA
    assert params["system"][0]["text"] == PromptLibrary().world_prompt("bootstrap")
    text = params["messages"][0]["content"]
    assert "## Setting\nA river land." in text and "### Ana\nA rogue." in text and "level 3" in text and "The mayor is a vampire." in text
    assert out.location == "Dunmere" and out.present is None and out.start_hour == 18
    assert [f.disclosure for f in out.facts] == ["known", "hidden"]


def test_the_bootstrap_prompt_exists():
    assert "GM notes" in PromptLibrary().world_prompt("bootstrap")
