"""The compendium screen: what the player has learned about the world (docs/COMPENDIUM.md 6)."""

import io
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Input, Static

from aigm_client.api import ApiClient, ApiError
from aigm_client.compendium_model import TABS, CompendiumModel

_console = Console(file=io.StringIO(), force_terminal=True, color_system="truecolor", width=500)
NARROW = 100  # below this many columns the list and the detail take turns
DWELL = 1.0  # seconds the cursor rests on an entry before it counts as read
FLUSH = 5.0  # how often read marks are sent while the screen is open


def not_available_message(error: ApiError) -> str:
    if error.status == 404:
        return "This server does not offer the compendium."
    return f"Could not load the compendium: {error.message}  (r to retry)"


class LinesView(ScrollView):
    """Draws a list of lines and keeps one of them in view."""

    DEFAULT_CSS = "LinesView { height: 1fr; }"

    def __init__(self, focusable: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.can_focus = focusable  # the list holds the focus so keys reach the screen; Tab is the screen's own
        self._strips: list[Strip] = []

    def show(self, texts: list[Text], follow: int = -1) -> None:
        width = max(self.size.width, 10)
        self._strips = [Strip(list(t.render(_console, end=""))).adjust_cell_length(width) for t in texts]
        self.virtual_size = Size(width, len(self._strips))
        if follow >= 0:
            top, height = int(self.scroll_offset.y), max(self.size.height, 1)
            if follow < top:
                self.scroll_to(y=follow, animate=False)
            elif follow >= top + height:
                self.scroll_to(y=follow - height + 1, animate=False)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        index = y + int(self.scroll_offset.y)
        return self._strips[index] if 0 <= index < len(self._strips) else Strip.blank(self.size.width)


class CompendiumScreen(ModalScreen[list[str]]):
    """Dismisses with the ids it has not yet told the server were read."""

    DEFAULT_CSS = """
    CompendiumScreen { background: $surface; }
    #cp-tabs { height: 1; padding: 0 1; background: $boost; }
    #cp-body { height: 1fr; }
    #cp-list { width: 45%; padding: 0 1; }
    #cp-detail { width: 1fr; padding: 0 1; border-left: tall $primary 40%; }
    #cp-filter { display: none; height: 3; }
    #cp-help { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("escape", "escape", "Close", show=False),
        Binding("q", "close", "Close", show=False),
        Binding("ctrl+g,f5", "close", "Close", show=False, priority=True),
        Binding("left", "tab(-1)", "Previous tab", show=False),
        Binding("right", "tab(1)", "Next tab", show=False),
        Binding("1", "go_tab('locations')", "Locations", show=False),
        Binding("2", "go_tab('characters')", "Characters", show=False),
        Binding("3", "go_tab('other')", "Other", show=False),
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("home", "edge(False)", "Top", show=False),
        Binding("end", "edge(True)", "Bottom", show=False),
        Binding("pageup", "scroll_detail(-1)", "Scroll up", show=False),
        Binding("pagedown", "scroll_detail(1)", "Scroll down", show=False),
        Binding("enter", "open", "Open", show=False),
        Binding("tab", "links", "Links", show=False),
        Binding("backspace", "back", "Back", show=False),
        Binding("slash", "filter", "Filter", show=False),
        Binding("n", "next_unread", "Next unread", show=False),
        Binding("a", "all_read", "All read", show=False),
        Binding("u", "unread_only", "Unread only", show=False),
        Binding("r", "refresh_all", "Refresh", show=False),
    ]

    def __init__(
        self,
        api: ApiClient,
        ascii_only: bool = False,
        on_counts: Callable[[dict[str, Any]], None] | None = None,
        tab: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__()
        self.api, self.ascii_only, self.on_counts = api, ascii_only, on_counts
        self.model = CompendiumModel(ascii_only)
        self.start_tab, self.start_name = tab, name
        self.error = ""
        self.detail_open = False  # narrow terminals: showing the detail instead of the list
        self._dwell = None

    def compose(self) -> ComposeResult:
        yield Static("", id="cp-tabs")
        with Horizontal(id="cp-body"):
            yield LinesView(focusable=True, id="cp-list")
            yield LinesView(id="cp-detail")
        yield Input(id="cp-filter", placeholder="Filter by name (Enter to apply, Esc to clear)")
        yield Static(self.model.help_text(), id="cp-help", markup=False)

    def on_mount(self) -> None:
        self.query_one("#cp-list", LinesView).focus()
        self.set_interval(FLUSH, self._flush_later)
        self.run_worker(self.load(), exclusive=True, group="cp-load")

    def on_resize(self, event: events.Resize) -> None:
        self.redraw()

    # ---- loading ------------------------------------------------------------------------

    async def load(self) -> None:
        """Fetch the counts and the three lists. Read marks go first, so a refresh does not bring them back."""
        await self.flush()
        m = self.model
        try:
            summary = await self.api.compendium()
            m.load_summary(summary)
            for tab in TABS:
                data = await self.api.compendium_list(
                    tab, q=m.query if tab == m.tab else "", sort="tree" if tab == "locations" else "name"
                )
                m.load_list(tab, data)
        except ApiError as e:
            self.error = not_available_message(e)
            self.redraw()
            return
        self.error = ""
        self._report(summary)
        if self.start_tab in TABS:
            m.switch_tab(self.start_tab)
        self.start_tab = None
        if self.start_name:
            outcome = m.focus_name(self.start_name)
            if outcome == "none":
                self.app.notify(f"Nothing known by the name {self.start_name!r}.", severity="warning")
            elif outcome == "filtered":
                await self.reload_tab()
            self.start_name = None
        self.redraw()
        await self.ensure_detail()

    async def reload_tab(self) -> None:
        m = self.model
        try:
            m.load_list(m.tab, await self.api.compendium_list(m.tab, q=m.query, sort="tree" if m.tab == "locations" else "name"))
        except ApiError as e:
            self.error = not_available_message(e)
        self.redraw()
        await self.ensure_detail()

    async def ensure_detail(self) -> None:
        m = self.model
        entity_id = m.current_id
        if entity_id is None or entity_id in m.details:
            self.redraw()
            self._rest()
            return
        try:
            detail = await self.api.compendium_entity(entity_id)
        except ApiError:
            return
        m.load_detail(detail)
        self.redraw()
        self._rest()

    # ---- read marks ---------------------------------------------------------------------

    def _rest(self) -> None:
        """The cursor has settled on an entry: after a moment of being looked at, it counts as read."""
        if self._dwell is not None:
            self._dwell.stop()
        self._dwell = self.set_timer(DWELL, self._read_current)

    def _read_current(self) -> None:
        m = self.model
        if m.current_id in m.details and m.mark_read(m.current_id):
            self.redraw()

    def _flush_later(self) -> None:
        if self.model.pending:
            self.run_worker(self.flush(), group="cp-flush")

    async def flush(self) -> None:
        ids = self.model.take_pending()
        if not ids:
            return
        try:
            self._report(await self.api.compendium_seen(ids))
        except ApiError:
            self.model.requeue(ids)

    def _report(self, summary: dict[str, Any]) -> None:
        if self.on_counts is not None:
            self.on_counts({"new": summary.get("new", 0), "updated": summary.get("updated", 0)})

    # ---- drawing ------------------------------------------------------------------------

    def redraw(self) -> None:
        m = self.model
        self.query_one("#cp-tabs", Static).update(m.tabs_text())
        lst, detail = self.query_one("#cp-list", LinesView), self.query_one("#cp-detail", LinesView)
        narrow = self.size.width < NARROW
        lst.display = not (narrow and self.detail_open)
        detail.display = not narrow or self.detail_open
        if self.error:
            lst.show([Text(self.error, style="red")])
            detail.show([])
            return
        texts, cursor = m.list_lines(max(lst.size.width - 2, 10))
        lst.show(texts, cursor)
        texts, selected = m.detail_lines(max(detail.size.width - 2, 10))
        detail.show(texts, selected)

    # ---- actions ------------------------------------------------------------------------

    def _moved(self) -> None:
        self.redraw()
        self.run_worker(self.ensure_detail(), exclusive=True, group="cp-detail")

    def action_tab(self, step: int) -> None:
        self.model.switch_tab(step=step)
        self.detail_open = False
        self._moved()

    def action_go_tab(self, tab: str) -> None:
        self.model.switch_tab(tab)
        self.detail_open = False
        self._moved()

    def action_move(self, delta: int) -> None:
        was = self.model.current_id
        self.model.move(delta)
        if self.model.current_id != was:
            self._moved()
        else:
            self.redraw()

    def action_edge(self, end: bool) -> None:
        self.model.move_to(end)
        self._moved()

    def action_scroll_detail(self, direction: int) -> None:
        view = self.query_one("#cp-detail", LinesView)
        view.scroll_to(y=max(0, int(view.scroll_offset.y) + direction * max(view.size.height - 1, 1)), animate=False)

    def action_open(self) -> None:
        m = self.model
        if m.link_mode:
            if m.follow():
                self._moved()
            return
        if self.size.width < NARROW:
            self.detail_open = not self.detail_open
        self.redraw()

    def action_links(self) -> None:
        m = self.model
        if m.link_mode:
            m.leave_links()
        elif m.enter_links():
            self.detail_open = True
        self.redraw()

    def action_back(self) -> None:
        if self.model.back():
            self._moved()

    def action_filter(self) -> None:
        box = self.query_one("#cp-filter", Input)
        box.display = True
        box.value = self.model.query
        box.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "cp-filter":
            self.model.query = event.value.strip()
            self._close_filter()
            self.run_worker(self.reload_tab(), exclusive=True, group="cp-load")

    def _close_filter(self) -> None:
        box = self.query_one("#cp-filter", Input)
        box.display = False
        self.query_one("#cp-list", LinesView).focus()

    def action_next_unread(self) -> None:
        if self.model.next_unread():
            self._moved()

    def action_all_read(self) -> None:
        self.model.mark_all_read()
        self.run_worker(self._send_all(), group="cp-flush")
        self.redraw()

    async def _send_all(self) -> None:
        try:
            self._report(await self.api.compendium_seen(None))
        except ApiError:
            self.app.notify("Could not mark everything read.", severity="warning")

    def action_unread_only(self) -> None:
        self.model.unseen_only = not self.model.unseen_only
        self._moved()

    def action_refresh_all(self) -> None:
        self.run_worker(self.load(), exclusive=True, group="cp-load")

    def action_escape(self) -> None:
        """Esc undoes the innermost thing first: the filter box, the links, the filter, the detail, then the screen."""
        m = self.model
        box = self.query_one("#cp-filter", Input)
        if box.display:
            self._close_filter()
        elif m.link_mode:
            m.leave_links()
            self.redraw()
        elif m.query:
            m.query = ""
            self.run_worker(self.reload_tab(), exclusive=True, group="cp-load")
        elif self.detail_open:
            self.detail_open = False
            self.redraw()
        else:
            self.action_close()

    def action_close(self) -> None:
        self.dismiss(self.model.take_pending())
