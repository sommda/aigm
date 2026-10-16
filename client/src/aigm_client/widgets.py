from textual import events
from textual.reactive import reactive
from textual.strip import Strip
from textual.widget import Widget

from aigm_client.transcript import Transcript


class TranscriptView(Widget):
    """Draws the pager's visible lines. Scrolling/paging is owned by `Transcript`."""

    can_focus = False
    DEFAULT_CSS = "TranscriptView { height: 1fr; width: 1fr; }"

    def __init__(self, transcript: Transcript, **kwargs) -> None:
        super().__init__(**kwargs)
        self.transcript = transcript

    anim_top: reactive[float] = reactive(0.0, repaint=False)

    def watch_anim_top(self, value: float) -> None:
        self.transcript.view_top_override = int(round(value))
        self.refresh()

    def animate_page_turn(self, from_top: int, to_top: int) -> None:
        """Quickly slide the view from the old page to the new one so the eye can follow."""
        if from_top == to_top:
            return
        self.transcript.view_top_override = from_top
        self.anim_top = float(from_top)
        self.animate("anim_top", float(to_top), duration=0.15, easing="out_cubic", on_complete=self._turn_done)

    def _turn_done(self) -> None:
        self.transcript.view_top_override = None
        self.refresh()

    def render_line(self, y: int) -> Strip:
        lines = self.transcript.visible_lines()
        width = self.size.width
        if y < len(lines):
            return Strip(lines[y]).adjust_cell_length(width)
        return Strip.blank(width)

    def on_resize(self, event: events.Resize) -> None:
        self.transcript.set_size(event.size.width, event.size.height)
        self.app.view_changed()  # type: ignore[attr-defined]

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.app.action_advance()  # type: ignore[attr-defined]

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self.transcript.scroll_by(-3)
        self.app.view_changed()  # type: ignore[attr-defined]

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self.transcript.scroll_by(3)
        self.app.view_changed()  # type: ignore[attr-defined]
