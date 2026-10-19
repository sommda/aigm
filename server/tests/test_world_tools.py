import re

import pytest

from aigm.game import Game
from aigm.llm.base import Completed, LLMError, TextChunk
from aigm.llm.loop import run_turn
from aigm.models import ErrorEvent, MessageEnd
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.tools import dispatch, tool_schemas
from aigm.world import WorldTime
from tests.conftest import chat, names, reply_text


@pytest.fixture
def state():
    s = GameState(Phase.ADVENTURE, {"setting": "x"})
    w = s.world
    region = w.add_entity("Thornwood", "location")
    town = w.add_entity("Ashby", "location", parent=region.id)
    mine = w.add_entity("Harrow Mine", "location", aliases=["the old mine"], parent=region.id)
    wren = w.add_entity("Wren", "npc", aliases=["the barmaid"])
    w.add_fact("The Harrow Mine was abandoned forty years ago.", [mine.id], disclosure="known")
    w.add_fact("The mine's lower gallery joins a cellar under Ashby.", [mine.id, town.id], aspect="secret")
    w.add_fact("Wren pours drinks at the Rusty Flagon.", [wren.id], disclosure="known")
    w.set_scene(town.id, [wren.id])
    s.turn = 7
    return s


def run(state, name, **inp):
    return dispatch(name, "t1", inp, state)


# ---- offering -----------------------------------------------------------------------------


def test_world_tools_are_adventure_only_and_described_by_prompt_files():
    zero = {t["name"] for t in tool_schemas(phase=Phase.SESSION_ZERO)}
    adv = {t["name"]: t for t in tool_schemas(phase=Phase.ADVENTURE)}
    assert not zero & {"recall", "establish", "set_scene"}
    assert {"recall", "establish", "set_scene"} <= set(adv)
    assert all(len(adv[n]["description"]) > 100 for n in ("recall", "establish", "set_scene"))
    out = dispatch("recall", "t", {"about": "x"}, GameState(Phase.SESSION_ZERO))
    assert out.is_error and "Unknown tool" in out.content


# ---- recall -------------------------------------------------------------------------------


def test_recall_by_name_lists_everything_including_hidden_facts(state):
    out = run(state, "recall", about="the old mine")
    assert not out.is_error
    text = out.content
    assert text.startswith("Harrow Mine (location, e003; also called the old mine), in Thornwood")
    assert "(f0001) [known] The Harrow Mine was abandoned forty years ago." in text
    assert "(f0002) [GM only, not yet known to the player] The mine's lower gallery joins a cellar" in text
    assert "Connected to: Thornwood, Ashby" in text
    assert text.index("[known]") < text.index("[GM only")


def test_recall_by_query_and_both(state):
    out = run(state, "recall", query="cellar under Ashby")
    assert out.content.startswith("Facts matching 'cellar under Ashby':") and "(f0002)" in out.content
    both = run(state, "recall", about="Wren", query="mine gallery").content
    assert "Wren (npc" in both and "Facts matching 'mine gallery':" in both


def test_recall_with_nothing_found_says_so_and_points_to_establish(state):
    out = run(state, "recall", about="Karth")
    assert not out.is_error and "No person, place, group or concept named 'Karth'" in out.content
    assert "`establish`" in out.content
    assert "`establish`" in run(state, "recall", query="dragons").content


def test_recall_about_falls_back_to_a_text_search(state):
    out = run(state, "recall", about="cellar")
    assert "No person, place, group or concept named 'cellar'" in out.content and "(f0002)" in out.content


def test_recall_needs_an_argument(state):
    assert run(state, "recall").is_error and run(state, "recall", about=5).is_error


# ---- establish ----------------------------------------------------------------------------


def test_establish_adds_entities_and_facts_stamped_with_turn_and_time(state):
    state.world.advance_time(6)
    out = run(
        state, "establish",
        entities=[{"name": "Old Marrow", "kind": "npc", "aliases": ["the hermit"]},
                  {"name": "Marrow's Hut", "kind": "location", "parent": "Thornwood"}],
        facts=[{"text": "Old Marrow lives alone in a hut north of Ashby.", "about": ["Old Marrow", "Marrow's Hut"]},
               {"text": "Old Marrow once mined at the Harrow Mine.", "about": ["the hermit", "Harrow Mine"],
                "disclosure": "hidden"}],
    )  # fmt: skip
    assert not out.is_error and out.content.startswith("Recorded. new: Old Marrow (e005), Marrow's Hut (e006)")
    w = state.world
    f1, f2 = w.fact("f0004"), w.fact("f0005")
    assert (f1.disclosure, f1.source, f1.turn, f1.created_at) == ("known", "improvised", 7, WorldTime(1, 14))
    assert f1.revealed_turn == 7 and f2.disclosure == "hidden" and f2.about == ["e005", "e003"]
    assert w.find("the hermit").name == "Old Marrow" and w.find("Marrow's Hut").parent == "e001"


