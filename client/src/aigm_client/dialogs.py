"""Modal dialogs for save / load / new game / confirmation."""

import re
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from aigm_client.api import ApiClient, ApiError
from aigm_client.session import story_note

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

DIALOG_CSS = """
.dialog { width: 64; height: auto; max-height: 90%; padding: 1 2; border: thick $primary;
          background: $surface; }
.dialog .title { text-style: bold; margin-bottom: 1; }
.dialog .buttons { height: auto; margin-top: 1; align-horizontal: right; }
.dialog .buttons Button { margin-left: 1; }
.dialog .error { color: $error; }
.dialog .warn { color: $warning; }
.dialog OptionList { height: auto; max-height: 10; }
"""


def suggest_name() -> str:
    return datetime.now().strftime("game-%Y%m%d-%H%M")


def describe(h: dict) -> str:
    row = f"{h['name']:<24} {h.get('message_count', '?'):>4} msgs  {str(h.get('saved_at', ''))[:16].replace('T', ' ')}"
    story = story_note(h.get("story"))
    return f"{row}  {story}" if story else row


class _Dialog(ModalScreen):
    DEFAULT_CSS = "_Dialog { align: center middle; }\n" + DIALOG_CSS
    BINDINGS = [("escape", "cancel", "Cancel")]

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmDialog(_Dialog):
    def __init__(self, message: str, yes_label: str = "Yes") -> None:
        super().__init__()
        self.message, self.yes_label = message, yes_label

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.message, markup=False)
            with Horizontal(classes="buttons"):
                yield Button(self.yes_label, id="yes", variant="warning")
                yield Button("Cancel", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


class SaveDialog(_Dialog):
    """Returns the chosen save name, or None. The app performs the save (and overwrite prompt)."""

    def __init__(self, api: ApiClient, default_name: str) -> None:
        super().__init__()
        self.api, self.default_name = api, default_name

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Save game", classes="title")
            yield Input(value=self.default_name, id="name", placeholder="name (letters, digits, - _)")
            yield Static("", id="error", classes="error", markup=False)
            yield Label("Existing saves (select to reuse a name):")
            yield OptionList(id="saves")
            with Horizontal(classes="buttons"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()
        self.run_worker(self._load_list())

    async def _load_list(self) -> None:
        ol = self.query_one("#saves", OptionList)
        try:
            for h in await self.api.list_histories():
                ol.add_option(Option(describe(h), id=h["name"]))
        except ApiError as e:
            self.query_one("#error", Static).update(e.message)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.query_one("#name", Input).value = str(event.option.id)

    def _submit(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        if not NAME_RE.match(name):
            self.query_one("#error", Static).update("Use 1-64 letters, digits, '-' or '_'.")
            return
        self.dismiss(name)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._submit()
        else:
            self.dismiss(None)


class LoadDialog(_Dialog):
    """Returns the chosen save name, or None. Can also delete saves (with confirmation)."""

    def __init__(self, api: ApiClient, dirty: bool) -> None:
        super().__init__()
        self.api, self.dirty = api, dirty
        self._confirm_delete: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Load game", classes="title")
            yield OptionList(id="saves")
            yield Static("", id="preview", markup=False)
            yield Static("", id="error", classes="error", markup=False)
            if self.dirty:
                yield Static("Unsaved changes in the current game will be lost.", classes="warn")
            with Horizontal(classes="buttons"):
                yield Button("Load", id="load", variant="primary")
                yield Button("Delete", id="delete", variant="error")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.run_worker(self._load_list())

    async def _load_list(self) -> None:
        ol = self.query_one("#saves", OptionList)
        ol.clear_options()
        try:
            saves = await self.api.list_histories()
        except ApiError as e:
            self.query_one("#error", Static).update(e.message)
            return
        for h in saves:
            ol.add_option(Option(describe(h), id=h["name"]))
        if saves:
            ol.highlighted = 0
            ol.focus()
        else:
            self.query_one("#preview", Static).update("No saved games yet.")
        self.query_one("#load", Button).disabled = not saves
        self.query_one("#delete", Button).disabled = not saves

    def _current(self) -> str | None:
        ol = self.query_one("#saves", OptionList)
        if ol.highlighted is None:
            return None
        opt = ol.get_option_at_index(ol.highlighted)
        return str(opt.id) if opt.id else None

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._reset_delete()
        if event.option.id:
            self.run_worker(self._preview(str(event.option.id)), exclusive=True, group="preview")

    async def _preview(self, name: str) -> None:
        preview = self.query_one("#preview", Static)
        try:
            info = await self.api.history_info(name)
        except ApiError as e:
            preview.update(e.message)
            return
        last = info.get("last_message_preview")
        text = f'Last: "{last}"' if last else f"{info.get('message_count', 0)} messages"
        story = story_note(info.get("story"))
        preview.update(f"{text}\n{story.capitalize()}" if story else text)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.dismiss(str(event.option.id))

    def _reset_delete(self) -> None:
        self._confirm_delete = None
        try:
            self.query_one("#delete", Button).label = "Delete"
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "load":
            name = self._current()
            if name:
                self.dismiss(name)
        elif bid == "delete":
            name = self._current()
            if not name:
                return
            if self._confirm_delete != name:
                self._confirm_delete = name
                event.button.label = "Really delete?"
            else:
                self.run_worker(self._delete(name))
        else:
            self.dismiss(None)

    async def _delete(self, name: str) -> None:
        try:
            await self.api.delete(name)
        except ApiError as e:
            self.query_one("#error", Static).update(e.message)
        self._reset_delete()
        await self._load_list()


class NewGameDialog(_Dialog):
    """Returns "discard", "save" (save first), or None."""

    def __init__(self, dirty: bool) -> None:
        super().__init__()
        self.dirty = dirty

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("New game", classes="title")
            yield Label("Start a new game?")
            if self.dirty:
                yield Static("The current game has unsaved changes.", classes="warn")
            with Horizontal(classes="buttons"):
                if self.dirty:
                    yield Button("Save first...", id="save", variant="primary")
                    yield Button("Discard", id="discard", variant="error")
                else:
                    yield Button("Start new game", id="discard", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        self.dismiss(bid if bid in ("save", "discard") else None)
