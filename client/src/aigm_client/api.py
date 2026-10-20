"""HTTP client for the AIGM backend (docs/API.md)."""

from collections.abc import AsyncIterator
from typing import Any

import httpx

from aigm_client.events import ErrorEvent, Event, MessageEnd, parse_event
from aigm_client.sse import SSEDecoder


# Where `uvicorn aigm.app:app` listens by default (127.0.0.1:8000).
DEFAULT_URL = "http://127.0.0.1:8000"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _error_from_response(resp: httpx.Response) -> ApiError:
    code, message = "http_error", f"HTTP {resp.status_code}"
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                code = err.get("code", code)
                message = err.get("message", message)
            elif "detail" in body:  # FastAPI's own validation errors
                code = "validation_error"
                message = str(body["detail"])
    except ValueError:
        pass
    return ApiError(resp.status_code, code, message)


class ApiClient:
    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        session_id: str = "default",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            transport=transport,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        try:
            resp = await self._http.request(method, path, **kw)
        except httpx.TransportError as exc:
            raise ApiError(0, "connection_error", f"Cannot reach server at {self.base_url} ({exc})") from exc
        if resp.status_code >= 400:
            raise _error_from_response(resp)
        return resp.json()

    def _session(self) -> dict[str, str]:
        return {"session_id": self.session_id}

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def context(self, draft: str = "") -> dict[str, Any]:
        """The model's next request as a tree (debug servers only; anything else answers 404)."""
        return await self._request("GET", "/debug/context", params={**self._session(), "draft": draft})

    async def set_thinking(self, enabled: bool) -> bool:
        """Turn the model's thinking on or off for the server (debug servers only; anything else answers 404)."""
        return (await self._request("PUT", "/debug/thinking", json={"enabled": enabled}))["thinking"]

    async def chat_state(self) -> dict[str, Any]:
        """The live session: `messages`, plus `phase` and `campaign` on servers that have them."""
        return await self._request("GET", "/chat/history", params=self._session())

    async def chat_history(self) -> list[dict[str, Any]]:
        return (await self.chat_state())["messages"]

    async def new_game(self) -> dict[str, Any]:
        return await self._request("POST", "/chat/new", params=self._session())

    async def list_histories(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/history"))["histories"]

    async def history_info(self, name: str) -> dict[str, Any]:
        return await self._request("GET", f"/history/{name}")

    async def save(self, name: str, overwrite: bool = False) -> dict[str, Any]:
        params = {**self._session(), **({"overwrite": "true"} if overwrite else {})}
        return await self._request("PUT", f"/history/{name}/save", params=params)

    async def restore(self, name: str) -> dict[str, Any]:
        return await self._request("POST", f"/history/{name}/restore", params=self._session())

    async def delete(self, name: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/history/{name}")

    async def stream_chat(self, message: str) -> AsyncIterator[Event]:
        """Yield typed events for one turn. Raises ApiError if the request is rejected up
        front (e.g. 409/422). Failures after the stream starts are yielded as ErrorEvent, and
        a stream that ends without a terminal event yields an ErrorEvent too."""
        terminal = False
        decoder = SSEDecoder()
        try:
            async with self._http.stream(
                "POST",
                "/chat",
                json={"message": message, "session_id": self.session_id},
                headers={"Accept": "text/event-stream"},
                timeout=httpx.Timeout(15.0, connect=5.0, read=None),
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise _error_from_response(resp)
                async for line in resp.aiter_lines():
                    msg = decoder.decode(line)
                    if msg is None:
                        continue
                    event = parse_event(msg.event, msg.data)
                    if event is None:
                        continue
                    yield event
                    if isinstance(event, (MessageEnd, ErrorEvent)):
                        terminal = True
                        return
        except httpx.TransportError as exc:
            if not terminal:
                yield ErrorEvent("connection_error", f"Connection lost: {exc}", True)
            return
        if not terminal:
            yield ErrorEvent("connection_closed", "Connection closed unexpectedly", True)