def test_establish_is_all_or_nothing_and_lists_every_problem(state):
    before = state.world.to_dict()
    out = run(
        state, "establish",
        entities=[{"name": "Fenn", "kind": "npc"}, {"name": "Ashby", "kind": "npc"}],
        facts=[{"text": "Fenn trades furs in Ashby.", "about": ["Fenn"]},
               {"text": "Gorr guards the old bridge.", "about": ["Gorr"]},
               {"text": "Too short", "about": ["Fenn"]}],
        reveal=["f0099"],
    )  # fmt: skip
    assert out.is_error and out.content.startswith("Nothing was recorded:")
    assert "already recorded as a location" in out.content and "'Gorr' is not recorded" in out.content
    assert "full declarative sentence" in out.content and "unknown fact 'f0099'" in out.content
    assert state.world.to_dict() == before


def test_establish_reuses_existing_entities_and_skips_repeated_facts(state):
    out = run(
        state, "establish",
        entities=[{"name": "the old mine", "kind": "location", "aliases": ["the dig"]}],
        facts=[{"text": "The Harrow Mine was abandoned forty years ago", "about": ["Harrow Mine"]},
               {"text": "The Harrow Mine has a rusted lift cage at its entrance.", "about": ["Harrow Mine"]}],
    )  # fmt: skip
    assert not out.is_error and "facts: f0004" in out.content and "skipped (already recorded): fact 1 repeats f0001" in out.content
    assert state.world.find("the dig").id == "e003" and len(state.world.entities) == 4


def test_establish_ignores_a_parent_given_to_a_person(state):
    out = run(state, "establish", entities=[{"name": "Joss Tilly", "kind": "npc", "parent": "Ashby"}],
              facts=[{"text": "Joss Tilly mends boots near the Ashby well.", "about": ["Joss Tilly"]}])  # fmt: skip
    assert not out.is_error and "ignored:" in out.content and "'Joss Tilly'" in out.content
    assert state.world.find("Joss Tilly").parent is None


def test_establish_treats_a_second_name_for_a_recorded_place_as_that_place(state):
    out = run(state, "establish",
              entities=[{"name": "The Harrow Pit", "kind": "location", "aliases": ["Harrow Mine"]}],
              facts=[{"text": "The Harrow Pit floods every spring.", "about": ["The Harrow Pit"]}])  # fmt: skip
    assert not out.is_error and "'The Harrow Pit' is the already recorded 'Harrow Mine'" in out.content
    assert len(state.world.entities) == 4 and state.world.find("The Harrow Pit") is state.world.find("Harrow Mine")
    assert state.world.facts_about(state.world.find("Harrow Mine").id)[-1].text == "The Harrow Pit floods every spring."


def test_a_fact_a_little_over_the_asked_length_is_kept_but_a_long_one_is_refused(state):
    fact = lambda n: {"text": " ".join(f"w{n}x{i}" for i in range(n)), "about": ["Wren"]}  # noqa: E731
    assert not run(state, "establish", facts=[fact(48)]).is_error
    out = run(state, "establish", facts=[fact(70)])
    assert out.is_error and "70 words" in out.content and "split it into two facts" in out.content


def test_establish_reveal_makes_hidden_facts_known(state):
    out = run(state, "establish", reveal=["f0002", "f0001"])
    assert "now known to the player: f0002" in out.content and "f0001" not in out.content.split("known to the player:")[1]
    f = state.world.fact("f0002")
    assert (f.disclosure, f.revealed_turn) == ("known", 7)


def test_establish_validates_shape(state):
    assert run(state, "establish").is_error
    assert run(state, "establish", facts=[{"text": "x"}] * 13).is_error
    assert run(state, "establish", facts=["nope"]).is_error
    assert run(state, "establish", entities=[{"name": "X", "kind": "monster"}]).is_error
    assert run(state, "establish", facts=[{"text": "Wren is rude to everyone she meets.", "about": [7]}]).is_error
    assert len(state.world.facts) == 3


# ---- set_scene ----------------------------------------------------------------------------


def test_set_scene_moves_the_party_and_advances_time(state):
    out = run(state, "set_scene", location="the old mine", present=["Wren"], elapsed_hours=5)
    assert out.content == "Scene: Harrow Mine. With the party: Wren. Time: Day 1, 13:00."
    assert (state.world.scene.location, state.world.scene.present) == ("e003", ["e004"])


def test_moving_without_present_clears_who_is_there_but_time_only_keeps_them(state):
    assert run(state, "set_scene", elapsed_hours=2).content.endswith("Time: Day 1, 10:00.")
    assert state.world.scene.present == ["e004"]
    assert "nobody recorded" in run(state, "set_scene", location="Harrow Mine").content
    assert state.world.scene.present == []


