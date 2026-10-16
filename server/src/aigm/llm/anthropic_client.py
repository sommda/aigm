"""LLMClient backed by the Anthropic Messages API (streaming)."""

import logging
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from aigm.llm.base import (
    Completed,
    LLMError,
    LLMEvent,
    TextChunk,
    ThinkingChunk,
    ThinkingStarted,
    ThinkingStopped,
)

log = logging.getLogger(__name__)


def to_llm_error(exc: Exception) -> LLMError:
    """Map SDK exceptions to user-facing errors (retryable = worth sending the message again)."""
    if isinstance(exc, anthropic.AuthenticationError):
        return LLMError("Anthropic rejected the API key. Check ANTHROPIC_API_KEY.", retryable=False)
    if isinstance(exc, anthropic.PermissionDeniedError):
        return LLMError("The API key is not permitted to use this model or feature.", retryable=False)
    if isinstance(exc, anthropic.NotFoundError):
        return LLMError("Model not found. Check AIGM_MODEL.", retryable=False)
    if isinstance(exc, anthropic.RateLimitError):
        return LLMError("Rate limited by Anthropic. Wait a moment and try again.", retryable=True)
    if isinstance(exc, anthropic.BadRequestError):
        return LLMError(f"Anthropic rejected the request: {exc.message}", retryable=False)
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMError("Could not reach the Anthropic API.", retryable=True)
    if isinstance(exc, anthropic.APIStatusError):
        return LLMError(f"Anthropic API error ({exc.status_code}).", retryable=exc.status_code >= 500)
    return LLMError(f"Anthropic request failed: {exc}", retryable=False)


class AnthropicLLM:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        max_tokens: int = 16000,
        thinking_summaries: bool = True,
        effort: str | None = None,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.thinking_summaries = thinking_summaries
        self.effort = effort
        self._client = client

    def _get_client(self) -> anthropic.AsyncAnthropic:
        # Created lazily so the server starts (and /health works) before credentials exist.
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    def request_params(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
            # Cache everything up to the end of the conversation so far: the system prompt,
            # tools and history are a stable prefix that grows each turn.
            "cache_control": {"type": "ephemeral"},
        }
        if self.thinking_summaries:
            params["thinking"] = {"type": "adaptive", "display": "summarized"}
        if self.effort:
            params["output_config"] = {"effort": self.effort}
        return params

    async def stream(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]:
        params = self.request_params(system, messages, tools)
        block_types: dict[int, str] = {}
        try:
            client = self._get_client()
            async with client.messages.stream(**params) as stream:
                async for event in stream:
                    kind = event.type
                    if kind == "content_block_start":
                        block_types[event.index] = event.content_block.type
                        if event.content_block.type in ("thinking", "redacted_thinking"):
                            yield ThinkingStarted()
                    elif kind == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield TextChunk(delta.text)
                        elif delta.type == "thinking_delta":
                            yield ThinkingChunk(delta.thinking)
                    elif kind == "content_block_stop":
                        if block_types.get(getattr(event, "index", -1)) in ("thinking", "redacted_thinking"):
                            yield ThinkingStopped()
                final = await stream.get_final_message()
        except (anthropic.AnthropicError, TypeError) as exc:
            # TypeError: the SDK raises it when no credentials can be resolved at all.
            if isinstance(exc, TypeError) and "auth" not in str(exc).lower():
                raise
            if isinstance(exc, TypeError):
                raise LLMError(
                    "No Anthropic credentials found. Set ANTHROPIC_API_KEY (see server/.env.example).",
                    retryable=False,
                ) from exc
            raise to_llm_error(exc) from exc

        if final.stop_reason == "refusal":
            category = getattr(final.stop_details, "category", None) if final.stop_details else None
            suffix = f" ({category})" if category else ""
            raise LLMError(f"The model declined to continue{suffix}. Try rephrasing your action.", retryable=False)

        usage = final.usage
        input_tokens = (
            (usage.input_tokens or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        )
        log.info(
            "anthropic usage: in=%s cache_read=%s cache_write=%s out=%s",
            usage.input_tokens,
            getattr(usage, "cache_read_input_tokens", 0),
            getattr(usage, "cache_creation_input_tokens", 0),
            usage.output_tokens,
        )
        yield Completed(
            # Stored verbatim in history, including thinking blocks and their signatures.
            content=[b.model_dump(mode="json", exclude_none=True) for b in final.content],
            stop_reason=final.stop_reason or "end_turn",
            usage={"input_tokens": input_tokens, "output_tokens": usage.output_tokens or 0},
        )
