"""The context viewer screen (debug servers only): the model's next request as a colored, collapsible tree."""

import io
from collections.abc import Callable

from rich.console import Console
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Static

from aigm_client.api import ApiClient, ApiError
from aigm_client.context_model import ContextModel

_console = Console(file=io.StringIO(), force_terminal=True, color_system="truecolor", width=500)
HELP = "Enter/Space open or close   ↑↓ move   PgUp/PgDn scroll   e open all   c reset   r refresh   Esc/q/Ctrl+K close"
HELP_ASCII = "Enter/Space open/close  Up/Down move  PgUp/PgDn scroll  e open all  c reset  r refresh  Esc/q close"


def not_available_message(error: ApiError) -> str:
    if error.status == 404:
        return "This server does not offer the context view. Start it with: aigm --debug"
    return f"Could not load the context: {error.message}"


class ContextView(ScrollView):
    """Draws the model's lines; the cursor sits on a row and moves over the visible rows."""

    can_focus = True
    BINDINGS = [
        Binding("enter,space", "toggle", "Open/close", show=False),
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("home", "edge(False)", "Top", show=False),
        Binding("end", "edge(True)", "Bottom", show=False),
        Binding("e", "expand_all", "Open all", show=False),
        Binding("c", "collapse_all", "Reset", show=False),
    ]
    DEFAULT_CSS = "ContextView { height: 1fr; width: 1fr; }"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model: ContextModel | None = None
        self.message = "Loading..."
        self._strips: list[Strip] = []
        self._where: dict[str, int] = {}

    # ---- content ------------------------------------------------------------------------

    def show_message(self, message: str) -> None:
        self.model, self.message = None, message
        self.rebuild()

    def show_model(self, model: ContextModel) -> None:
        self.model = model
        self.rebuild()

    def rebuild(self, follow_cursor: bool = True) -> None:
        width = max(self.size.width, 20)
        if self.model is None:
            texts, self._where = [Text(self.message)], {}
        else:
            texts, self._where = self.model.lines(width)
        cursor_line = self._where.get(self.model.cursor) if self.model else None
        self._strips = []
        for i, text in enumerate(texts):
            if i == cursor_line:
                text = text.copy()
                text.stylize("reverse")
            self._strips.append(Strip(list(text.render(_console, end=""))).adjust_cell_length(width))
        self.virtual_size = Size(width, len(self._strips))
        if follow_cursor and cursor_line is not None:
            top, height = int(self.scroll_offset.y), max(self.size.height, 1)
            if cursor_line < top:
                self.scroll_to(y=cursor_line, animate=False)
            elif cursor_line >= top + height:
                self.scroll_to(y=cursor_line - height + 1, animate=False)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        index = y + int(self.scroll_offset.y)
        if 0 <= index < len(self._strips):
            return self._strips[index]
        return Strip.blank(self.size.width)

    def on_resize(self, event: events.Resize) -> None:
        self.rebuild(follow_cursor=False)

    # ---- actions ------------------------------------------------------------------------

    def action_toggle(self) -> None:
        if self.model and self.model.cursor:
            self.model.toggle(self.model.cursor)
            self.rebuild()

    def action_move(self, delta: int) -> None:
        if self.model:
            self.model.move(delta)
            self.rebuild()

    def action_page(self, direction: int) -> None:
        if self.model:
            self.model.move(direction * max(self.size.height - 1, 1))
            self.rebuild()

    def action_edge(self, end: bool) -> None:
        if self.model:
            self.model.move_to(end)
            self.rebuild()

    def action_expand_all(self) -> None:
        if self.model:
            self.model.expand_all()
            self.rebuild()

    def action_collapse_all(self) -> None:
        if self.model:
            self.model.collapse_all()
            self.rebuild()

    def on_click(self, event: events.Click) -> None:
        if not self.model:
            return
        line = event.y + int(self.scroll_offset.y)
        row = next((node_id for node_id, at in self._where.items() if at == line), None)
        if row is not None:
            self.model.cursor = row
            self.model.toggle(row)
            self.rebuild()


class ContextScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    ContextScreen { background: $surface; }
    #ctx-head { height: auto; min-height: 1; padding: 0 1; background: $boost; text-style: bold; }
    #ctx-help { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("escape,q", "close", "Close", show=False),
        Binding("ctrl+k", "close", "Close", show=False, priority=True),
        Binding("r", "refresh_context", "Refresh", show=False),
    ]

    def __init__(self, api: ApiClient, draft: Callable[[], str], ascii_only: bool = False) -> None:
        super().__init__()
        self.api, self.draft, self.ascii_only = api, draft, ascii_only
        self.model: ContextModel | None = None

    def compose(self) -> ComposeResult:
        yield Static("Context", id="ctx-head", markup=False)
        yield ContextView(id="ctx-view")
        yield Static(HELP_ASCII if self.ascii_only else HELP, id="ctx-help", markup=False)

    @property
    def view(self) -> ContextView:
        return self.query_one("#ctx-view", ContextView)

    def on_mount(self) -> None:
        self.view.focus()
        self.run_worker(self.load(), exclusive=True, group="context")

    async def load(self) -> None:
        """Fetch the context for the text typed so far. A refresh keeps what the user has opened."""
        head = self.query_one("#ctx-head", Static)
        try:
            data = await self.api.context(self.draft())
        except ApiError as e:
            self.model = None
            head.update("Context")
            self.view.show_message(not_available_message(e))
            return
        if self.model is None:
            self.model = ContextModel(data, self.ascii_only)
        else:
            self.model.apply(data)
        head.update(self.model.header_text)
        self.view.show_model(self.model)

    def action_refresh_context(self) -> None:
        self.run_worker(self.load(), exclusive=True, group="context")

    def action_close(self) -> None:
        self.dismiss(None)
