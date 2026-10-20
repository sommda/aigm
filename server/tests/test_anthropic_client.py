"""AnthropicLLM against the real SDK, with the HTTP layer mocked (no network)."""

import json

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from aigm.llm.anthropic_client import AnthropicLLM
from aigm.llm.base import (
    Completed,
    LLMError,
    TextChunk,
    ThinkingChunk,
    ThinkingStarted,
    ThinkingStopped,
    ToolInputChunk,
    ToolInputStarted,
    ToolInputStopped,
)
from aigm.tools import tool_schemas
from tests.conftest import chat, names, reply_text

# ---- helpers: Anthropic wire-format SSE ------------------------------------------------


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps({'type': event, **data})}\n\n"


def message_stream(blocks, stop_reason="end_turn", in_tokens=25, out_tokens=40, cache_read=0):
    """blocks: list of ('text', [chunks]) | ('thinking', [chunks], signature) | ('tool_use', id, name, json_str)."""
    out = [
        sse(
            "message_start",
            {
                "message": {
                    "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                    "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": in_tokens, "output_tokens": 1,
                              "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": 0},
                }
            },
        ),
        sse("ping", {}),
    ]
    for i, block in enumerate(blocks):
        kind = block[0]
        if kind == "text":
            out.append(sse("content_block_start", {"index": i, "content_block": {"type": "text", "text": ""}}))
            for chunk in block[1]:
                out.append(sse("content_block_delta", {"index": i, "delta": {"type": "text_delta", "text": chunk}}))
        elif kind == "thinking":
            out.append(sse("content_block_start", {"index": i, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}))
            for chunk in block[1]:
                out.append(sse("content_block_delta", {"index": i, "delta": {"type": "thinking_delta", "thinking": chunk}}))
            out.append(sse("content_block_delta", {"index": i, "delta": {"type": "signature_delta", "signature": block[2]}}))
        elif kind == "tool_use":
            _, tid, name, args = block
            out.append(sse("content_block_start", {"index": i, "content_block": {"type": "tool_use", "id": tid, "name": name, "input": {}}}))
            half = len(args) // 2
            for part in (args[:half], args[half:]):
                out.append(sse("content_block_delta", {"index": i, "delta": {"type": "input_json_delta", "partial_json": part}}))
        out.append(sse("content_block_stop", {"index": i}))
    out.append(sse("message_delta", {"delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": {"output_tokens": out_tokens}}))
    out.append(sse("message_stop", {}))
    return "".join(out)


