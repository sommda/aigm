"""The reduced history end to end: what the model is sent, what the viewer shows, what is saved."""

import json

from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from aigm.game import Game
from aigm.history import STORY_OPEN, HistoryPolicy, turns
from aigm.llm.base import Completed, TextChunk
from aigm.llm.loop import run_turn
from aigm.session.persistence import validate_messages
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.world import Digest
from tests.conftest import chat, names
from tests.test_history_reduce import make_digests, make_history

POLICY = HistoryPolicy(trim_keep=3, trim_step=3, digest_keep=6, digest_step=6)


class Recorder:
    def __init__(self):
        self.calls = []

    async def stream(self, *, system, messages, tools):
        self.calls.append(list(messages))
        yield TextChunk("ok")
        yield Completed(content=[{"type": "text", "text": "ok"}], stop_reason="end_turn")


def long_session(n=30):
    session = Session("s")
    session.messages = make_history(n)
    session.state = GameState(Phase.ADVENTURE, {"setting": "x"})
    for d in make_digests(session.messages).values():
        session.state.world.add_digest(d)
    return session


async def test_the_model_gets_the_reduced_history_and_the_session_keeps_everything():
    session = long_session()
    stored = [dict(m) for m in session.messages]
    llm = Recorder()
    events = [
        e async for e in run_turn(session=session, user_text="next", llm=llm, game=Game(history_policy=POLICY), max_iters=3)
    ]
    [sent] = llm.calls
    assert len(sent) < len(session.messages)
    assert sent[2]["content"][0]["text"].startswith(STORY_OPEN)
    assert "GM 5 after" not in json.dumps(sent) and "GM 30 after" in json.dumps(sent)
    validate_messages(sent)
    # everything that was stored is still there, in full, with the new turn after it
    assert session.messages[: len(stored)] == stored and len(session.messages) == len(stored) + 2
    history = events[-1].metrics["history"]
    assert history["turns"] == 31 and history["digested_turns"] > 0 and history["trimmed_turns"] > 0
    sizes = events[-1].metrics["requests"][0]["sent"]
    assert sizes["history"] < sizes["history_stored"] and sizes["messages_sent"] < sizes["messages_stored"]
    assert sizes["history_by_kind"]["digests"] > 0


async def test_with_reduction_off_the_model_gets_every_message():
    session = long_session()
    llm = Recorder()
    off = Game(history_policy=HistoryPolicy(trim=False, digest=False))
    async for _ in run_turn(session=session, user_text="next", llm=llm, game=off, max_iters=3):
        pass
    [sent] = llm.calls
    assert sent[:-1] == session.messages[:-2]


async def test_the_current_turns_tool_loop_is_never_trimmed():
    """Thinking blocks must go back to the API unchanged while a turn's tool calls are being answered."""

    class Rolls:
        calls = 0

        async def stream(self, *, system, messages, tools):
            Rolls.calls += 1
            if Rolls.calls == 1:
                content = [
                    {"type": "thinking", "thinking": "why", "signature": "SIG"},
                    {"type": "tool_use", "id": "x1", "name": "roll_dice", "input": {"expression": "1d20"}},
                ]
                yield Completed(content=content, stop_reason="tool_use")
            else:
                self.second = messages
                yield Completed(content=[{"type": "text", "text": "done"}], stop_reason="end_turn")

    session, llm = long_session(), Rolls()
    async for _ in run_turn(session=session, user_text="next", llm=llm, game=Game(history_policy=POLICY), max_iters=3):
        pass
    tail = llm.second[-3:]
    assert tail[1]["content"][0] == {"type": "thinking", "thinking": "why", "signature": "SIG"}
    assert tail[1]["content"][1]["type"] == "tool_use" and tail[2]["content"][0]["type"] == "tool_result"


def test_the_viewer_shows_the_reduced_history_and_what_it_saved(tmp_path):
    settings = Settings(
        test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", debug=True, _env_file=None,
        history_trim_keep=3, history_trim_step=3, history_digest_keep=6, history_digest_step=6,
    )  # fmt: skip
    app = create_app(settings)
    session = app.state.sessions.get("default")
    session.messages = make_history(30)
    session.state = GameState(Phase.ADVENTURE, {"setting": "x"})
    for d in make_digests(session.messages).values():
        session.state.world.add_digest(d)
    data = TestClient(app).get("/debug/context").json()
    red = data["reduction"]
    assert red["turns"] == 31 and red["digested_turns"] == 23 and red["history_tokens_saved"] > 0
    history = next(s for s in data["sections"] if s["id"] == "history")
    assert f"of {len(session.messages)} messages sent" in history["title"]
    assert "23 turns as digests" in history["title"] and "trimmed" in history["title"]
    story = next(n for m in history["children"] for n in m["children"] if n["kind"] == "digest")
    assert "23 earlier turns condensed" in story["title"]
    assert any("(trimmed)" in m["title"] for m in history["children"])
    titles = [m["title"] for m in history["children"]]
    assert titles[0].startswith("Turn 1 ·") and any(t.startswith("Turn 26 ·") for t in titles)


def test_a_game_in_test_mode_builds_digests_in_the_background_and_then_uses_them(tmp_path):
    settings = Settings(
        test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", world_every_pages=0.001,
        history_trim_keep=2, history_trim_step=2, history_digest_keep=3, history_digest_step=2, _env_file=None,
    )  # fmt: skip
    app = create_app(settings)
    client = TestClient(app)
    session = app.state.sessions.get("default")
    session.state = GameState(Phase.ADVENTURE, {"setting": "x"})
    session.messages = make_history(2)
    for i in range(8):
        assert names(chat(client, f"I do thing {i}"))[-1] == "message_end"
    assert len(session.state.world.digests) >= 7  # one per finished turn but the newest
    turns_now = turns(session.messages)
    assert all(session.state.world.digests[t.start].end == t.end for t in turns_now[1:-1])
    validate_messages(session.messages)
    last = chat(client, "and again")[-1][1]
    assert last["metrics"]["history"]["digested_turns"] > 0


def test_digest_objects_are_the_same_whatever_made_them():
    assert Digest(2, 4, 2, "x").to_dict() == Digest.from_dict(Digest(2, 4, 2, "x").to_dict()).to_dict()
