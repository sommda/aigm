import asyncio

import pytest

from aigm.config import Settings
from aigm.app import create_app
from aigm.llm.loop import run_turn
from aigm.llm.scripted import SAMPLES, ScriptedLLM, long_text, markdown_sampler
from aigm.session.store import Session
from aigm.game import Game
from fastapi.testclient import TestClient
from tests.conftest import chat, names, reply_text


def history(client, sid="default"):
    return client.get("/chat/history", params={"session_id": sid}).json()["messages"]


def test_health_reports_test_mode(client):
    assert client.get("/health").json() == {"status": "ok", "model": "scripted-test"}


def test_echo_turn_event_order_and_history(client):
    events = chat(client, "echo hello **world**")
    ns = names(events)
    assert ns[0] == "message_start" and ns[-1] == "message_end"
    assert set(ns[1:-1]) == {"text"}
    assert reply_text(events) == "hello **world**"
    end = events[-1][1]
    assert end["stop_reason"] == "end_turn" and end["usage"]["output_tokens"] >= 1
    msgs = history(client)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"][0]["text"] == "echo hello **world**"
    assert msgs[1]["content"] == [{"type": "text", "text": "hello **world**"}]


def test_text_is_streamed_in_small_chunks(client):
    events = chat(client, "echo " + "x" * 40)
    assert sum(1 for n, _ in events if n == "text") >= 5


def test_roll_uses_real_tool_and_loops_back(client):
    events = chat(client, "roll 4d6kh3+2 # strength")
    ns = names(events)
    assert ns.index("tool_call") < ns.index("dice_roll") < len(ns) - 1
    dice = next(d for n, d in events if n == "dice_roll")
    assert dice["expression"] == "4d6kh3+2 # strength" and dice["comment"] == "strength"
    term = dice["dice"][0]
    assert term["notation"] == "4d6kh3" and len(term["rolls"]) == 4
    assert dice["total"] == sum(r["value"] for r in term["rolls"] if r["kept"]) + 2
    call = next(d for n, d in events if n == "tool_call")
    assert call["name"] == "roll_dice" and call["tool_use_id"] == dice["tool_use_id"]
    assert "came up" in reply_text(events)  # the follow-up narration after the tool result

    msgs = history(client)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    result = msgs[2]["content"][0]
    assert result["type"] == "tool_result" and result["is_error"] is False
    assert result["tool_use_id"] == call["tool_use_id"]
    assert result["content"] == dice["result"]


def test_multiroll_emits_two_dice_events(client):
    events = chat(client, "multiroll")
    assert names(events).count("dice_roll") == 2
    msgs = history(client)
    assert len(msgs[2]["content"]) == 2  # both tool_results in a single user message


def test_badroll_reports_tool_error_to_model(client):
    events = chat(client, "badroll")
    assert "dice_roll" not in names(events)
    assert names(events)[-1] == "message_end"
    result = history(client)[2]["content"][0]
    assert result["is_error"] is True and "Invalid dice expression" in result["content"]
    assert "refused" in reply_text(events)


@pytest.mark.parametrize("cmd", sorted(SAMPLES))
def test_each_markup_sample_streams_intact(client, cmd):
    assert reply_text(chat(client, cmd)) == SAMPLES[cmd]


def test_markdown_sampler_and_long_and_help(client):
    assert reply_text(chat(client, "markdown")) == markdown_sampler()
    assert reply_text(chat(client, "long 5")) == long_text(5)
    assert "Test mode commands" in reply_text(chat(client, "help"))


def test_unknown_input_is_echoed(client):
    assert "You said: dance wildly" in reply_text(chat(client, "dance wildly"))


def test_thinking_events(client):
    events = chat(client, "think 2")
    ns = names(events)
    assert ns[1] == "thinking" and events[1][1] == {"status": "start"}
    deltas = [d["delta"] for n, d in events if n == "thinking" and d["status"] == "delta"]
    assert deltas and "Consideration 1" in "".join(deltas)
    end = next(d for n, d in events if n == "thinking" and d["status"] == "end")
    assert end["duration_ms"] >= 0
    assert ns.index("text") > max(i for i, n in enumerate(ns) if n == "thinking")
    blocks = history(client)[1]["content"]
    assert [b["type"] for b in blocks] == ["thinking", "text"]


def test_thinking_deltas_can_be_disabled(tmp_path):
    s = Settings(test_mode=True, test_delay=0, save_dir=tmp_path, stream_thinking=False, _env_file=None)
    events = chat(TestClient(create_app(s)), "think")
    statuses = [d["status"] for n, d in events if n == "thinking"]
    assert statuses == ["start", "end"]


def test_upstream_error_event_and_rollback(client):
    chat(client, "echo first")
    before = history(client)
    events = chat(client, "error")
    last = events[-1]
    assert last[0] == "error" and last[1]["code"] == "upstream_error" and last[1]["retryable"] is True
    assert "message_end" not in names(events)
    assert history(client) == before  # the failed turn left no trace
    assert chat(client, "echo again")[-1][0] == "message_end"  # session usable again (not stuck busy)


def test_tool_loop_limit(tmp_path):
    s = Settings(test_mode=True, test_delay=0, save_dir=tmp_path, max_tool_iters=3, _env_file=None)
    c = TestClient(create_app(s))
    events = chat(c, "loop")
    assert names(events).count("dice_roll") == 3
    assert events[-1][0] == "error" and events[-1][1]["code"] == "tool_loop_limit"
    assert history(c) == []


def test_busy_session_rejected_with_409(app, client):
    app.state.sessions.get("default").busy = True
    resp = client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"
    other = chat(client, "echo hi", session_id="other")  # other sessions unaffected
    assert other[-1][0] == "message_end"


def test_busy_cleared_after_turn(app, client):
    chat(client, "echo hi")
    assert app.state.sessions.get("default").busy is False


def test_sessions_are_independent(client):
    chat(client, "echo a", session_id="s1")
    assert len(history(client, "s1")) == 2 and history(client, "s2") == []


@pytest.mark.parametrize(
    "body", [{"message": ""}, {"message": "   "}, {"message": "hi", "session_id": "bad id!"}, {}]
)
def test_chat_validation(client, body):
    resp = client.post("/chat", json=body)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_error"


def test_new_game_clears_live_history(client):
    chat(client, "echo hi")
    resp = client.post("/chat/new")
    assert resp.json() == {"session_id": "default", "phase": "session_zero", "message_count": 0, "discarded_message_count": 2}
    assert history(client) == []


def test_new_game_conflicts_when_busy(app, client):
    app.state.sessions.get("default").busy = True
    assert client.post("/chat/new").status_code == 409


async def test_cancelled_stream_leaves_history_untouched():
    session = Session("s")
    session.messages = [{"role": "user", "content": [{"type": "text", "text": "old"}]},
                        {"role": "assistant", "content": [{"type": "text", "text": "old reply"}]}]
    before = list(session.messages)
    gen = run_turn(
        session=session, user_text="echo " + "z" * 100, llm=ScriptedLLM(delay=0), game=Game(), max_iters=4,
    )
    seen = [await gen.__anext__() for _ in range(3)]
    assert seen[0].event == "message_start"
    await gen.aclose()  # what happens when the client disconnects
    assert session.messages == before


async def test_cancel_during_sleep_propagates():
    session = Session("s")
    gen = run_turn(
        session=session, user_text="slow", llm=ScriptedLLM(delay=0), game=Game(), max_iters=4,
    )

    async def consume():
        async for _ in gen:
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.messages == []
