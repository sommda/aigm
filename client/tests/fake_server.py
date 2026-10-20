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


def sample_context() -> dict:
    """A small context tree in the shape of GET /debug/context (docs/API.md)."""
    msg = lambda i, kind, title, blocks: {  # noqa: E731
        "id": f"history/{i}", "kind": kind, "title": title, "tokens": sum(b["tokens"] for b in blocks), "children": blocks,
    }
    block = lambda i, j, kind, title, text: {  # noqa: E731
        "id": f"history/{i}/{j}", "kind": kind, "title": title, "tokens": len(text) // 4 + 1, "text": text,
    }
    history = [
        msg(0, "assistant", "Turn 1 · GM: You stand before the mine.", [
            block(0, 0, "assistant", "You stand before the mine.", "You stand before the mine.\nIt is cold."),
        ]),
        msg(1, "user", "Turn 1 · Player: I roll to search.", [
            block(1, 0, "user", "I roll to search.", "I roll to search."),
        ]),
        msg(2, "assistant", "Turn 2 · GM: (rolls the dice)", [
            block(2, 0, "thinking", "Thinking", "Needs a check."),
            block(2, 1, "tool_use", "Tool call: roll_dice", 'roll_dice\n{"expression": "1d20+2"}'),
        ]),
    ]
    return {
        "session_id": "default", "phase": "adventure", "model": "fake", "turn": 2, "estimated_tokens": 321,
        "sections": [
            {"id": "system", "kind": "system", "title": "System prompt", "tokens": 20, "children": [
                {"id": "prompt/system/common/01_role.md", "kind": "prompt", "title": "system/common/01_role.md",
                 "tokens": 20, "text": "You are the game master.\nBe vivid."},
            ]},
            {"id": "tools", "kind": "tools", "title": "Tools (1)", "tokens": 30, "children": [
                {"id": "tools/roll_dice", "kind": "tools", "title": "roll_dice", "tokens": 30, "text": "Roll dice."},
            ]},
            {"id": "history", "kind": "history", "title": "History (3 messages)",
             "tokens": sum(m["tokens"] for m in history), "children": history},
            {"id": "next", "kind": "user", "title": "Next user message (turn 2)", "tokens": 50, "children": [
                {"id": "input", "kind": "input", "title": "Your next message", "tokens": 8,
                 "text": "«your next message goes here»", "cache_breakpoint": True},
                {"id": "briefing", "kind": "briefing", "title": "World notes (briefing)", "tokens": 42,
                 "note": "Computed for the text typed so far, not the final message.", "children": [
                    {"id": "briefing/0", "kind": "briefing", "title": "Clock", "tokens": 5, "text": "Time: day 1, 08:00"},
                 ]},
            ]},
        ],
    }


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
        self.phase = ""  # "" = an older server that does not report the phase
        self.ruleset_name = ""  # "" = an older server that does not report the ruleset
        self.debug: bool | None = None  # None = an older server whose /health has no debug field
        self.context = sample_context()
        self.thinking = True

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
            extra = {} if self.debug is None else {"debug": self.debug}
            if self.debug:
                extra["thinking"] = self.thinking
            return self._json(200, {"status": "ok", "model": "fake", **extra})
        if path == "/debug/context" and self.debug:
            return self._json(200, self.context)
        if path == "/debug/thinking" and method == "PUT" and self.debug:
            self.thinking = body["enabled"]
            return self._json(200, {"thinking": self.thinking})
        if path == "/chat/history":
            body = {"session_id": "default", "messages": self.messages}
            if self.phase:
                body["phase"] = self.phase
            if self.ruleset_name:
                body["ruleset_name"] = self.ruleset_name
            return self._json(200, body)
        if path == "/chat/new":
            n = len(self.messages)
            self.messages = []
            extra = {"phase": "session_zero"} if self.phase else {}
            self.phase = "session_zero" if self.phase else self.phase
            return self._json(200, {"session_id": "default", "message_count": 0, "discarded_message_count": n, **extra})
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
