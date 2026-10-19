"""Measuring turns: time to the first visible text, total time, and token use (docs/HISTORY.md, A)."""

import asyncio
import json

from aigm.app import create_app
from aigm.config import Settings
from aigm.game import Game
from aigm.llm.base import Completed, TextChunk, ThinkingChunk, ThinkingStarted, ThinkingStopped
from aigm.llm.loop import run_turn
from aigm.metrics import MetricsLog, TurnMetrics, history_breakdown
from aigm.models import MessageEnd
from aigm.session.store import Session
from fastapi.testclient import TestClient
from tests.conftest import chat, names


class TimedLLM:
    """Thinks for a while, then writes; the second call (after a tool result) answers at once."""

    def __init__(self, think=0.06, wait=0.03):
        self.think, self.wait, self.calls = think, wait, 0

    async def stream(self, *, system, messages, tools):
        self.calls += 1
        if self.calls == 1:
            yield ThinkingStarted()
            await asyncio.sleep(self.think)
            yield ThinkingChunk("hmm")
            yield ThinkingStopped()
            await asyncio.sleep(self.wait)
            yield TextChunk("Steel rings out. ")
            yield Completed(
                content=[
                    {"type": "text", "text": "Steel rings out. "},
                    {"type": "tool_use", "id": "t1", "name": "roll_dice", "input": {"expression": "1d20", "narration": "The blade flashes."}},
                ],
                stop_reason="tool_use",
                usage={"input_tokens": 1000, "output_tokens": 30, "cache_read_tokens": 800, "cache_write_tokens": 100},
            )
        else:
            yield TextChunk("It hits.")
            yield Completed(
                content=[{"type": "text", "text": "It hits."}],
                stop_reason="end_turn",
                usage={"input_tokens": 1100, "output_tokens": 10, "cache_read_tokens": 1000, "cache_write_tokens": 0},
            )


async def run(llm, tmp_path, **kw):
    session = Session("s")
    log = MetricsLog(tmp_path / "metrics")
    events = [
        e
        async for e in run_turn(
            session=session, user_text="I attack.", llm=llm, game=Game(), max_iters=4, metrics=log, model="m", **kw
        )
    ]
    return events, session


async def test_first_visible_text_ignores_thinking_and_totals_cover_the_turn(tmp_path):
    events, _ = await run(TimedLLM(), tmp_path, roll_pause=0.05)
    end = events[-1]
    assert isinstance(end, MessageEnd)
    m = end.metrics
    first, think = m["requests"][0]["first_text_ms"], m["requests"][0]["thinking_ms"]
    assert think >= 55 and first >= think + 25  # the thinking time is reported apart and is not the first text
    assert m["first_text_ms"] >= first  # measured from the start of the turn
    assert m["requests"][1]["thinking_ms"] == 0 and m["requests"][1]["first_text_ms"] is not None
    assert m["pause_ms"] == 50 and m["total_ms"] >= m["first_text_ms"] + 50
    assert m["total_ms"] >= sum(r["total_ms"] for r in m["requests"])
    assert m["model"] == "m" and m["model_calls"] == 2 and m["phase"] == "session_zero"


async def test_token_use_is_summed_and_cache_use_is_split_out(tmp_path):
    events, _ = await run(TimedLLM(think=0, wait=0), tmp_path)
    end = events[-1]
    assert end.usage == {"input_tokens": 2100, "output_tokens": 40, "cache_read_tokens": 1800, "cache_write_tokens": 100}
    m = end.metrics
    assert (m["input_tokens"], m["cache_read_tokens"], m["cache_write_tokens"]) == (2100, 1800, 100)
    assert m["uncached_input_tokens"] == 200 and m["output_tokens"] == 40
    first = m["requests"][0]
    assert first["uncached_input_tokens"] == 100 and first["stop_reason"] == "tool_use"
    sent = first["sent"]
    assert sent["system"] > 0 and sent["tools"] > 0 and sent["messages_sent"] == 1 == sent["messages_stored"]
    assert sent["history_by_kind"]["player"] > 0 and sent["briefing"] == 0


async def test_each_finished_turn_appends_one_json_line(tmp_path):
    await run(TimedLLM(think=0, wait=0), tmp_path)
    await run(TimedLLM(think=0, wait=0), tmp_path)
    lines = (tmp_path / "metrics" / "s.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert record["session"] == "s" and record["at"].endswith("Z") and record["model_calls"] == 2


async def test_a_failed_turn_records_nothing(tmp_path):
    class Broken:
        async def stream(self, *, system, messages, tools):
            raise Exception("boom")
            yield

    events, _ = await run(Broken(), tmp_path)
    assert names_of(events)[-1] == "error" and not (tmp_path / "metrics").exists()


def names_of(events):
    return [e.event for e in events]


def test_metrics_can_be_switched_off(tmp_path):
    MetricsLog(None).record("s", TurnMetrics(1, "adventure"))
    assert not list(tmp_path.iterdir())


def test_history_breakdown_splits_the_tokens_by_kind():
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "p" * 40}]},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "t" * 80, "signature": "s"},
                {"type": "text", "text": "g" * 400},
                {"type": "tool_use", "id": "a", "name": "roll_dice", "input": {"expression": "1d20"}},
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "r" * 20}]},
        {"role": "user", "content": [{"type": "text", "text": "<story_so_far>\n" + "d" * 100}]},
    ]
    by = history_breakdown(msgs)
    assert by["player"] == 10 and by["gm"] == 100 and by["digests"] > 25
    assert by["thinking"] > 20 and by["tool_calls"] > 10 and by["tool_results"] > 5


# ---- through the API ------------------------------------------------------------------------


def test_message_end_carries_metrics_and_the_file_is_written(tmp_path):
    settings = Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None)
    client = TestClient(create_app(settings))
    events = chat(client, "hello")
    assert names(events)[-1] == "message_end"
    end = events[-1][1]
    assert end["metrics"]["model"] == "scripted-test" and end["metrics"]["first_text_ms"] is not None
    assert end["usage"]["cache_read_tokens"] == 0
    [line] = (tmp_path / "saves" / "metrics" / "default.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["turn"] == 1


def test_metrics_file_is_off_when_disabled(tmp_path):
    settings = Settings(
        test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", metrics=False, _env_file=None
    )
    client = TestClient(create_app(settings))
    chat(client, "hello")
    assert not (tmp_path / "saves" / "metrics").exists()
