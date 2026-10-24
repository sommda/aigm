"""The status screen's model: the pages the server sent, which tab is showing, and the lines to draw. Pure logic with
no terminal in it, so it can be tested directly (docs/STATUS.md 8). The server decides what the pages say; this only
lays them out."""

import textwrap
from typing import Any

from rich.text import Text

STATUS_TAB = "status"
CHARACTER_PREFIX = "c:"
NO_LOCATION = "The party's location has not been recorded yet."
MAX_FIRST_COLUMN = 24


def wrap(text: str, width: int, indent: str = "", first: str | None = None) -> list[str]:
    return textwrap.wrap(
        text, max(width, 10), initial_indent=indent if first is None else first, subsequent_indent=indent
    ) or [indent if first is None else first]


class StatusModel:
    def __init__(self, ascii_only: bool = False) -> None:
        self.dot = "-" if ascii_only else "·"
        self.dash = "-" if ascii_only else "—"
        self.tab = STATUS_TAB
        self.pages: dict[str, dict[str, Any]] = {}
        self.roster: list[dict[str, Any]] = []

    @property
    def tabs(self) -> list[tuple[str, str]]:
        """Status, then one tab per party member, by first name."""
        return [(STATUS_TAB, "Status")] + [
            (CHARACTER_PREFIX + c["name"], c["name"].split()[0]) for c in self.roster if c.get("name")
        ]

    def load(self, tab: str, page: dict[str, Any]) -> None:
        self.pages[tab] = page

    def load_roster(self, data: dict[str, Any]) -> None:
        self.roster = [c for c in data.get("characters") or [] if isinstance(c, dict)]
        if self.tab not in {t for t, _ in self.tabs}:
            self.tab = STATUS_TAB

    def find_tab(self, query: str) -> str | None:
        """The character tab a name or the start of one refers to (`/sheet toby`)."""
        wanted = query.strip().casefold()
        if not wanted:
            return None
        names = [(t, n) for t, n in self.tabs if t != STATUS_TAB]
        for tab_id, _ in names:
            if tab_id[len(CHARACTER_PREFIX):].casefold() == wanted:
                return tab_id
        return next((t for t, _ in names if t[len(CHARACTER_PREFIX):].casefold().startswith(wanted)), None)

    @property
    def character(self) -> str | None:
        """The name of the character whose tab is showing, or None on the status tab."""
        return self.tab[len(CHARACTER_PREFIX):] if self.tab.startswith(CHARACTER_PREFIX) else None

    def switch(self, tab: str | None = None, step: int = 0) -> bool:
        ids = [t for t, _ in self.tabs]
        new = tab if tab in ids else ids[(ids.index(self.tab) + step) % len(ids)] if step else self.tab
        changed = new != self.tab
        self.tab = new
        return changed

    def tabs_text(self) -> Text:
        out = Text()
        for tab_id, title in self.tabs:
            out.append(f" {title} ", style="reverse bold" if tab_id == self.tab else "dim")
            out.append(" ")
        return out

    def help_text(self) -> str:
        return "Left/Right or 1-9 tab   Up/Down/PgUp/PgDn scroll   r refresh   q or Esc close"

    # ---- drawing ------------------------------------------------------------------------

    def lines(self, width: int) -> list[Text]:
        page = self.pages.get(self.tab)
        if page is None:
            return []
        return self._character_lines(page, width) if self.character else self._status_lines(page, width)

    def _character_lines(self, page: dict[str, Any], width: int) -> list[Text]:
        out = [Text(page["name"], style="bold")]
        if page.get("headline"):
            out.append(Text(page["headline"]))
        vitals = Text()
        if page.get("hp"):
            vitals.append(f"HP {page['hp']}", style="bold green")
        if page.get("conditions"):
            vitals.append(("  " if vitals else "") + ", ".join(page["conditions"]), style="yellow")
        if vitals:
            out.append(vitals)
        if page.get("progress"):
            out.append(Text(page["progress"], style="dim"))
        for section in page.get("sections") or []:
            self._heading(out, section["title"])
            for line in section["lines"]:
                out.extend(Text(t) for t in wrap(line, width, "    ", "  "))
        if page.get("text"):
            self._heading(out, "Sheet")
            out.append(Text("No tidy version of this sheet was written; here it is as the GM wrote it.", style="dim"))
            for paragraph in str(page["text"]).split("\n"):
                if paragraph.strip():
                    out.extend(Text(t) for t in wrap(paragraph.strip(), width, "  "))
                else:
                    out.append(Text(""))
        return out

    def _heading(self, out: list[Text], title: str) -> None:
        out.append(Text(""))
        out.append(Text(title, style="bold cyan"))

    def _status_lines(self, page: dict[str, Any], width: int) -> list[Text]:
        out: list[Text] = []
        loc = page.get("location")
        if not loc:
            out.append(Text(NO_LOCATION, style="dim"))
        else:
            out.append(Text(loc["name"], style="bold"))
            path = [p["name"] for p in loc.get("path") or []]
            when = f"{loc['time']} {self.dot} {loc['period']}" if loc.get("time") else ""
            where = ("in " + ", ".join(reversed(path))) if path else ""
            sub = f"  {self.dot}  ".join(x for x in (where, when) if x)
            if sub:
                out.append(Text(sub, style="dim"))
            if loc.get("overview"):
                out.append(Text(""))
                out.extend(Text(line) for line in wrap(loc["overview"], width))
            self._people(out, page.get("here") or [], "Here", width)
            items = page.get("items") or []
            if items:
                self._heading(out, "Key items")
                for item in items:
                    out.extend(Text(line) for line in wrap(item, width, "  ", f"{self.dot} "))
            self._people(out, page.get("inside") or [], "Inside", width)
            exits = page.get("exits") or []
            if exits:
                self._heading(out, "Ways out")
                for e in exits:
                    out.extend(self._named(e["name"], e.get("route"), width))
        table = page.get("table") or {}
        if table.get("rows"):
            self._heading(out, "Everyone here")
            out.extend(self._table(table["columns"], table["rows"], width))
        return out

    def _named(self, name: str, text: str | None, width: int) -> list[Text]:
        """`name — text`, wrapped under the text, for a person, place or way."""
        if not text:
            return [Text(f"{self.dot} {name}", style="bold")]
        lines = wrap(text, width - 2, "    ")
        first = Text(f"{self.dot} ")
        first.append(name, style="bold")
        first.append(f" {self.dash}")
        return [first, *(Text(line) for line in lines)]

    def _people(self, out: list[Text], entries: list[dict[str, Any]], title: str, width: int) -> None:
        if not entries:
            return
        self._heading(out, title)
        for e in entries:
            out.extend(self._named(e["name"], e.get("summary"), width))

    def _table(self, columns: list[str], rows: list[list[str]], width: int) -> list[Text]:
        """A text table: the last column takes the rest of the width and wraps."""
        sizes = [min(max(len(str(c)) for c in col), MAX_FIRST_COLUMN) for col in zip(columns, *rows)]
        sizes[-1] = max(width - sum(sizes[:-1]) - 2 * (len(sizes) - 1), 10)
        gap = "  "
        out = []
        head = Text()
        for size, name in zip(sizes, columns):
            head.append(name.ljust(size) + gap, style="bold dim")
        out.append(head)
        for row in rows:
            last = len(sizes) - 1
            cells = [wrap(str(c), size) if i == last else [str(c)[:size]] for i, (c, size) in enumerate(zip(row, sizes))]
            for n in range(max(len(c) for c in cells)):
                line = Text()
                for i, (cell, size) in enumerate(zip(cells, sizes)):
                    text = cell[n] if n < len(cell) else ""
                    line.append(text.ljust(size) + gap, style="bold" if i == 0 else "")
                out.append(line)
        return out