def test_set_scene_rejects_unknown_things_and_changes_nothing(state):
    before = state.world.to_dict()
    for inp in (
        {"location": "Karth"},
        {"location": "Wren"},  # not a place
        {"present": ["Nobody"]},
        {"elapsed_hours": -1},
        {"elapsed_hours": 2.5},
        {"elapsed_hours": 24 * 31},
        {"location": "Karth", "elapsed_hours": 3},
    ):
        out = run(state, "set_scene", **inp)
        assert out.is_error and out.content.startswith("Scene not changed"), inp
        assert state.world.to_dict() == before


# ---- staging in the turn loop -------------------------------------------------------------


class Scripted:
    def __init__(self, *responses):
        self.responses = list(responses)

    async def stream(self, *, system, messages, tools):
        content, stop = self.responses.pop(0)
        for b in content:
            if b["type"] == "text":
                yield TextChunk(b["text"])
        yield Completed(content, stop)


def tool_use(name, **inp):
    return [{"type": "tool_use", "id": "tu1", "name": name, "input": inp}], "tool_use"


def text(t):
    return [{"type": "text", "text": t}], "end_turn"


def adventure_session():
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, {"setting": "x"})
    ashby = session.state.world.add_entity("Ashby", "location")
    session.state.world.set_scene(ashby.id)
    return session


async def test_establish_in_a_successful_turn_is_committed_with_the_turn_number():
    session = adventure_session()
    llm = Scripted(tool_use("establish", entities=[{"name": "Wren", "kind": "npc"}],
                            facts=[{"text": "Wren runs the Rusty Flagon in Ashby.", "about": ["Wren", "Ashby"]}]),
                   text("Wren greets you."))  # fmt: skip
    events = [e async for e in run_turn(session=session, user_text="hi", llm=llm, game=Game(), max_iters=4)]
    assert isinstance(events[-1], MessageEnd)
    fact = session.state.world.fact("f0001")
    assert fact.turn == 1 and fact.source == "improvised"
    llm = Scripted(tool_use("establish", facts=[{"text": "Wren fears the Thorn Guild.", "about": ["Wren"]}]), text("ok"))
    _ = [e async for e in run_turn(session=session, user_text="more", llm=llm, game=Game(), max_iters=4)]
    assert session.state.world.fact("f0002").turn == 2


async def test_establish_in_a_failed_turn_leaves_the_world_unchanged():
    session = adventure_session()
    before = session.state.world.to_dict()

    class Dies(Scripted):
        async def stream(self, *, system, messages, tools):
            if not self.responses:
                raise LLMError("boom")
            async for ev in super().stream(system=system, messages=messages, tools=tools):
                yield ev

    llm = Dies(tool_use("establish", entities=[{"name": "Wren", "kind": "npc"}]))
    events = [e async for e in run_turn(session=session, user_text="hi", llm=llm, game=Game(), max_iters=4)]
    assert isinstance(events[-1], ErrorEvent)
    assert session.state.world.to_dict() == before and session.messages == []


async def test_the_next_request_in_a_turn_sees_what_a_tool_just_recorded():
    session = adventure_session()
    seen = []

    class Spy(Scripted):
        async def stream(self, *, system, messages, tools):
            seen.append(messages[-1]["content"][-1]["text"])
            async for ev in super().stream(system=system, messages=messages, tools=tools):
                yield ev

    llm = Spy(tool_use("establish", entities=[{"name": "Wren", "kind": "npc"}],
                       facts=[{"text": "Wren runs the Rusty Flagon in Ashby.", "about": ["Wren", "Ashby"]}]),
              text("Wren greets you."))  # fmt: skip
    _ = [e async for e in run_turn(session=session, user_text="hi", llm=llm, game=Game(), max_iters=4)]
    assert "Wren" not in seen[0] and "Wren runs the Rusty Flagon" not in seen[0]
    assert "Wren runs the Rusty Flagon in Ashby." in seen[1]


# ---- end to end in test mode --------------------------------------------------------------


def test_world_commands_over_http_and_saved(client):
    chat(client, "begin")
    client.put("/history/base/save")
    base = client.get("/history/base").json()
    ev = chat(client, "establish Wren")
    assert names(ev).count("tool_call") == 1 and re.search(r"Recorded\. new: Wren \(e\d+\); facts: f\d+", reply_text(ev))
    assert "Wren tends the bar" in reply_text(chat(client, "recall Wren"))
    assert "`establish`" in reply_text(chat(client, "recall Nobody"))
    assert "Scene not changed" in reply_text(chat(client, "scene Nowhere 3"))
    client.put("/history/w/save")
    info = client.get("/history/w").json()
    assert (info["entity_count"], info["fact_count"]) == (base["entity_count"] + 1, base["fact_count"] + 1)
    client.post("/chat/new")
    assert "Wren" not in reply_text(chat(client, "echo hi"))
    client.post("/history/w/restore")
    assert "Wren tends the bar" in reply_text(chat(client, "recall Wren"))


def test_world_commands_are_not_available_in_session_zero(client):
    assert "[test mode: Session 0]" in reply_text(chat(client, "recall Wren"))
