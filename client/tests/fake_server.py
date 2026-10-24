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


def sample_status() -> dict:
    """The status page as the endpoint describes it (docs/STATUS.md 7)."""
    return {
        "location": {
            "id": "e002", "name": "The Docks", "path": [{"id": "e001", "name": "Port Veyra"}],
            "overview": "Gulls wheel over wet planks and tarred rope while stevedores shout over the tide.",
            "time": "Day 1, 18:00", "period": "evening",
        },
        "here": [{"id": "e004", "name": "Elian", "kind": "npc", "summary": "A merchant who needs a crate moved."}],
        "items": ["A barred cargo hatch."],
        "inside": [{"id": "e005", "name": "Pier Nine", "kind": "location", "summary": "A long jetty."}],
        "exits": [{"id": "e006", "name": "Customs House", "route": "Up Dock Street from the Docks."}],
        "table": {
            "columns": ["Name", "Who"],
            "rows": [["Toby", "Party, level 3"], ["Galvin", "Party, level 1"],
                     ["Elian", "A merchant who needs a crate moved."]],
        },
    }


def sample_compendium() -> dict[str, dict]:
    """Entities as the compendium endpoints describe them, by id (docs/COMPENDIUM.md 5)."""
    def ent(i, name, kind, category, status, facts, parent=None, **extra):
        return {"id": i, "name": name, "kind": kind, "category": category, "status": status, "parent": parent,
                "facts": facts, **extra}

    def fact(i, text, label, new=False):
        return {"id": i, "text": text, "aspect": (label or "").lower() or None, "label": label,
                "learned_turn": 3, "new": new}

    vale = {"id": "e001", "name": "Ashby Vale"}
    return {
        "e001": ent("e001", "Ashby Vale", "location", "locations", None,
                    [fact("f1", "Ashby Vale is a farming valley.", "History")], children=[
                        {"id": "e003", "name": "Thornwood", "kind": "location", "status": "updated"}]),
        "e003": ent("e003", "Thornwood", "location", "locations", "updated",
                    [fact("f2", "The Thornwood is a dark forest east of Ashby.", "Approach"),
                     fact("f3", "Lights are seen there at night.", "Hazards", new=True)],
                    parent=vale, path=[vale],
                    children=[{"id": "e007", "name": "Harrow Mine", "kind": "location", "status": "new"}]),
        "e007": ent("e007", "Harrow Mine", "location", "locations", "new",
                    [fact("f4", "The Harrow Mine was abandoned forty years ago after a collapse.", "History", True)],
                    parent={"id": "e003", "name": "Thornwood"}, path=[vale, {"id": "e003", "name": "Thornwood"}],
                    aliases=["the old mine"],
                    related=[{"id": "e020", "name": "Thorn Guild", "kind": "faction", "category": "other"}]),
        "e010": ent("e010", "Wren", "npc", "characters", None, [fact("f5", "Wren runs the Rusty Flagon.", "Role")]),
        "e020": ent("e020", "Thorn Guild", "faction", "other", "new",
                    [fact("f6", "The Thorn Guild controls the toll road.", "Goals", True)]),
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
        self.story: dict | None = None  # the public summary a story game reports
        self.story_text = ""
        self.compendium: dict[str, dict] | None = None  # None = an older server without the compendium
        self.status_page: dict | None = None  # None = an older server without the status page
        self.seen: set[str] = set()
        self.compendium_down = False  # answer the compendium calls with a 500

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _json(self, status: int, body: dict) -> httpx.Response:
        return httpx.Response(status, json=body)

    def _err(self, status: int, code: str, msg: str) -> httpx.Response:
        return self._json(status, {"error": {"code": code, "message": msg}})

    def _status(self, e: dict) -> str | None:
        return None if e["id"] in self.seen else e["status"]

    def _unread(self) -> dict[str, int]:
        statuses = [self._status(e) for e in (self.compendium or {}).values()]
        return {"new": statuses.count("new"), "updated": statuses.count("updated")}

    def _compendium(self, method: str, path: str, params: dict, body: dict) -> httpx.Response:
        assert self.compendium is not None
        if self.compendium_down:
            return self._err(500, "internal_error", "boom")
        parts = path.strip("/").split("/")
        if len(parts) == 1:
            cats = []
            for cid, title in (("locations", "Locations"), ("characters", "Characters"), ("other", "Other")):
                ents = [e for e in self.compendium.values() if e["category"] == cid]
                st = [self._status(e) for e in ents]
                cats.append({"id": cid, "title": title, "count": len(ents), "new": st.count("new"),
                             "updated": st.count("updated")})
            return self._json(200, {"session_id": "default", "categories": cats, **self._unread()})
        if parts[1] == "seen" and method == "POST":
            ids = list(self.compendium) if body.get("all") else body.get("entities", [])
            self.seen.update(i for i in ids if i in self.compendium)
            return self._json(200, {"session_id": "default", "categories": [], **self._unread()})
        if parts[1] == "entities" and len(parts) == 3:
            e = self.compendium.get(parts[2])
            if e is None:
                return self._err(404, "not_found", "No compendium entry")
            status = self._status(e)
            facts = [{**f, "new": f["new"] and e["id"] not in self.seen} for f in e["facts"]]
            return self._json(200, {"aliases": [], "path": [], "children": [], "related": [], "learned_turn": 3,
                                    "updated_turn": 3, **e, "status": status, "facts": facts})
        if parts[1] in ("locations", "characters", "other"):
            q = params.get("q", "").casefold()
            rows = []
            for e in self.compendium.values():
                if e["category"] != parts[1] or q not in e["name"].casefold():
                    continue
                depth = len(e.get("path") or []) if params.get("sort") == "tree" else 0
                rows.append({"id": e["id"], "name": e["name"], "kind": e["kind"], "category": e["category"],
                             "summary": e["facts"][0]["text"], "parent": e["parent"], "depth": depth,
                             "fact_count": len(e["facts"]), "status": self._status(e), "unseen_count": 0,
                             "learned_turn": 3})
            rows.sort(key=lambda r: (r["depth"] and 0, r["id"]))
            return self._json(200, {"session_id": "default", "category": parts[1], "title": parts[1].title(),
                                    "count": len(rows), "entries": rows})
        return self._err(404, "not_found", f"{method} {path}")

    def handle(self, req: httpx.Request) -> httpx.Response:
        path, method = req.url.path, req.method
        params = dict(req.url.params)
        body = json.loads(req.content) if req.content else {}
        self.calls.append((method, path, {**params, **body}))
        if path == "/health":
            extra = {} if self.debug is None else {"debug": self.debug}
            if self.debug:
                extra["thinking"] = self.thinking
            if self.compendium is not None:
                extra["compendium"] = True
            if self.status_page is not None:
                extra["status"] = True
            return self._json(200, {"status": "ok", "model": "fake", **extra})
        if path == "/debug/context" and self.debug:
            return self._json(200, self.context)
        if path == "/debug/thinking" and method == "PUT" and self.debug:
            self.thinking = body["enabled"]
            return self._json(200, {"thinking": self.thinking})
        if path == "/debug/story" and self.debug:
            return self._json(200, {"story": None, "text": self.story_text})
        if path == "/status" and self.status_page is not None:
            return self._json(200, {"session_id": "default", "phase": "adventure", **self.status_page})
        if path.startswith("/compendium") and self.compendium is not None:
            return self._compendium(method, path, params, body)
        if path == "/chat/history":
            body = {"session_id": "default", "messages": self.messages}
            if self.story:
                body["story"] = self.story
            if self.compendium is not None:
                body["compendium"] = self._unread()
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
