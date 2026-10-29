import json

from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from aigm.game import Game
from aigm.session.persistence import HistoryRepository  # noqa: F401
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.tools import dispatch
from aigm.world.briefing import build_briefing
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import LOOK_RETRY_TURNS, CuratorService, _last_narration
from tests.conftest import chat
from tests.test_looks import make_look


def make_client(tmp_path, curator=None):
    settings = Settings(test_mode=True, test_delay=0, save_dir=tmp_path, _env_file=None)
    return TestClient(create_app(settings, curator=curator))


def adventure(turn=3):
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, {"setting": "A river town.", "party": [{"name": "Toby Reed", "sheet": "Rogue."}]})
    world = session.state.world
    world.set_scene(world.add_entity("Ashby", "location").id, [world.add_entity("Marta Venn", "npc").id])
    world.add_fact("Marta Venn keeps the Rusty Flagon.", [world.find("Marta Venn").id], disclosure="known")
    session.state.turn = turn
    session.messages = [
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Marta Venn waves from behind the bar."}]},
    ]
    return session


# ---- bootstrap -------------------------------------------------------------------------------


def test_beginning_a_game_describes_the_party_and_the_cast_while_the_player_waits(tmp_path):
    client = make_client(tmp_path)
    events = chat(client, "begin")
    messages = [d["message"] for n, d in events if n == "status" and d["stage"] == "world"]
    assert messages.index("Picturing the characters...") == len(messages) - 2 and messages[-1] == "The world is ready."
    client.put("/history/g/save")
    saved = json.loads((tmp_path / "g.json").read_text())
    assert saved["version"] == 11 and list(saved["looks"]) == ["Test Hero"]
    innkeeper = next(e for e in saved["world"]["entities"] if e["name"] == "Innkeeper")
    assert innkeeper["look"]["summary"] and saved["looks"]["Test Hero"]["rev"] == 1


class NoLooks(ScriptedCurator):
    async def look(self, request):
        raise RuntimeError("model down")


def test_a_failure_describing_the_characters_does_not_stop_the_game_from_beginning(tmp_path):
    client = make_client(tmp_path, CuratorService(NoLooks()))
    events = chat(client, "begin")
    assert "phase_change" in [n for n, _ in events] and events[-1][0] == "message_end"
    state = client.app.state.sessions.get("default").state
    assert state.looks == {} and state.world.find("Innkeeper").look is None


# ---- after a turn ----------------------------------------------------------------------------


async def test_the_background_sweep_writes_missing_looks_and_then_goes_quiet():
    session, svc = adventure(), CuratorService(ScriptedCurator())
    assert svc.looks_due(session)
    assert await svc.run_looks_if_due(session)
    assert session.state.world.find("Marta Venn").look is not None and "Toby Reed" in session.state.looks
    assert not svc.looks_due(session) and not await svc.run_looks_if_due(session)
    assert not session.curating


async def test_a_sweep_that_writes_nothing_backs_off():
    session, svc = adventure(turn=5), CuratorService(NoLooks())
    assert not await svc.run_looks_if_due(session)
    assert session.looks_retry_turn == 5 + LOOK_RETRY_TURNS and not svc.looks_due(session)
    session.state.turn += LOOK_RETRY_TURNS
    assert svc.looks_due(session)


def test_not_due_in_session_zero_while_busy_or_curating():
    svc = CuratorService(ScriptedCurator())
    zero = Session("z")
    assert not svc.looks_due(zero)
    for attr in ("busy", "curating"):
        session = adventure()
        setattr(session, attr, True)
        assert not svc.looks_due(session)


async def test_results_for_a_game_that_was_replaced_are_dropped():
    session, svc = adventure(), CuratorService(ScriptedCurator())

    class Replacing(ScriptedCurator):
        async def look(self, request):
            session.reset_world_work()
            return await super().look(request)

    svc = CuratorService(Replacing())
    assert not await svc.run_looks_if_due(session)
    assert session.state.world.find("Marta Venn").look is None and session.state.looks == {}


def test_waiting_party_looks_are_applied_when_idle_and_only_to_party_members():
    session = adventure()
    session.pending_looks.append({"Toby Reed": make_look("Toby Reed"), "Stranger": make_look("Stranger")})
    session.drain_pending()
    assert list(session.state.looks) == ["Toby Reed"] and session.pending_looks == []


def test_last_narration_is_the_text_since_the_players_last_message():
    messages = adventure().messages + [
        {"role": "user", "content": [{"type": "text", "text": "I ask"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "First."}, {"type": "tool_use", "id": "x"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Second."}]},
    ]
    assert _last_narration(messages) == "First.\nSecond."


# ---- what the GM sees -----------------------------------------------------------------------


def test_the_briefing_shows_the_look_of_people_present_and_the_party():
    session = adventure()
    state = session.state
    state.world.set_look(state.world.find("Marta Venn").id, make_look())
    state.set_look("Toby Reed", make_look("Toby Reed"))
    notes = build_briefing(state.world)
    assert "Marta Venn (npc)" in notes and "  Looks: A stooped old woman" in notes
    assert "Marks: clouded left eye; tremor in the right hand." in notes
    assert "description" not in notes and make_look().description[:40] not in notes  # the summary only
    full = Game().briefing(state, "", "")
    assert "How the party looks" in full and "- Toby Reed: A stooped old woman" in full


def test_recall_gives_the_whole_look():
    session = adventure()
    state = session.state
    state.world.set_look(state.world.find("Marta Venn").id, make_look())
    out = dispatch("recall", "t1", {"about": "Marta Venn"}, state)
    assert not out.is_error and "Look (what anyone can see" in out.content and make_look().description[:60] in out.content
