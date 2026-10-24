"""The compendium screen's model: the lists and details the server sent, the cursor, which entries have been read,
and the lines to draw. Pure logic with no terminal in it, so it can be tested directly (docs/COMPENDIUM.md 6)."""

import textwrap
from typing import Any

from rich.text import Text

TABS = ("locations", "characters", "other")
TITLES = {"locations": "Locations", "characters": "Characters", "other": "Other"}
EMPTY = "Nothing is known yet."
STATUS_STYLE = {"new": "bold green", "updated": "yellow"}


class Marks:
    """The glyphs, plain when the terminal cannot draw them."""

    def __init__(self, ascii_only: bool) -> None:
        self.star, self.arrow, self.crumb = ("*", ">", ">") if ascii_only else ("✦", "→", "›")
        self.ellipsis = "..." if ascii_only else "…"
        self.dot = "-" if ascii_only else "·"


class CompendiumModel:
    def __init__(self, ascii_only: bool = False) -> None:
        self.marks = Marks(ascii_only)
        self.tab = "locations"
        self.lists: dict[str, list[dict[str, Any]]] = {t: [] for t in TABS}
        self.counts: dict[str, dict[str, int]] = {t: {"count": 0, "new": 0, "updated": 0} for t in TABS}
        self.cursor: dict[str, int] = {t: 0 for t in TABS}
        self.details: dict[str, dict[str, Any]] = {}
        self.query = ""
        self.unseen_only = False
        self.read: set[str] = set()  # read during this opening: their marks stay on screen until it closes
        self.pending: list[str] = []  # read, but not yet sent to the server
        self.link_mode = False  # the cursor is on the detail's links instead of the list
        self.link_index = 0
        self.trail: list[tuple[str, str]] = []  # (tab, entity id) to go back to

    # ---- loading ------------------------------------------------------------------------

    def load_summary(self, summary: dict[str, Any]) -> None:
        for c in summary.get("categories") or []:
            if c.get("id") in self.counts:
                self.counts[c["id"]] = {k: int(c.get(k) or 0) for k in ("count", "new", "updated")}

    def load_list(self, category: str, data: dict[str, Any]) -> None:
        if category not in self.lists:
            return
        keep = self.current_id if category == self.tab else None
        self.lists[category] = [e for e in data.get("entries") or [] if isinstance(e, dict)]
        self.cursor[category] = self.index_of(category, keep) if keep else 0
        self.details = {k: v for k, v in self.details.items() if k in {e["id"] for t in TABS for e in self.lists[t]}}

    def index_of(self, category: str, entity_id: str | None) -> int:
        return next((i for i, e in enumerate(self.lists[category]) if e["id"] == entity_id), 0)

    def load_detail(self, detail: dict[str, Any]) -> None:
        self.details[detail["id"]] = detail

    # ---- the cursor ---------------------------------------------------------------------

    @property
    def entries(self) -> list[dict[str, Any]]:
        rows = self.lists[self.tab]
        return [e for e in rows if self.unread(e)] if self.unseen_only else rows

    @property
    def current(self) -> dict[str, Any] | None:
        rows = self.entries
        return rows[min(self.cursor[self.tab], len(rows) - 1)] if rows else None

    @property
    def current_id(self) -> str | None:
        return self.current["id"] if self.current else None

    @property
    def current_detail(self) -> dict[str, Any] | None:
        return self.details.get(self.current_id or "")

    def unread(self, entry: dict[str, Any]) -> bool:
        return bool(entry.get("status")) and entry["id"] not in self.read

    def unread_count(self, category: str | None = None) -> int:
        rows = self.lists[category] if category else [e for t in TABS for e in self.lists[t]]
        return sum(1 for e in rows if self.unread(e))

    def move(self, delta: int) -> None:
        if self.link_mode:
            links = self.links()
            self.link_index = max(0, min(self.link_index + delta, len(links) - 1))
            return
        rows = self.entries
        if rows:
            self.cursor[self.tab] = max(0, min(self.cursor[self.tab] + delta, len(rows) - 1))

    def move_to(self, end: bool) -> None:
        rows = self.entries
        self.cursor[self.tab] = len(rows) - 1 if end and rows else 0

    def switch_tab(self, tab: str | None = None, step: int = 0) -> None:
        if tab is None:
            tab = TABS[(TABS.index(self.tab) + step) % len(TABS)]
        if tab in TABS:
            self.tab, self.link_mode = tab, False

    def select(self, category: str, entity_id: str) -> bool:
        """Put the cursor on an entity of a tab, clearing the filter that could hide it. False when it is not there."""
        if entity_id not in {e["id"] for e in self.lists.get(category, ())}:
            return False
        self.tab, self.link_mode, self.unseen_only = category, False, False
        self.cursor[category] = self.index_of(category, entity_id)
        return True

    def next_unread(self) -> bool:
        """Jump to the next entry with an unread mark, across the tabs, after the cursor. False when none is left."""
        order = [(t, i) for t in TABS for i, _ in enumerate(self.lists[t])]
        here = (self.tab, self.index_of(self.tab, self.current_id)) if self.current_id else (TABS[0], -1)
        start = order.index(here) + 1 if here in order else 0
        for tab, i in order[start:] + order[:start]:
            entry = self.lists[tab][i]
            if self.unread(entry):
                return self.select(tab, entry["id"])
        return False

    def focus_name(self, text: str) -> str:
        """Open what `/compendium NAME` asked for: an exact or unique-prefix name match across the lists
        ("found"), otherwise the first tab with a partial match, which also becomes the filter ("filtered")."""
        wanted = text.strip().casefold()
        rows = [(t, e) for t in TABS for e in self.lists[t]]
        exact = [(t, e) for t, e in rows if e["name"].casefold() == wanted]
        prefix = [(t, e) for t, e in rows if e["name"].casefold().startswith(wanted)]
        for found in (exact, prefix if len(prefix) == 1 else []):
            if found:
                self.select(found[0][0], found[0][1]["id"])
                return "found"
        partial = [(t, e) for t, e in rows if wanted in e["name"].casefold()]
        if len(partial) == 1:
            self.select(partial[0][0], partial[0][1]["id"])
            return "found"
        if partial:
            self.tab, self.query = partial[0][0], text.strip()
            return "filtered"
        return "none"

    # ---- reading marks ------------------------------------------------------------------

    def mark_read(self, entity_id: str) -> bool:
        """The player has looked at an entry. Returns True when that is news to send to the server."""
        entry = next((e for t in TABS for e in self.lists[t] if e["id"] == entity_id), None)
        if entry is None or not entry.get("status") or entity_id in self.read:
            return False
        self.read.add(entity_id)
        self.pending.append(entity_id)
        return True

    def mark_all_read(self) -> None:
        for t in TABS:
            for e in self.lists[t]:
                if e.get("status"):
                    self.read.add(e["id"])
        self.pending.clear()

    def take_pending(self) -> list[str]:
        out, self.pending = self.pending, []
        return out

    def requeue(self, ids: list[str]) -> None:
        self.pending = [*ids, *self.pending]

    # ---- links in the detail ------------------------------------------------------------

    def links(self) -> list[tuple[str, dict[str, Any]]]:
        """What the detail points at: (heading, {id, name, kind, category}) for the parent, the children and the
        related entities, in the order they are drawn."""
        d = self.current_detail
        if not d:
            return []
        out: list[tuple[str, dict[str, Any]]] = []
        if d.get("parent"):
            out.append(("Inside", d["parent"]))
        out += [("Places inside", c) for c in d.get("children") or []]
        out += [("See also", r) for r in d.get("related") or []]
        return out

    def enter_links(self) -> bool:
        if not self.links():
            return False
        self.link_mode, self.link_index = True, 0
        return True

    def leave_links(self) -> None:
        self.link_mode = False

    def follow(self) -> str | None:
        """Jump to the link under the cursor. Returns its id, or None if it is not in the lists (they are stale)."""
        links = self.links()
        if not self.link_mode or not links:
            return None
        target = links[min(self.link_index, len(links) - 1)][1]
        category = target.get("category") or self._category_of(target["id"])
        here = (self.tab, self.current_id)
        if category and self.select(category, target["id"]):
            self.trail.append((here[0], here[1] or ""))
            return target["id"]
        return None

    def _category_of(self, entity_id: str) -> str | None:
        return next((t for t in TABS if any(e["id"] == entity_id for e in self.lists[t])), None)

    def back(self) -> bool:
        while self.trail:
            tab, entity_id = self.trail.pop()
            if entity_id and self.select(tab, entity_id):
                return True
        return False

    # ---- drawing ------------------------------------------------------------------------

    def tabs_text(self) -> Text:
        text = Text()
        for i, tab in enumerate(TABS, 1):
            unread = self.unread_count(tab)
            label = f"{i} {TITLES[tab]} ({self.counts[tab]['count']})" + (f" {self.marks.star}{unread}" if unread else "")
            text.append(f" {label} ", style="reverse bold" if tab == self.tab else "")
            text.append(" ")
        return text

    def list_lines(self, width: int) -> tuple[list[Text], int]:
        """The list pane's lines and the line the cursor is on (-1 when the list is empty)."""
        rows = self.entries
        if not rows:
            return [Text(EMPTY if not (self.query or self.unseen_only) else "No entries match.", style="dim")], -1
        lines: list[Text] = []
        cursor_line = -1
        current = self.cursor[self.tab]
        for i, entry in enumerate(rows):
            status = entry.get("status")
            tag = status or ""
            mark = (self.marks.star + " ") if status else "  "
            indent = "  " * int(entry.get("depth") or 0)
            room = max(width - len(tag) - 1, 8)
            name = f"{mark}{indent}{entry['name']}"
            name = name if len(name) <= room else name[: room - 1] + self.marks.ellipsis
            style = STATUS_STYLE.get(status or "", "") if entry["id"] not in self.read else "dim"
            line = Text(name.ljust(width - len(tag)), style=style)
            line.append(tag, style=style)
            if i == current:
                cursor_line = len(lines)
                line.stylize("reverse")
            lines.append(line)
        return lines, cursor_line

    def detail_lines(self, width: int) -> tuple[list[Text], int]:
        """The detail pane's lines and the line of the selected link (-1 when not on a link)."""
        d = self.current_detail
        entry = self.current
        if entry is None:
            return [], -1
        if d is None:
            return [Text("Loading...", style="dim")], -1
        wrap = max(width - 2, 10)
        star = self.marks.star
        lines: list[Text] = []
        head = Text(d["name"][: wrap - len(d.get("kind", "")) - 2], style="bold")
        head.append(f"  {d.get('kind', '')}", style="dim")
        lines.append(head)
        extra = []
        if d.get("path"):
            extra.append("in " + f" {self.marks.crumb} ".join(p["name"] for p in d["path"]))
        if d.get("aliases"):
            extra.append("also called: " + ", ".join(d["aliases"]))
        for note in extra:
            lines += [Text(part, style="dim") for part in textwrap.wrap(note, wrap) or [""]]
        facts = d.get("facts") or []
        plain = [f for f in facts if not f.get("label")]  # the description: no heading, no indent
        if plain:
            lines.append(Text(""))
        for fact in plain:
            lines += self._fact_lines(d, fact, wrap, indent=0)
        label = object()
        for fact in (f for f in facts if f.get("label")):  # the other properties, under their headings
            if fact["label"] != label:
                label = fact["label"]
                lines.append(Text(""))
                lines.append(Text(label, style="bold cyan"))
            lines += self._fact_lines(d, fact, wrap, indent=2)
        selected = -1
        links = self.links()
        heading = None
        for n, (title, target) in enumerate(links):
            if title != heading:
                heading = title
                lines.append(Text(""))
                lines.append(Text(title, style="bold cyan"))
            tag = f"  {target.get('kind', '')}" + (f"  {target['status']}" if target.get("status") else "")
            room = max(wrap - len(tag) - 4, 6)
            name = target["name"] if len(target["name"]) <= room else target["name"][: room - 1] + self.marks.ellipsis
            row = Text(f"  {self.marks.arrow} {name}")
            row.append(tag, style=STATUS_STYLE.get(target.get("status") or "", "dim"))
            if self.link_mode and n == self.link_index:
                row.stylize("reverse")
                selected = len(lines)
            lines.append(row)
        return lines, selected

    def _fact_lines(self, d: dict[str, Any], fact: dict[str, Any], wrap: int, indent: int) -> list[Text]:
        new = fact.get("new") and d["id"] not in self.read
        lead = self.marks.star + " " if new else ""
        pad = " " * indent
        body = textwrap.wrap(fact["text"], max(wrap - indent - 2, 8)) or [""]
        out = [
            Text(pad + (lead if j == 0 else " " * len(lead)) + part, style="green" if new else "")
            for j, part in enumerate(body)
        ]
        if fact.get("via"):  # whose starting knowledge it is
            tag = f"{self.marks.dot} {', '.join(fact['via'])}"
            if out[-1].cell_len + len(tag) + 2 <= wrap:
                out[-1].append(f"  {tag}", style="dim")
            else:
                out.append(Text(pad + " " * len(lead) + tag, style="dim"))
        return out

    def help_text(self) -> str:
        base = "←→ tab  ↑↓ move  Tab links  / filter  u unread only  n next unread  a all read  r refresh  Esc close"
        if self.marks.star == "*":
            base = "Left/Right tab  Up/Down move  Tab links  / filter  u unread  n next unread  a all read  Esc close"
        return base
