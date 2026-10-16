"""Chat session view-model: applies server events to the transcript. UI-free."""

from typing import Any

from aigm_client import events as ev
from aigm_client.blocks import (
    DiceBlock,
    MarkdownBlock,
    ReasoningBlock,
    SystemBlock,
    history_to_blocks,
)
from aigm_client.transcript import Transcript


class ChatSession:
    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript
        self.busy = False  # a chat turn is in flight
        self.thinking = False
        self.game_name: str | None = None
        self.dirty = False  # unsaved changes since last save/load/new
        self.changed = False  # set whenever anything visible changed; the UI clears it
        self._text: MarkdownBlock | None = None
        self._reasoning: ReasoningBlock | None = None

    # ---- derived ------------------------------------------------------------------------

    @property
    def can_input(self) -> bool:
        """The prompt is shown only when no turn is in flight and nothing is held."""
        return not self.busy and self.transcript.held == 0

    def _touch(self) -> None:
        self.transcript.invalidate()
        self.changed = True

    # ---- turn lifecycle -----------------------------------------------------------------

    def begin_turn(self, user_text: str) -> None:
        self.transcript.start_user_message(user_text)
        self.busy = True
        self.dirty = True
        self._text = self._reasoning = None
        self._touch()

    def apply(self, event: ev.Event) -> None:
        match event:
            case ev.Text(delta=delta):
                if self._text is None:
                    self._text = MarkdownBlock()
                    self.transcript.add(self._text)
                self._text.append(delta)
            case ev.Thinking(status="start"):
                self.thinking = True
                self._text = None  # text before/after a thinking phase are separate segments
                self._reasoning = None
            case ev.Thinking(status="delta", delta=delta):
                if self._reasoning is None:
                    self._reasoning = ReasoningBlock()
                    self.transcript.add(self._reasoning)
                self._reasoning.append(delta)
            case ev.Thinking(status="end"):
                self.thinking = False
                self._reasoning = None
            case ev.ToolCall():
                self._text = None
            case ev.DiceRoll():
                self._text = None
                self.transcript.add(DiceBlock(event))
            case ev.MessageEnd():
                self._finish_turn()
            case ev.ErrorEvent(message=message):
                self._finish_turn()
                self.add_system(
                    f"Error: {message or 'unknown error'} (this turn was discarded; send it again)", "red"
                )
            case _:  # MessageStart, Unknown: nothing to show
                pass
        self._touch()

    def _finish_turn(self) -> None:
        self.busy = False
        self.thinking = False
        self._text = self._reasoning = None
        self.transcript.finalize_markdown()

    def fail(self, message: str) -> None:
        """A request failed before or outside the event stream (ApiError)."""
        self._finish_turn()
        self.add_system(f"Error: {message}", "red")

    def interrupted(self) -> None:
        self._finish_turn()
        self.add_system("[interrupted - turn discarded; send it again]", "yellow")

    # ---- other content ------------------------------------------------------------------

    def add_system(self, text: str, style: str = "dim") -> None:
        for line in text.splitlines() or [""]:
            self.transcript.add(SystemBlock(line, style))
        self._touch()

    def load_history(self, messages: list[dict[str, Any]]) -> None:
        """Replace the transcript with a server history and open on its last page."""
        self.transcript.replace_blocks(history_to_blocks(messages))
        self.busy = self.thinking = False
        self._text = self._reasoning = None
        self.dirty = False
        self._touch()

    def new_game(self) -> None:
        self.transcript.clear()
        self.busy = self.thinking = False
        self._text = self._reasoning = None
        self.game_name = None
        self.dirty = False
        self._touch()

    def mark_saved(self, name: str) -> None:
        self.game_name = name
        self.dirty = False
        self.changed = True

    def mark_loaded(self, name: str) -> None:
        self.game_name = name
        self.dirty = False
        self.changed = True
