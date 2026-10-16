"""A scripted in-memory stand-in for the AIGM server, usable as an httpx transport."""

import json

import httpx


class _Stream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for c in self._chunks:
            yield c


def sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class FakeServer:
    def __init__(self, reply_events: list[tuple[str, dict]] | None = None) -> None:
        self.reply_events = reply_events or [
            ("message_start", {"message_id": "m1", "session_id": "default"}),
            ("text", {"delta": "You swing. "}),
            ("message_end", {"message_id": "m1", "stop_reason": "end_turn", "usage": {}}),
        ]
        self.messages: list[dict] = []
        self.saves: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, str, dict]] = []
        self.split_chunks = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _json(self, status: int, body: dict) -> httpx.Response:
        return httpx.Response(status, json=body)

    def _err(self, status: int, code: str, msg: str) -> httpx.Response:
        return self._json(status, {"error": {"code": code, "message": msg}})

    def handle(self, req: httpx.Request) -> httpx.Response:
        path, method = req.url.path, req.method
        params = dict(req.url.params)
        body = json.loads(req.content) if req.content else {}
        self.calls.append((method, path, {**params, **body}))
        if path == "/health":
            return self._json(200, {"status": "ok", "model": "fake"})
        if path == "/chat/history":
            return self._json(200, {"session_id": "default", "messages": self.messages})
        if path == "/chat/new":
            n = len(self.messages)
            self.messages = []
            return self._json(200, {"session_id": "default", "message_count": 0, "discarded_message_count": n})
        if path == "/chat" and method == "POST":
            self.messages.append({"role": "user", "content": [{"type": "text", "text": body["message"]}]})
            data = b"".join(sse(e, d) for e, d in self.reply_events)
            chunks = [data[i : i + 7] for i in range(0, len(data), 7)] if self.split_chunks else [data]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=_Stream(chunks))
        if path == "/history" and method == "GET":
            hs = [
                {"name": n, "message_count": len(m), "saved_at": "2026-10-15T18:22:04Z", "model": "fake"}
                for n, m in self.saves.items()
            ]
            return self._json(200, {"histories": hs})
        parts = path.strip("/").split("/")
        if parts[0] == "history" and len(parts) >= 2:
            name = parts[1]
            if len(parts) == 3 and parts[2] == "save" and method == "PUT":
                if name in self.saves and params.get("overwrite") != "true":
                    return self._err(409, "already_exists", f"A saved history named '{name}' already exists")
                existed = name in self.saves
                self.saves[name] = list(self.messages)
                return self._json(
                    200,
                    {"name": name, "message_count": len(self.messages), "saved_at": "x", "overwritten": existed},
                )
            if len(parts) == 3 and parts[2] == "restore" and method == "POST":
                if name not in self.saves:
                    return self._err(404, "not_found", f"No saved history named '{name}'")
                self.messages = list(self.saves[name])
                return self._json(200, {"name": name, "message_count": len(self.messages)})
            if len(parts) == 2 and method == "GET":
                if name not in self.saves:
                    return self._err(404, "not_found", f"No saved history named '{name}'")
                return self._json(200, {"name": name, "message_count": len(self.saves[name]), "saved_at": "x"})
            if len(parts) == 2 and method == "DELETE":
                if name not in self.saves:
                    return self._err(404, "not_found", f"No saved history named '{name}'")
                del self.saves[name]
                return self._json(200, {"name": name, "deleted": True})
        return self._err(404, "not_found", f"{method} {path}")
