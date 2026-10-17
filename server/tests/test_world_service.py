import asyncio

import pytest

from aigm.config import Settings
from aigm.game import Game
from aigm.llm.base import Completed, TextChunk
from aigm.llm.loop import run_turn
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.tools import dispatch
from aigm.world import World, WorldTime
from aigm.world.briefing import build_briefing
from aigm.world.curator import Extraction
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService
from tests.conftest import chat, reply_text
from tests.test_world_pass import FakeCurator


def adventure(pages_text="", turns=1):
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, {"setting": "A grim border region."})
    w = session.state.world
    w.set_scene(w.add_entity("Ashby", "location").id)
    for i in range(turns):
        session.messages += [
            {"role": "user", "content": [{"type": "text", "text": f"go {i}"}]},
            {"role": "assistant", "content": [{"type": "text", "text": pages_text}]},
        ]
    return session


def service(curator=None, **kw):
    kw.setdefault("page_chars", 100)
    return CuratorService(curator or ScriptedCurator(), **kw)


# ---- when a pass is due --------------------------------------------------------------------


def test_due_only_after_enough_narration():
    svc = service(every_pages=3)
    assert not svc.due(adventure("x" * 100, turns=2))  # 2 pages
    assert svc.due(adventure("x" * 100, turns=3))  # 3 pages
    assert svc.pages(adventure("x" * 150, turns=2)) == 3.0


def test_short_exchanges_do_not_trigger_even_over_many_turns():
    assert not service(every_pages=3).due(adventure("ok.", turns=50))


def test_pages_count_from_processed_through():
    s = adventure("x" * 100, turns=4)
    s.state.world.mark_processed(4)
    svc = service(every_pages=3)
    assert svc.pages(s) == 2.0 and not svc.due(s)


def test_not_due_in_session_zero_while_busy_or_already_running():
    svc = service(every_pages=1)
    s = adventure("x" * 100, turns=3)
    assert svc.due(s)
    s.busy = True
    assert not svc.due(s)
    s.busy, s.curating = False, True
    assert not svc.due(s)
    s.curating, s.state.phase = False, Phase.SESSION_ZERO
    assert not svc.due(s)


def test_a_lookup_miss_requests_a_pass_after_one_page_regardless_of_the_threshold():
    svc = service(every_pages=3)
    s = adventure("x" * 100, turns=1)
    assert not svc.due(s)
    out = dispatch("recall", "t", {"about": "Karth"}, s.state)
    assert "Nothing is recorded" in out.content and s.state.pass_requested
    assert svc.due(s)
    s2 = adventure("x" * 20, turns=1)  # nothing much to digest yet
    dispatch("recall", "t", {"about": "Karth"}, s2.state)
    assert not svc.due(s2)
    s3 = adventure("x" * 100, turns=1)
    dispatch("recall", "t", {"query": "dragons"}, s3.state)  # a search miss is not a request
    assert not s3.state.pass_requested


# ---- running ------------------------------------------------------------------------------


async def test_a_pass_updates_the_world_and_the_marker():
    s = adventure("[[fact: Wren | Wren runs the Rusty Flagon in Ashby.]]" + "x" * 100, turns=3)
    cur = ScriptedCurator()
    assert await service(cur, every_pages=1).run_if_due(s)
    w = s.state.world
    assert w.find("Wren") and w.processed_through == len(s.messages)
    assert "expand" in cur.calls and not s.curating and not s.pending
    assert not await service(cur, every_pages=1).run_if_due(s)  # nothing new to digest


async def test_a_failed_pass_changes_nothing_and_is_retried():
    class Flaky(FakeCurator):
        fail = True

        async def extract(self, request):
            if self.fail:
                raise RuntimeError("model down")
            return Extraction()

    s = adventure("x" * 100, turns=3)
    cur = Flaky()
    svc = service(cur, every_pages=1)
    before = s.state.world.to_dict()
    assert not await svc.run_if_due(s)
    assert s.state.world.to_dict() == before and s.state.world.processed_through == 0 and not s.curating
    cur.fail = False
    assert await svc.run_if_due(s) and s.state.world.processed_through == len(s.messages)


