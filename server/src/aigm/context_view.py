"""The context viewer's data: the request the next player message would produce, as a tree of named parts.

Built from the same `RequestDescription` that `run_turn` sends (see `Game.describe`), so the view is the
real request, not a second implementation of it. Debug mode only (docs/CONTEXT.md)."""

import json
from typing import Any

from aigm.game import BRIEFING_CLOSE, BRIEFING_OPEN, Game
from aigm.llm.loop import turn_number
from aigm.session.state import Phase
from aigm.session.store import Session
from aigm.world.briefing import CHARS_PER_TOKEN
from aigm.world.ops import apply_ops

PLACEHOLDER = "«your next message goes here»"
BRIEFING_NOTE = "Computed for the text typed so far, not the final message."
_BRIEFING_SECTIONS = (
    ("Time:", "Clock"),
    ("Location:", "Location"),
    ("Present:", "Present"),
    ("Nearby:", "Nearby"),
    ("Also relevant:", "Relevant"),
    ("Corrections", "Corrections"),
)


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def _node(id: str, kind: str, title: str, text: str | None = None, children: list[dict] | None = None, **extra: Any) -> dict:
    tokens = estimate_tokens(text) if text is not None else sum(c["tokens"] for c in children or [])
    node: dict[str, Any] = {"id": id, "kind": kind, "title": title, "tokens": tokens, **extra}
    if text is not None:
        node["text"] = text
    if children is not None:
        node["children"] = children
    return node


def _preview(text: str, limit: int = 70) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def _block_text(block: dict[str, Any]) -> str:
    match block.get("type"):
        case "text":
            return block.get("text", "")
        case "thinking":
            return block.get("thinking", "")
        case "redacted_thinking":
            return "[redacted thinking]"
        case "tool_use":
            return f"{block.get('name', '')}\n{_dump(block.get('input', {}))}"
        case "tool_result":
            content = block.get("content", "")
            return content if isinstance(content, str) else _dump(content)
        case _:
            return _dump(block)


def _block_node(id: str, role: str, block: dict[str, Any]) -> dict:
    kind = block.get("type")
    text = _block_text(block)
    match kind:
        case "text":
            return _node(id, role, _preview(text) or "(empty)", text)
        case "thinking" | "redacted_thinking":
            return _node(id, "thinking", "Thinking", text)
        case "tool_use":
            return _node(id, "tool_use", f"Tool call: {block.get('name', '?')}", text)
        case "tool_result":
            suffix = " (error)" if block.get("is_error") else ""
            return _node(id, "tool_result", f"Tool result{suffix}: {_preview(text)}", text)
        case _:
            return _node(id, role, f"Unknown block ({kind})", text)


def _message_nodes(messages: list[dict[str, Any]]) -> list[dict]:
    nodes, turn = [], 0
    for i, msg in enumerate(messages):
        role = msg["role"]
        if role == "user" and any(b.get("type") == "text" for b in msg["content"]):
            turn += 1
        who = "Player" if role == "user" else "GM"
        blocks = [_block_node(f"history/{i}/{j}", role, b) for j, b in enumerate(msg["content"])]
        first = next((b for b in msg["content"] if b.get("type") == "text"), None)
        label = _preview(first["text"]) if first else ", ".join(b["title"] for b in blocks)
        nodes.append(_node(f"history/{i}", role, f"Turn {turn} · {who}: {label}", children=blocks))
    return nodes


def _briefing_node(briefing: str) -> dict:
    body = briefing.removeprefix(BRIEFING_OPEN).removesuffix(BRIEFING_CLOSE).strip("\n")
    sections: list[tuple[str, list[str]]] = []
    for line in body.split("\n"):
        title = next((t for prefix, t in _BRIEFING_SECTIONS if line.startswith(prefix)), None)
        if title or not sections:
            sections.append((title or "Notes", []))
        sections[-1][1].append(line)
    children = [_node(f"briefing/{n}", "briefing", title, "\n".join(lines)) for n, (title, lines) in enumerate(sections)]
    return _node("briefing", "briefing", "World notes (briefing)", children=children, note=BRIEFING_NOTE)


def build_context(*, game: Game, session: Session, model: str, draft: str = "") -> dict[str, Any]:
    """The request the next message would produce, from the session's committed state. Nothing in the
    session is changed: finished curator passes the next turn would apply first are applied to a copy."""
    state = session.state.copy()
    for ops in session.pending:
        apply_ops(state.world, ops)
    staged = [*session.messages, {"role": "user", "content": [{"type": "text", "text": draft}]}]
    state.turn = turn = turn_number(staged)
    request = game.describe(state, staged, draft)

    parts = [_node(f"prompt/{p.source}", "prompt", p.source, p.text) for p in request.system_parts]
    tools = [
        _node(f"tools/{t['name']}", "tools", t["name"], f"{t['description']}\n\nInput schema:\n{_dump(t['input_schema'])}")
        for t in request.tools
    ]
    stored = request.history[:-1]  # the last entry is the pending message, shown below
    history = _message_nodes(stored)
    pending = [_node("input", "input", "Your next message", draft or PLACEHOLDER, cache_breakpoint=True)]
    if request.briefing:
        pending.append(_briefing_node(request.briefing))

    sections = [
        _node("system", "system", "System prompt", children=parts),
        _node("tools", "tools", f"Tools ({len(tools)})", children=tools),
        _node("history", "history", f"History ({len(stored)} messages)", children=history),
        _node("next", "user", f"Next user message (turn {turn})", children=pending),
    ]
    return {
        "session_id": session.id,
        "phase": state.phase.value,
        "model": model,
        "turn": turn,
        "estimated_tokens": sum(s["tokens"] for s in sections),
        "sections": sections,
    }
