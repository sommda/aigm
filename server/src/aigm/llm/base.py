"""LLM abstraction. The tool loop consumes normalized events so it is independent of the
Anthropic SDK and can be driven by a scripted fake in test mode."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class ThinkingStarted:
    pass


@dataclass
class ThinkingChunk:
    text: str


@dataclass
class ThinkingStopped:
    pass


@dataclass
class TextChunk:
    text: str


@dataclass
class Completed:
    """The final assistant message: Anthropic-format content blocks (text, tool_use,
    thinking...) exactly as they should be stored in history."""

    content: list[dict[str, Any]]
    stop_reason: str
    # input_tokens counts everything the model read, cached or not; the cache_* keys say how much of it was
    # read from or written to the prompt cache.
    usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})


LLMEvent = ThinkingStarted | ThinkingChunk | ThinkingStopped | TextChunk | Completed


class LLMClient(Protocol):
    def stream(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]: ...