class Gate(ScriptedCurator):
    """Holds extraction until the test lets it go."""

    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def extract(self, request):
        self.started.set()
        await self.release.wait()
        return await super().extract(request)


async def test_the_gm_can_record_facts_while_a_pass_runs_and_both_survive():
    s = adventure("[[fact: Wren | Wren runs the Rusty Flagon in Ashby.]]" + "x" * 100, turns=3)
    gate = Gate()
    task = asyncio.create_task(service(gate, every_pages=1).run_if_due(s))
    await gate.started.wait()
    assert s.curating
    # a turn commits meanwhile: the GM establishes a person and the session state is replaced
    state = s.state.copy()
    dispatch("establish", "t", {"entities": [{"name": "Fenn", "kind": "npc"}],
                                "facts": [{"text": "Fenn trades furs in Ashby.", "about": ["Fenn", "Ashby"]}]}, state)  # fmt: skip
    s.state = state
    gate.release.set()
    assert await task
    w = s.state.world
    assert w.find("Fenn") and w.find("Wren")
    assert any("Fenn trades furs" in f.text for f in w.facts.values())
    assert any("Wren runs the Rusty Flagon" in f.text for f in w.facts.values())


async def test_the_same_fact_recorded_by_both_is_kept_once():
    s = adventure("[[fact: Wren | Wren runs the Rusty Flagon in Ashby.]]" + "x" * 100, turns=3)
    gate = Gate()
    task = asyncio.create_task(service(gate, every_pages=1).run_if_due(s))
    await gate.started.wait()
    state = s.state.copy()
    dispatch("establish", "t", {"entities": [{"name": "Wren", "kind": "npc"}],
                                "facts": [{"text": "Wren runs the Rusty Flagon in Ashby.", "about": ["Wren"]}]}, state)  # fmt: skip
    s.state = state
    gate.release.set()
    await task
    assert [f.text for f in s.state.world.facts.values() if "Rusty Flagon" in f.text] == [
        "Wren runs the Rusty Flagon in Ashby."
    ]
    assert len([e for e in s.state.world.entities.values() if e.name == "Wren"]) == 1


async def test_results_wait_for_an_idle_session_and_land_at_the_start_of_the_next_turn():
    s = adventure("[[fact: Wren | Wren runs the Rusty Flagon in Ashby.]]" + "x" * 100, turns=3)
    gate = Gate()
    task = asyncio.create_task(service(gate, every_pages=1).run_if_due(s))
    await gate.started.wait()
    s.busy = True  # a turn is running when the pass finishes
    gate.release.set()
    await task
    assert s.state.world.find("Wren") is None and len(s.pending) == 1

    class Quiet:
        async def stream(self, *, system, messages, tools):
            yield TextChunk("ok")
            yield Completed([{"type": "text", "text": "ok"}], "end_turn")

    s.busy = True
    seen = []
    _ = [e async for e in run_turn(session=s, user_text="hi", llm=Quiet(), game=Game(), max_iters=2)]
    assert s.state.world.find("Wren") and not s.pending


async def test_a_pass_for_a_replaced_game_is_discarded():
    s = adventure("[[fact: Wren | Wren runs the Rusty Flagon in Ashby.]]" + "x" * 100, turns=3)
    gate = Gate()
    task = asyncio.create_task(service(gate, every_pages=1).run_if_due(s))
    await gate.started.wait()
    s.reset_world_work()  # /chat/new or a restore
    s.messages, s.state = [], GameState()
    gate.release.set()
    assert not await task
    assert s.state.world.is_empty and not s.pending


# ---- corrections reach the GM exactly once ------------------------------------------------


def test_corrections_appear_in_the_briefing():
    w = World()
    w.set_scene(w.add_entity("Ashby", "location").id)
    w.add_correction("The player was told: Ashby is a market town. Treat that as true.", 4)
    w.add_correction("The player was told: Ashby is a market town. Treat that as true.", 4)  # not repeated
    text = build_briefing(w)
    assert text.count("Treat that as true") == 1 and "Corrections (" in text


