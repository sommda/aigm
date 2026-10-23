"""LLMClient backed by a local Ollama server (native /api/chat, streaming).

History is kept in Anthropic's block format, so requests are translated to Ollama's message format and the answer
back to a normalized `Completed`. Ollama sends a tool call whole rather than piece by piece, so each one arrives as
a start, one chunk holding the entire input, and a stop."""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from aigm.llm.base import (
    Completed,
    LLMError,
    LLMEvent,
    TextChunk,
    ThinkingChunk,
    ThinkingStarted,
    ThinkingStopped,
    ToolInputChunk,
    ToolInputStarted,
    ToolInputStopped,
)

log = logging.getLogger(__name__)

# Local models plan out loud in their visible text; this is the same note the Anthropic client adds when thinking is off.
LOCAL_NOTE = (
    "\n\nDo not plan, explain your bookkeeping or comment on your tool calls in your reply: everything you write "
    "is shown to the player as the story, so write only the story."
)


def to_ollama_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]},
        }
        for t in tools
    ]


def to_ollama_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic-format history to Ollama chat messages. Thinking blocks are left out: they are not needed to
    continue a conversation. A tool result becomes a `tool` message, named after the call it answers."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    names: dict[str, str] = {}
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            out.append({"role": message["role"], "content": content})
            continue
        text = "\n\n".join(b["text"] for b in content if b.get("type") == "text" and b.get("text"))
        if message["role"] == "assistant":
            calls = []
            for b in content:
                if b.get("type") == "tool_use":
                    names[b["id"]] = b["name"]
                    calls.append({"function": {"name": b["name"], "arguments": b.get("input") or {}}})
            entry: dict[str, Any] = {"role": "assistant", "content": text}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
            continue
        for b in content:
            if b.get("type") == "tool_result":
                result = b.get("content", "")
                if isinstance(result, list):
                    result = "\n".join(p.get("text", "") for p in result if isinstance(p, dict))
                if b.get("is_error"):
                    result = f"Error: {result}"
                out.append({"role": "tool", "tool_name": names.get(b.get("tool_use_id"), ""), "content": result})
        if text:
            out.append({"role": "user", "content": text})
    return out


class OllamaLLM:
    def __init__(
        self,
        *,
        model: str,
        host: str = "http://localhost:11434",
        max_tokens: int = 16000,
        num_ctx: int = 32768,
        keep_alive: str | None = None,
        think: bool | None = None,
        timeout: float = 600.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.max_tokens = max_tokens
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.think = think  # None: leave it to the model; True/False: ask for / forbid thinking
        self.thinking = True  # debug only: POST /debug/thinking; off here means "do not ask for thinking"
        self.timeout = timeout
        self._client = client

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=10.0))
        return self._client

    def request_params(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "stream": True,
            "messages": to_ollama_messages(system + LOCAL_NOTE, messages),
            # Ollama's default context is small and silently cuts the start of a long prompt, so always set it.
            "options": {"num_ctx": self.num_ctx, "num_predict": self.max_tokens},
        }
        if tools:
            params["tools"] = to_ollama_tools(tools)
        think = self.think if self.thinking else False
        if think is not None:
            params["think"] = think
        if self.keep_alive:
            params["keep_alive"] = self.keep_alive
        return params

    async def stream(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]:
        params = self.request_params(system, messages, tools)
        text: list[str] = []
        thinking: list[str] = []
        calls: list[dict[str, Any]] = []
        thinking_open = False
        final: dict[str, Any] = {}
        try:
            async with self._get_client().stream("POST", f"{self.host}/api/chat", json=params) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise _status_error(response.status_code, body, self.model)
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        raise LLMError("Ollama sent an unreadable reply", retryable=True) from None
                    if chunk.get("error"):
                        raise LLMError(f"Ollama error: {chunk['error']}", retryable=False)
                    message = chunk.get("message") or {}
                    if message.get("thinking"):
                        if not thinking_open:
                            thinking_open = True
                            yield ThinkingStarted()
                        thinking.append(message["thinking"])
                        yield ThinkingChunk(message["thinking"])
                    if message.get("content"):
                        if thinking_open:
                            thinking_open = False
                            yield ThinkingStopped()
                        text.append(message["content"])
                        yield TextChunk(message["content"])
                    for call in message.get("tool_calls") or []:
                        if thinking_open:
                            thinking_open = False
                            yield ThinkingStopped()
                        function = call.get("function") or {}
                        arguments = function.get("arguments") or {}
                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments or "{}")
                            except ValueError:
                                raise LLMError("The model produced an unreadable tool call", retryable=True) from None
                        call_id = f"toolu_{uuid.uuid4().hex[:24]}"
                        calls.append({"type": "tool_use", "id": call_id, "name": function.get("name", ""), "input": arguments})
                        yield ToolInputStarted(call_id, function.get("name", ""))
                        yield ToolInputChunk(call_id, json.dumps(arguments))
                        yield ToolInputStopped(call_id)
                    if chunk.get("done"):
                        final = chunk
        except httpx.ConnectError as exc:
            raise LLMError(f"Could not reach Ollama at {self.host}. Is it running? (AIGM_OLLAMA_HOST)", retryable=True) from exc
        except httpx.TimeoutException as exc:
            raise LLMError("Ollama took too long to answer.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama request failed: {exc}", retryable=True) from exc
        if thinking_open:
            yield ThinkingStopped()

        content: list[dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": "".join(text)})
        content += calls
        stop = "tool_use" if calls else "max_tokens" if final.get("done_reason") == "length" else "end_turn"
        in_tokens, out_tokens = final.get("prompt_eval_count") or 0, final.get("eval_count") or 0
        log.info("ollama usage: in=%s out=%s", in_tokens, out_tokens)
        yield Completed(
            content=content, stop_reason=stop, usage={"input_tokens": in_tokens, "output_tokens": out_tokens}
        )


def _status_error(status: int, body: str, model: str) -> LLMError:
    try:
        detail = json.loads(body).get("error", body)
    except (ValueError, AttributeError):
        detail = body
    if status == 404:
        return LLMError(f"Ollama has no model {model!r}. Run `ollama pull {model}` or check AIGM_MODEL.")
    return LLMError(f"Ollama error ({status}): {detail}", retryable=status >= 500)


async def ollama_json(
    client: httpx.AsyncClient, host: str, model: str, system: str, user: str, schema: dict[str, Any],
    *, num_ctx: int, max_tokens: int, keep_alive: str | None = None,
) -> str:
    """One non-streaming chat constrained to a JSON schema; returns the reply text (for the world curator)."""
    params: dict[str, Any] = {
        "model": model,
        "stream": False,
        "think": False,
        "format": schema,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"num_ctx": num_ctx, "num_predict": max_tokens, "temperature": 0.2},
    }
    if keep_alive:
        params["keep_alive"] = keep_alive
    try:
        response = await client.post(f"{host.rstrip('/')}/api/chat", json=params)
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach Ollama at {host}: {exc}", retryable=True) from exc
    if response.status_code != 200:
        raise _status_error(response.status_code, response.text, model)
    data = response.json()
    if data.get("done_reason") == "length":
        raise LLMError("The model ran out of room before finishing its answer", retryable=True)
    return (data.get("message") or {}).get("content", "")
