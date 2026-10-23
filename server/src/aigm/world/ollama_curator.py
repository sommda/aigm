"""The model-driven curator on a local Ollama server: the same passes as `AnthropicCurator`, with each answer
constrained to the pass's JSON schema through Ollama's `format` option. Effort levels do not apply."""

import json
from typing import Any

import httpx

from aigm.llm.base import LLMError
from aigm.llm.ollama_client import ollama_json
from aigm.prompts import PromptLibrary
from aigm.world.anthropic_curator import AnthropicCurator
from aigm.world.curator import CuratorError


class OllamaCurator(AnthropicCurator):
    def __init__(
        self,
        *,
        prompts: PromptLibrary,
        model: str,
        expand_model: str | None = None,
        host: str = "http://localhost:11434",
        num_ctx: int = 32768,
        keep_alive: str | None = None,
        max_tokens: int = 8000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            api_key=None, prompts=prompts, model=model, expand_model=expand_model or model, max_tokens=max_tokens
        )
        self.host, self.num_ctx, self.keep_alive = host, num_ctx, keep_alive
        self._http = client

    async def _ask(self, step: str, model: str, effort: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))
        try:
            text = await ollama_json(
                self._http, self.host, model, self.system[step], user, schema,
                num_ctx=self.num_ctx, max_tokens=self.max_tokens, keep_alive=self.keep_alive,
            )
        except LLMError as exc:
            raise CuratorError(f"{step}: {exc}") from exc
        try:
            data = json.loads(text)
        except ValueError:
            raise CuratorError(f"{step}: the model did not return JSON") from None
        if not isinstance(data, dict):
            raise CuratorError(f"{step}: the model returned {type(data).__name__}, not an object")
        return data