class FakeAnthropic:
    """Serves queued SSE bodies (or error responses) and records the request bodies."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        item = self.responses.pop(0)
        if isinstance(item, tuple):  # (status, json body)
            return httpx2.Response(item[0], json=item[1])
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=item.encode())

    def sdk_client(self) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(
            api_key="test-key", max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self.handler)),
        )


def make_llm(fake, **kw):
    return AnthropicLLM(api_key="test-key", model="claude-sonnet-5-5", client=fake.sdk_client(), **kw)


async def collect(llm, messages=None, system="SYS", tools=None):
    messages = messages or [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    return [e async for e in llm.stream(system=system, messages=messages, tools=tools or tool_schemas())]


# ---- stream translation ----------------------------------------------------------------


async def test_text_stream():
    fake = FakeAnthropic(message_stream([("text", ["Hel", "lo ", "world"])], in_tokens=100, out_tokens=7, cache_read=50))
    events = await collect(make_llm(fake))
    assert [e.text for e in events if isinstance(e, TextChunk)] == ["Hel", "lo ", "world"]
    done = events[-1]
    assert isinstance(done, Completed) and done.stop_reason == "end_turn"
    assert done.content == [{"type": "text", "text": "Hello world"}]
    # input includes cached tokens, and the cache use is reported on its own
    assert done.usage == {"input_tokens": 150, "output_tokens": 7, "cache_read_tokens": 50, "cache_write_tokens": 0}


async def test_thinking_text_and_tool_use():
    fake = FakeAnthropic(
        message_stream(
            [
                ("thinking", ["Need ", "a roll."], "sig-abc"),
                ("text", ["Rolling..."]),
                ("tool_use", "toolu_1", "roll_dice", '{"expression": "1d20+5"}'),
            ],
            stop_reason="tool_use",
        )
    )
    events = await collect(make_llm(fake))
    kinds = [type(e).__name__ for e in events]
    assert kinds[:5] == ["ThinkingStarted", "ThinkingChunk", "ThinkingChunk", "ThinkingStopped", "TextChunk"]
    assert [e.text for e in events if isinstance(e, ThinkingChunk)] == ["Need ", "a roll."]
    assert [e.name for e in events if isinstance(e, ToolInputStarted)] == ["roll_dice"]
    done = events[-1]
    assert done.stop_reason == "tool_use"
    thinking, text, tool = done.content
    assert thinking == {"type": "thinking", "thinking": "Need a roll.", "signature": "sig-abc"}
    assert text["text"] == "Rolling..."
    assert tool == {"type": "tool_use", "id": "toolu_1", "name": "roll_dice", "input": {"expression": "1d20+5"}}


async def test_omitted_thinking_still_signals_phase():
    fake = FakeAnthropic(message_stream([("thinking", [], "sig"), ("text", ["ok"])]))
    events = await collect(make_llm(fake))
    kinds = [type(e).__name__ for e in events]
    assert kinds[:2] == ["ThinkingStarted", "ThinkingStopped"]  # no chunks when thinking text is omitted
    assert events[-1].content[0] == {"type": "thinking", "thinking": "", "signature": "sig"}


# ---- request construction --------------------------------------------------------------


async def test_request_params_defaults():
    fake = FakeAnthropic(message_stream([("text", ["x"])]))
    await collect(make_llm(fake), system="You are the GM.")
    body = fake.requests[0]
    assert body["model"] == "claude-sonnet-5-5" and body["max_tokens"] == 16000 and body["stream"] is True
    assert body["system"] == "You are the GM."
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in body["tools"]] == ["roll_dice", "recall", "establish", "set_scene"]
    assert "Roll dice" in body["tools"][0]["description"]
    assert "temperature" not in body and "output_config" not in body


async def test_request_params_optional():
    fake = FakeAnthropic(message_stream([("text", ["x"])]))
    await collect(make_llm(fake, thinking_summaries=False, effort="low"))
    body = fake.requests[0]
    assert "thinking" not in body and body["output_config"] == {"effort": "low"}


async def test_thinking_off_is_sent_as_between_tools():
    fake = FakeAnthropic(message_stream([("text", ["x"])]))
    llm = make_llm(fake)
    llm.thinking = False
    await collect(llm)
    assert fake.requests[0]["thinking"] == {"type": "between_tools"}


async def test_history_is_sent_verbatim_including_thinking_signature():
    fake = FakeAnthropic(message_stream([("text", ["x"])]))
    history = [
        {"role": "user", "content": [{"type": "text", "text": "roll"}]},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "hm", "signature": "sig-1"},
            {"type": "tool_use", "id": "toolu_1", "name": "roll_dice", "input": {"expression": "1d6"}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "3", "is_error": False}]},
    ]
    await collect(make_llm(fake), messages=history)
    assert fake.requests[0]["messages"] == history


# ---- errors ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, retryable, fragment",
    [
        (401, False, "API key"),
        (404, False, "Model not found"),
        (429, True, "Rate limited"),
        (500, True, "500"),
        (529, True, "529"),
        (400, False, "rejected the request"),
    ],
)
async def test_http_errors_map_to_llm_errors(status, retryable, fragment):
    fake = FakeAnthropic((status, {"type": "error", "error": {"type": "api_error", "message": "boom"}}))
    with pytest.raises(LLMError) as exc:
        await collect(make_llm(fake))
    assert exc.value.retryable is retryable and fragment in str(exc.value)


async def test_refusal_is_an_error():
    fake = FakeAnthropic(message_stream([("text", ["I can't"])], stop_reason="refusal"))
    with pytest.raises(LLMError) as exc:
        await collect(make_llm(fake))
    assert "declined" in str(exc.value) and not exc.value.retryable


async def test_missing_credentials_message():
    class NoCreds:
        class messages:
            @staticmethod
            def stream(**kw):
                raise TypeError('"Could not resolve authentication method. Expected one of api_key or auth_token to be set."')

    llm = AnthropicLLM(api_key=None, model="m", client=NoCreds())  # type: ignore[arg-type]
    with pytest.raises(LLMError) as exc:
        await collect(llm)
    assert "ANTHROPIC_API_KEY" in str(exc.value)


# ---- the whole server with the Anthropic client behind it -------------------------------


def server_with(fake, tmp_path, **settings):
    s = Settings(test_mode=False, save_dir=tmp_path / "saves", _env_file=None, **settings)
    return TestClient(create_app(s, llm=make_llm(fake)))


def test_full_turn_with_tool_loop(tmp_path):
    fake = FakeAnthropic(
        message_stream(
            [("thinking", ["Attack roll."], "sig-1"), ("text", ["You swing. "]),
             ("tool_use", "toolu_1", "roll_dice", '{"expression": "1d20+5", "narration": "The blade flashes."}')],
            stop_reason="tool_use",
        ),
        message_stream([("text", ["A solid hit!"])]),
    )
    client = server_with(fake, tmp_path)
    events = chat(client, "I attack the goblin")
    assert names(events)[0] == "message_start" and names(events)[-1] == "message_end"
    assert "dice_roll" in names(events) and "tool_call" in names(events)
    assert reply_text(events) == "You swing. \n\nThe blade flashes.\n\nA solid hit!"
    assert [d["status"] for n, d in events if n == "thinking"] == ["start", "delta", "end"]
    roll = next(d for n, d in events if n == "dice_roll")

    # second API call carries the assistant turn (incl. thinking+signature) and the real tool result
    second = fake.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[1]["content"][0] == {"type": "thinking", "thinking": "Attack roll.", "signature": "sig-1"}
    result = second[2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_1"
    assert result["content"] == roll["result"] and result["is_error"] is False
    # the system prompt came from the prompt files
    assert "Game Master" in fake.requests[0]["system"]

    history = client.get("/chat/history").json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]


def test_upstream_failure_rolls_back_and_reports(tmp_path):
    fake = FakeAnthropic((529, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}))
    client = server_with(fake, tmp_path)
    events = chat(client, "hello")
    assert events[-1][0] == "error" and events[-1][1]["code"] == "upstream_error" and events[-1][1]["retryable"]
    assert client.get("/chat/history").json()["messages"] == []


def test_truncated_tool_call_is_not_committed(tmp_path):
    fake = FakeAnthropic(
        message_stream([("tool_use", "toolu_1", "roll_dice", '{"expression": "1d20')], stop_reason="max_tokens")
    )
    client = server_with(fake, tmp_path)
    events = chat(client, "go")
    assert events[-1][0] == "error" and "cut off" in events[-1][1]["message"]
    assert client.get("/chat/history").json()["messages"] == []


async def test_tool_input_is_streamed_as_fragments_with_the_call_id():
    args = '{"expression": "1d20+5", "narration": "You swing."}'
    fake = FakeAnthropic(
        message_stream([("text", ["Go."]), ("tool_use", "toolu_9", "roll_dice", args)], stop_reason="tool_use")
    )
    events = await collect(make_llm(fake))
    started = [e for e in events if isinstance(e, ToolInputStarted)]
    chunks = [e for e in events if isinstance(e, ToolInputChunk)]
    stopped = [e for e in events if isinstance(e, ToolInputStopped)]
    assert [(e.tool_use_id, e.name) for e in started] == [("toolu_9", "roll_dice")]
    assert len(chunks) > 1 and {e.tool_use_id for e in chunks} == {"toolu_9"}
    assert "".join(e.partial_json for e in chunks) == args
    assert [e.tool_use_id for e in stopped] == ["toolu_9"]
    order = [type(e).__name__ for e in events]
    assert order.index("ToolInputStarted") < order.index("ToolInputChunk") < order.index("ToolInputStopped")


async def test_only_the_roll_tool_asks_for_eager_input_streaming():
    fake = FakeAnthropic(message_stream([("text", ["x"])]))
    await collect(make_llm(fake))
    flags = {t["name"]: t.get("eager_input_streaming") for t in fake.requests[0]["tools"]}
    assert flags.pop("roll_dice") is True
    assert not any(flags.values())


async def test_unparseable_tool_input_is_a_retryable_error():
    fake = FakeAnthropic(message_stream([("tool_use", "toolu_9", "roll_dice", '{"expression" 1d20}')], stop_reason="tool_use"))
    with pytest.raises(LLMError) as err:
        await collect(make_llm(fake))
    assert err.value.retryable and "unreadable tool call" in str(err.value)
