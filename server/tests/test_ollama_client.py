"""OllamaLLM and the Ollama settings, with the HTTP layer mocked (no network)."""

import json

import httpx
import pytest

from aigm.app import create_app
from aigm.config import Settings
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
from aigm.llm.ollama_client import OllamaLLM, to_ollama_messages, to_ollama_tools
from aigm.world.ollama_curator import OllamaCurator


def ndjson(*chunks: dict) -> bytes:
    return "".join(json.dumps(c) + "\n" for c in chunks).encode()


def llm_with(body: bytes, status: int = 200, seen: list | None = None, **kw) -> OllamaLLM:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(status, content=body)

    return OllamaLLM(model="gemma4:12b", client=httpx.AsyncClient(transport=httpx.MockTransport(handle)), **kw)


async def collect(llm: OllamaLLM, messages=None, tools=None):
    return [e async for e in llm.stream(system="sys", messages=messages or [], tools=tools or [])]


async def test_text_streams_and_completes():
    body = ndjson(
        {"message": {"role": "assistant", "content": "You "}, "done": False},
        {"message": {"role": "assistant", "content": "wake."}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
         "prompt_eval_count": 12, "eval_count": 3},
    )
    events = await collect(llm_with(body))
    assert [e.text for e in events if isinstance(e, TextChunk)] == ["You ", "wake."]
    done = events[-1]
    assert isinstance(done, Completed)
    assert done.content == [{"type": "text", "text": "You wake."}]
    assert done.stop_reason == "end_turn"
    assert done.usage == {"input_tokens": 12, "output_tokens": 3}


async def test_a_tool_call_arrives_whole_and_is_given_an_id():
    body = ndjson(
        {"message": {"role": "assistant", "content": "",
                     "tool_calls": [{"function": {"name": "roll_dice", "arguments": {"expression": "1d20"}}}]},
         "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
    )
    events = await collect(llm_with(body))
    start, chunk, stop = events[:3]
    assert isinstance(start, ToolInputStarted) and start.name == "roll_dice"
    assert isinstance(chunk, ToolInputChunk) and json.loads(chunk.partial_json) == {"expression": "1d20"}
    assert isinstance(stop, ToolInputStopped) and stop.tool_use_id == start.tool_use_id
    done = events[-1]
    assert done.stop_reason == "tool_use"
    assert done.content == [
        {"type": "tool_use", "id": start.tool_use_id, "name": "roll_dice", "input": {"expression": "1d20"}}
    ]


async def test_thinking_is_streamed_and_closed_before_the_text():
    body = ndjson(
        {"message": {"thinking": "hm"}, "done": False},
        {"message": {"content": "Hi"}, "done": False},
        {"message": {}, "done": True, "done_reason": "length"},
    )
    events = await collect(llm_with(body))
    kinds = [type(e) for e in events]
    assert kinds[:4] == [ThinkingStarted, ThinkingChunk, ThinkingStopped, TextChunk]
    assert events[-1].stop_reason == "max_tokens"
    assert all(b["type"] == "text" for b in events[-1].content)  # thinking is not stored


async def test_the_request_sets_the_context_size_and_only_sends_think_when_asked():
    seen: list = []
    body = ndjson({"message": {"content": "x"}, "done": True})
    await collect(llm_with(body, seen=seen, num_ctx=16384, keep_alive="1h", think=False))
    sent = seen[0]
    assert sent["options"]["num_ctx"] == 16384 and sent["keep_alive"] == "1h" and sent["think"] is False
    assert sent["stream"] is True and sent["messages"][0]["role"] == "system"
    seen.clear()
    await collect(llm_with(body, seen=seen))
    assert "think" not in seen[0] and "keep_alive" not in seen[0] and "tools" not in seen[0]


def test_messages_and_tools_are_translated():
    history = [
        {"role": "user", "content": [{"type": "text", "text": "I attack."}]},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "..", "signature": "s"},
            {"type": "text", "text": "Roll!"},
            {"type": "tool_use", "id": "t1", "name": "roll_dice", "input": {"expression": "1d20"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "17", "is_error": False},
            {"type": "text", "text": "notes", "cache_control": {"type": "ephemeral"}},
        ]},
    ]
    assert to_ollama_messages("sys", history) == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "I attack."},
        {"role": "assistant", "content": "Roll!",
         "tool_calls": [{"function": {"name": "roll_dice", "arguments": {"expression": "1d20"}}}]},
        {"role": "tool", "tool_name": "roll_dice", "content": "17"},
        {"role": "user", "content": "notes"},
    ]
    tool = {"name": "roll_dice", "description": "d", "input_schema": {"type": "object"}, "eager_input_streaming": True}
    assert to_ollama_tools([tool]) == [
        {"type": "function", "function": {"name": "roll_dice", "description": "d", "parameters": {"type": "object"}}}
    ]


async def test_errors_are_readable():
    missing = llm_with(b'{"error":"model not found"}', status=404)
    with pytest.raises(LLMError, match="ollama pull"):
        await collect(missing)
    midway = llm_with(ndjson({"error": "boom"}))
    with pytest.raises(LLMError, match="boom"):
        await collect(midway)

    def refuse(request):
        raise httpx.ConnectError("no")

    down = OllamaLLM(model="m", client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    with pytest.raises(LLMError, match="Is it running") as info:
        await collect(down)
    assert info.value.retryable


def test_provider_setting_builds_the_ollama_client_and_curator(tmp_path):
    settings = Settings(
        _env_file=None, AIGM_PROVIDER="ollama", AIGM_MODEL="gemma4:12b", AIGM_SAVE_DIR=str(tmp_path),
        AIGM_OLLAMA_THINK="", AIGM_OLLAMA_NUM_CTX="8192",
    )
    app = create_app(settings)
    assert isinstance(app.state.llm, OllamaLLM) and app.state.llm.num_ctx == 8192 and app.state.llm.think is None
    assert isinstance(app.state.curator.curator, OllamaCurator)
    assert settings.curator_model == settings.curator_expand_model == "gemma4:12b"
    named = Settings(_env_file=None, AIGM_PROVIDER="ollama", AIGM_MODEL="a", AIGM_WORLD_MODEL="b")
    assert (named.curator_model, named.curator_expand_model) == ("b", "b")
    assert Settings(_env_file=None).curator_model == "claude-haiku-5-5"


async def test_the_curator_asks_for_json_in_the_schema():
    seen: list = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": '{"a": 1}'}, "done": True, "done_reason": "stop"})

    from aigm.prompts import PromptLibrary

    curator = OllamaCurator(
        prompts=PromptLibrary(None), model="gemma4:12b", client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    schema = {"type": "object"}
    assert await curator._ask("extract", "gemma4:12b", "low", "text", schema) == {"a": 1}
    assert seen[0]["format"] == schema and seen[0]["stream"] is False and seen[0]["think"] is False
