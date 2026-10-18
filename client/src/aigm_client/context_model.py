"""The context viewer's model: the server's context tree, its collapse state, and the lines to draw.

Pure logic with no terminal in it, so it can be tested directly (docs/CONTEXT.md)."""

import textwrap
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text

# Rich styles per node kind. Unknown kinds fall back to plain text.
KIND_STYLES = {
    "system": "bright_blue",
    "prompt": "bright_blue",
    "tools": "cyan",
    "briefing": "yellow",
    "digest": "medium_purple1",
    "history": "white",
    "user": "green",
    "assistant": "magenta",
    "thinking": "dim magenta",
    "tool_use": "orange3",
    "tool_result": "dark_orange3",
    "input": "bold black on bright_white",
}
ALWAYS_OPEN = {"input"}  # the user-input placeholder is never collapsible
TEXT_KINDS = {"user", "assistant"}


@dataclass
class Node:
    id: str
    kind: str
    title: str
    tokens: int = 0
    text: str | None = None
    children: list["Node"] = field(default_factory=list)
    note: str = ""
    cache_breakpoint: bool = False

    @property
    def expandable(self) -> bool:
        return self.kind not in ALWAYS_OPEN and bool(self.children or self.text)


def parse_nodes(raw: list[dict[str, Any]]) -> list[Node]:
    return [
        Node(
            id=str(n.get("id", "")),
            kind=str(n.get("kind", "")),
            title=str(n.get("title", "")),
            tokens=int(n.get("tokens") or 0),
            text=n.get("text"),
            children=parse_nodes(n.get("children") or []),
            note=str(n.get("note") or ""),
            cache_breakpoint=bool(n.get("cache_breakpoint")),
        )
        for n in raw
    ]


def walk(nodes: list[Node], depth: int = 0, parent: Node | None = None):
    for node in nodes:
        yield node, depth, parent
        yield from walk(node.children, depth + 1, node)


def default_open(node: Node, depth: int, parent: Node | None) -> bool:
    """Top-level groups show their children as one-line rows; the text blocks of a message show when the message
    is opened; everything else (prompt files, tools, tool calls, thinking, briefing) starts collapsed."""
    if depth == 0:
        return True
    return node.kind in TEXT_KINDS and parent is not None and parent.id.startswith("history/")


class ContextModel:
    def __init__(self, data: dict[str, Any], ascii_only: bool = False) -> None:
        self.ascii_only = ascii_only
        self.expanded: set[str] = set()
        self._known: set[str] = set()
        self.cursor: str | None = None
        self.apply(data)

    # ---- data ---------------------------------------------------------------------------

    def apply(self, data: dict[str, Any]) -> None:
        """Load a (new) response. Nodes seen before keep their collapse state; new ones get the defaults."""
        self.data = data
        self.nodes = parse_nodes(data.get("sections") or [])
        ids = set()
        for node, depth, parent in walk(self.nodes):
            ids.add(node.id)
            if node.id not in self._known and default_open(node, depth, parent):
                self.expanded.add(node.id)
        self.expanded &= ids
        self._known = ids
        if self.cursor not in ids:
            self.cursor = self.nodes[0].id if self.nodes else None

    @property
    def header_text(self) -> str:
        d = self.data
        head = (
            f"Context for the next message  ·  {d.get('phase', '?')}  ·  {d.get('model', '?')}  ·  "
            f"turn {d.get('turn', '?')}  ·  ~{d.get('estimated_tokens', 0):,} tokens"
        )
        red = d.get("reduction") or {}
        if red.get("digested_turns") or red.get("trimmed_turns"):
            head += (
                f"\nHistory reduced: {red.get('digested_turns', 0)} turns as digests, {red.get('trimmed_turns', 0)} "
                f"trimmed, ~{red.get('history_tokens_saved', 0):,} tokens saved"
            )
        return head

    # ---- collapse state -----------------------------------------------------------------

    def toggle(self, node_id: str) -> None:
        node = self.find(node_id)
        if node is None or not node.expandable:
            return
        self.expanded.symmetric_difference_update({node_id})

    def expand_all(self) -> None:
        self.expanded = {n.id for n, _, _ in walk(self.nodes) if n.expandable}

    def collapse_all(self) -> None:
        """Back to the defaults."""
        self.expanded = {n.id for n, d, p in walk(self.nodes) if default_open(n, d, p)}

    def find(self, node_id: str | None) -> Node | None:
        return next((n for n, _, _ in walk(self.nodes) if n.id == node_id), None)

    def is_open(self, node: Node) -> bool:
        return node.kind in ALWAYS_OPEN or node.id in self.expanded

    # ---- drawing ------------------------------------------------------------------------

    def visible_headers(self) -> list[str]:
        """Ids of the rows shown, top to bottom (what the cursor moves over)."""
        out: list[str] = []

        def visit(nodes: list[Node]) -> None:
            for node in nodes:
                out.append(node.id)
                if node.children and self.is_open(node):
                    visit(node.children)

        visit(self.nodes)
        return out

    def move(self, delta: int) -> None:
        rows = self.visible_headers()
        if not rows:
            return
        at = rows.index(self.cursor) if self.cursor in rows else 0
        self.cursor = rows[max(0, min(len(rows) - 1, at + delta))]

    def move_to(self, end: bool) -> None:
        rows = self.visible_headers()
        if rows:
            self.cursor = rows[-1 if end else 0]

    def lines(self, width: int) -> tuple[list[Text], dict[str, int]]:
        """The drawn lines, and the line index of each row's header (for the cursor and scrolling)."""
        out: list[Text] = []
        where: dict[str, int] = {}
        bar = "|" if self.ascii_only else "▌"
        closed, opened = (">", "v") if self.ascii_only else ("▸", "▾")
        width = max(width, 20)

        def style_of(kind: str) -> str:
            return KIND_STYLES.get(kind, "")

        def visit(nodes: list[Node], depth: int) -> None:
            for node in nodes:
                style = style_of(node.kind)
                indent = "  " * depth
                if node.kind in ALWAYS_OPEN:
                    marker = "*" if self.ascii_only else "●"
                else:
                    marker = (opened if self.is_open(node) else closed) if node.expandable else " "
                tail = f"  {node.kind} · ~{node.tokens:,} tok"
                room = max(10, width - len(indent) - 4 - len(tail))
                title = node.title if len(node.title) <= room else node.title[: room - 1] + "…"
                line = Text(indent)
                line.append(bar, style=style.split(" on ")[-1] if " on " in style else style)
                line.append(f" {marker} ")
                line.append(title, style=style or None)
                line.append(tail, style="dim")
                where[node.id] = len(out)
                out.append(line)
                if not self.is_open(node):
                    continue
                if node.note:
                    out.append(Text(f"{indent}{bar} {node.note}", style="dim italic"))
                if node.text is not None:
                    prefix = f"{indent}{bar} "
                    for raw in node.text.split("\n"):
                        for piece in textwrap.wrap(
                            raw, max(10, width - len(prefix)), replace_whitespace=False, drop_whitespace=False
                        ) or [""]:
                            body = Text(prefix[: len(indent)])
                            body.append(bar, style=style.split(" on ")[-1] if " on " in style else style)
                            body.append(" ")
                            body.append(piece, style=style if node.kind == "input" else None)
                            out.append(body)
                if node.cache_breakpoint:
                    rule = "-- prompt-cache breakpoint --" if self.ascii_only else "── prompt-cache breakpoint ──"
                    out.append(Text(f"{indent}  {rule}", style="dim"))
                visit(node.children, depth + 1)

        visit(self.nodes, 0)
        return out, where