async def test_a_correction_is_shown_in_one_turn_and_then_cleared():
    s = adventure("hello", turns=1)
    s.state.world.add_correction("The player was told X. Treat that as true.", 1)
    sent = []

    class Spy:
        async def stream(self, *, system, messages, tools):
            sent.append(messages[-1]["content"][-1]["text"])
            yield TextChunk("ok")
            yield Completed([{"type": "text", "text": "ok"}], "end_turn")

    for _ in range(2):
        _ = [e async for e in run_turn(session=s, user_text="hi", llm=Spy(), game=Game(), max_iters=2)]
    assert "Treat that as true" in sent[0] and "Treat that as true" not in sent[1]
    assert s.state.world.corrections == []


async def test_a_correction_queued_by_a_failing_turn_is_not_lost():
    s = adventure("hello", turns=1)
    s.state.world.add_correction("The player was told X. Treat that as true.", 1)

    class Dies:
        async def stream(self, *, system, messages, tools):
            raise RuntimeError("x")
            yield

    _ = [e async for e in run_turn(session=s, user_text="hi", llm=Dies(), game=Game(), max_iters=2)]
    assert len(s.state.world.corrections) == 1


# ---- persistence of the new world fields --------------------------------------------------


def test_reported_hours_and_corrections_round_trip():
    w = World()
    w.advance_time(3, reported=True)
    w.advance_time(1)
    w.add_correction("note", 2)
    again = World.from_dict(w.to_dict())
    assert again == w and again.reported_hours == 3 and again.corrections == [{"text": "note", "turn": 2}]
    assert w.settle_reported_hours(5) == 2 and w.time == WorldTime(1, 14) and w.reported_hours == 0


# ---- over HTTP, in test mode --------------------------------------------------------------


@pytest.fixture
def eager(tmp_path):
    from fastapi.testclient import TestClient

    from aigm.app import create_app

    settings = Settings(test_mode=True, test_delay=0, save_dir=tmp_path / "saves", world_every_pages=0.05, world_page_chars=100, _env_file=None)
    return TestClient(create_app(settings))


def test_the_curator_runs_after_the_reply_and_expands_the_world(eager):
    chat(eager, "begin")
    reply = reply_text(chat(eager, "echo [[fact: Wren:npc | Wren tends the bar at the Rusty Flagon.]] [[at: Rusty Flagon]] [[elapsed: 2]] " + "x" * 120))
    assert "Wren tends the bar" in reply
    eager.put("/history/c/save")
    info = eager.get("/history/c").json()
    assert info["entity_count"] >= 3 and info["fact_count"] >= 3
    assert info["world_time"] == {"day": 1, "hour": 20}  # opens at 18:00, plus 2 hours
    assert "Wren tends the bar" in reply_text(chat(eager, "recall Wren"))
    assert "Rusty Flagon" in reply_text(chat(eager, "recall Rusty Flagon"))


def test_no_curation_in_session_zero_or_below_the_threshold(client):
    chat(client, "echo [[fact: Wren | Wren tends the bar at the Rusty Flagon.]]")
    client.put("/history/z/save")
    assert client.get("/history/z").json()["fact_count"] == 0
    chat(client, "begin")
    client.put("/history/a/save")
    seeded = client.get("/history/a").json()["fact_count"]
    assert seeded > 0  # the world was seeded when the adventure began
    chat(client, "echo [[fact: Wren | Wren tends the bar at the Rusty Flagon.]]")  # far under three pages
    client.put("/history/b/save", params={"overwrite": True})
    client.put("/history/a/save", params={"overwrite": True})
    assert client.get("/history/a").json()["fact_count"] == seeded


def test_new_game_forgets_curator_work(eager):
    chat(eager, "begin")
    chat(eager, "echo [[fact: Wren | Wren tends the bar at the Rusty Flagon.]] " + "x" * 120)
    eager.post("/chat/new")
    eager.put("/history/n/save")
    assert eager.get("/history/n").json()["fact_count"] == 0
