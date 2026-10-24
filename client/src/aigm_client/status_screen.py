"""The status screen: where the party is and how everyone is doing (docs/STATUS.md 8). It asks the server for the page
it is showing when it opens, when the tab changes and when the player presses r; it never listens for events."""

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static

from aigm_client.api import ApiClient, ApiError
from aigm_client.compendium_screen import LinesView
from aigm_client.status_model import StatusModel


def not_available_message(error: ApiError) -> str:
    if error.status == 404:
        return "This server does not offer the status page."
    return f"Could not load the status page: {error.message}  (r to retry)"


class StatusScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    StatusScreen { background: $surface; }
    #st-tabs { height: 1; padding: 0 1; background: $boost; }
    #st-body { height: 1fr; padding: 0 1; }
    #st-help { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("escape,q", "close", "Close", show=False),
        Binding("f7", "close", "Close", show=False, priority=True),
        Binding("left", "tab(-1)", "Previous tab", show=False),
        Binding("right", "tab(1)", "Next tab", show=False),
        Binding("up", "scroll(-1)", "Up", show=False),
        Binding("down", "scroll(1)", "Down", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("home", "top", "Top", show=False),
        Binding("r", "refresh_page", "Refresh", show=False),
    ]

    def __init__(self, api: ApiClient, ascii_only: bool = False) -> None:
        super().__init__()
        self.api = api
        self.model = StatusModel(ascii_only)
        self.error = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="st-tabs")
        yield LinesView(focusable=True, id="st-body")
        yield Static(self.model.help_text(), id="st-help", markup=False)

    def on_mount(self) -> None:
        self.query_one("#st-body", LinesView).focus()
        self.action_refresh_page()

    def on_resize(self, event: events.Resize) -> None:
        self.redraw()

    # ---- loading ------------------------------------------------------------------------

    async def load(self) -> None:
        tab = self.model.tab
        try:
            page = await self.api.status()
        except ApiError as e:
            self.error = not_available_message(e)
        else:
            self.error = ""
            self.model.load(tab, page)
        self.redraw()

    # ---- drawing ------------------------------------------------------------------------

    def redraw(self) -> None:
        self.query_one("#st-tabs", Static).update(self.model.tabs_text())
        view = self.query_one("#st-body", LinesView)
        if self.error:
            view.show([Text(self.error, style="red")])
        else:
            view.show(self.model.lines(max(view.size.width - 2, 10)))

    # ---- actions ------------------------------------------------------------------------

    def action_refresh_page(self) -> None:
        self.run_worker(self.load(), exclusive=True, group="st-load")

    def action_tab(self, step: int) -> None:
        if self.model.switch(step=step):
            self.redraw()
            self.action_refresh_page()

    def action_scroll(self, delta: int) -> None:
        view = self.query_one("#st-body", LinesView)
        view.scroll_to(y=max(0, int(view.scroll_offset.y) + delta), animate=False)

    def action_page(self, direction: int) -> None:
        self.action_scroll(direction * max(self.query_one("#st-body", LinesView).size.height - 1, 1))

    def action_top(self) -> None:
        self.query_one("#st-body", LinesView).scroll_to(y=0, animate=False)

    def action_close(self) -> None:
        self.dismiss(None)
