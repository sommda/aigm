import asyncio
import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Input, Static
from textual.worker import Worker

from aigm_client.api import ApiClient, ApiError
from aigm_client.blocks import MarkdownBlock, UserBlock
from aigm_client.commands import Command, parse_command
from aigm_client.compendium_screen import CompendiumScreen
from aigm_client.status_screen import StatusScreen
from aigm_client.compendium_model import TABS
from aigm_client.context_screen import ContextScreen
from aigm_client.dialogs import ConfirmDialog, LoadDialog, NewGameDialog, SaveDialog, suggest_name
from aigm_client.session import ChatSession, intro_text, story_note
from aigm_client.transcript import Transcript
from aigm_client.widgets import PromptInput, TranscriptView, decode_prompt

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
HELP = """Commands:
  /new                  start a new game          (Ctrl+N)
  /save [NAME] [--overwrite]  save the game       (Ctrl+S)
  /load [NAME]          load a saved game         (Ctrl+O)
  /saves                list saved games
  /info NAME            show info about a saved game
  /delete NAME          delete a saved game
  /compendium [TAB|NAME]  what you have learned: locations, characters, other  (Ctrl+G)
  /status               where you are and who is with you  (F7)
  /sheet [NAME]         a character's sheet
  /reconnect            retry connecting to the server
  /quit                 quit
Keys: Space/Enter = next page, PageUp/PageDown/arrows/wheel = scroll back,
      End = back to the current page, Esc = cancel the current turn, Ctrl+T = show/hide reasoning."""
DEBUG_HELP = (
    "\nDebug server: /context (Ctrl+K) shows exactly what the model will be sent for your next message."
    "\n  /story  prints the whole story plan (spoilers)"
    "\n  /thinking [on|off]  (F6) turn the model's thinking on or off, to compare a move both ways"
)


class AigmApp(App):
    CSS = """
    #pager { height: 1; background: $boost; padding: 0 1; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    #prompt { height: 3; }
    """
    BINDINGS = [
        Binding("space,enter", "advance", "Next page", show=False),
        Binding("pagedown", "page_down", "Page down", show=False),
        Binding("pageup", "page_up", "Page up", show=False),
        Binding("down", "scroll(1)", "Scroll down", show=False),
        Binding("up", "scroll(-1)", "Scroll up", show=False),
        Binding("home", "scroll_top", "Top", show=False),
        Binding("end", "scroll_live", "Latest", show=False),
        Binding("escape", "cancel_turn", "Cancel turn", show=False),
        Binding("ctrl+s,f2", "save", "Save"),
        Binding("ctrl+o,f3", "load", "Load"),
        Binding("ctrl+n,f4", "new_game", "New game"),
        Binding("ctrl+t", "toggle_reasoning", "Reasoning"),
        # priority: the prompt's own Ctrl+K (delete to end of line) must not take it
        Binding("ctrl+k", "context", "Context", priority=True),
        Binding("f6", "thinking", "Thinking"),
        # priority for the same reason: the prompt would otherwise take it
        Binding("ctrl+g,f5", "compendium", "Compendium", priority=True),
        Binding("f7", "status", "Status", priority=True),
    ]

    def __init__(self, api: ApiClient, ascii_only: bool = False) -> None:
        super().__init__()
        self.api = api
        self.ascii_only = ascii_only
        self.debug_server = False  # set from /health: the server offers the context view
        self.has_status = False  # set from /health: the server offers the status page
        self.has_compendium = False  # set from /health: the server offers the compendium
        self.model_thinking = True  # debug servers only: whether the model thinks (F6, /thinking)
        self.transcript = Transcript(ascii_only=ascii_only)
        self.session = ChatSession(self.transcript)
        self.connected: bool | None = None
        self._turn: Worker | None = None
        self._spin = 0
        self._last_gate: tuple | None = None

    # ---- layout -------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        self.view = TranscriptView(self.transcript, id="transcript")
        yield self.view
        yield Static("", id="pager")
        yield Static("", id="status")
        yield PromptInput(id="prompt", placeholder="What do you do?")
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "AIGM"
        self.set_interval(1 / 30, self._tick)
        self.run_worker(self._startup())

    async def on_unmount(self) -> None:
        await self.api.aclose()

    # ---- startup ------------------------------------------------------------------------

    async def _startup(self) -> None:
        s = self.session
        try:
            health = await self.api.health()
            state = await self.api.chat_state()
        except ApiError as e:
            self.connected = False
            s.add_system(f"{e.message}\nStart the server, then type /reconnect.", "red")
            return
        self.connected = True
        self.debug_server = health.get("debug") is True
        self.has_compendium = health.get("compendium") is True
        self.has_status = health.get("status") is True
        self.model_thinking = health.get("thinking") is not False
        s.show_metrics = self.debug_server
        self.refresh_bindings()
        messages = state["messages"]
        s.load_history(
            messages, state.get("phase", ""), state.get("ruleset_name", ""), state.get("story"), state.get("compendium")
        )
        s.dirty = bool(messages)
        if not messages:
            s.add_system(intro_text(s.phase))

    # ---- UI refresh ---------------------------------------------------------------------

    def view_changed(self) -> None:
        self.session.changed = True

    def _tick(self) -> None:
        spin = int(time.monotonic() * 10) % len(SPINNER)
        animate = (self.session.busy or self.session.thinking) and spin != self._spin
        self._spin = spin
        if not (self.session.changed or animate):
            return
        self.session.changed = False
        self.view.refresh()
        self._update_pager()
        self._update_status()
        self._sync_input()

    def _update_pager(self) -> None:
        t = self.transcript
        if t.held > 0:
            text = f"▼ MORE ({t.held} lines buffered)  [Space/Enter]"
            if t.scrolled_back:
                text += "  (scrolled back, End to return)"
        elif t.scrolled_back:
            text = "↑ scrolled back  [End/Space to return]"
        else:
            text = ""
        self.query_one("#pager", Static).update(text)

    def _update_status(self) -> None:
        s = self.session
        if s.status:
            left = f"{SPINNER[self._spin]} {s.status}"
        elif s.thinking:
            left = f"{SPINNER[self._spin]} Thinking..."
        elif s.busy:
            left = f"{SPINNER[self._spin]} GM is writing..."
        else:
            left = "Ready"
        game = (s.game_name or "unsaved") + ("*" if s.dirty and s.game_name else "")
        conn = {True: "● connected", False: "○ offline", None: "… connecting"}[self.connected]
        mode = f"   mode: {s.phase_label}" if s.phase_label else ""
        if mode and s.ruleset_name:
            mode += f" · {s.ruleset_name}"
        story = f"   story: {s.story_label}" if s.story_label else ""
        news = f"   {'*' if self.ascii_only else '✦'} {s.compendium_unread} new" if s.compendium_unread else ""
        debug = ("   DEBUG" + ("" if self.model_thinking else " (no thinking)")) if self.debug_server else ""
        self.query_one("#status", Static).update(f"{left}{mode}{story}{news}   game: {game}   {conn}{debug}")

    def _sync_input(self) -> None:
        prompt = self.query_one("#prompt", Input)
        modal = len(self.screen_stack) > 1
        back = self.transcript.scrolled_back
        enabled = self.session.can_input and not modal and not back
        gate = (enabled, self.session.busy, self.transcript.held > 0, back, self.session.phase)
        if gate == self._last_gate:
            return
        self._last_gate = gate
        prompt.disabled = not enabled
        if enabled:
            ask = "Tell the GM..." if self.session.phase == "session_zero" else "What do you do?"
            prompt.placeholder = f"{ask}  (/help for commands)"
            prompt.focus()
        else:
            if back:
                prompt.placeholder = "Scrolled back - press End or Space to return"
            elif self.session.busy:
                prompt.placeholder = "GM is responding... (Esc to cancel)"
            else:
                prompt.placeholder = "Press Space or Enter for more..."
            if self.focused is prompt:
                self.set_focus(None)

    def _kick(self) -> None:
        self._last_gate = None
        self.session.changed = True

    # ---- paging / scrolling actions -----------------------------------------------------

    def _modal(self) -> bool:
        return len(self.screen_stack) > 1

    def action_advance(self) -> None:
        if self._modal():
            return
        before = self.transcript.visible_range()[0]
        if self.transcript.advance() == "advanced":
            self.view.animate_page_turn(before, self.transcript.page_start)
        self._kick()

    def action_page_down(self) -> None:
        if self._modal():
            return
        if self.transcript.scrolled_back:
            self.transcript.scroll_by(self.transcript.page_height - 1)
        else:
            self.action_advance()
            return
        self._kick()

    def action_page_up(self) -> None:
        if not self._modal():
            self.transcript.scroll_by(-(self.transcript.page_height - 1))
            self._kick()

    def action_scroll(self, delta: int) -> None:
        if not self._modal():
            self.transcript.scroll_by(delta)
            self._kick()

    def action_scroll_top(self) -> None:
        if not self._modal():
            self.transcript.scroll_to_top()
            self._kick()

    def action_scroll_live(self) -> None:
        if not self._modal():
            self.transcript.scroll_to_live()
            self._kick()

    def action_toggle_reasoning(self) -> None:
        self.transcript.set_show_reasoning(not self.transcript.show_reasoning)
        self.session.add_system(
            "Reasoning is now " + ("shown." if self.transcript.show_reasoning else "hidden.")
        )
        self._kick()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("context", "thinking") and not self.debug_server:
            return False  # not bound and not shown in the footer unless the server is in debug mode
        if action == "compendium" and not self.has_compendium:
            return False  # likewise for a server without the compendium
        if action == "status" and not self.has_status:
            return False
        return True

    def action_context(self) -> None:
        if isinstance(self.screen, ContextScreen):
            self.screen.dismiss(None)
        else:
            self.run_worker(self._context_flow(), group="flow")

    async def _context_flow(self) -> None:
        if not self.debug_server:
            self.session.add_system("The server is not in debug mode (start it with --debug).", "yellow")
            self._kick()
            return
        if self._modal():
            return
        prompt = self.query_one("#prompt", Input)
        await self.push_screen_wait(ContextScreen(self.api, lambda: decode_prompt(prompt.value), self.ascii_only))

    def action_compendium(self) -> None:
        if isinstance(self.screen, CompendiumScreen):
            self.screen.action_close()
        else:
            self.run_worker(self._compendium_flow(None), group="flow")

    async def _compendium_flow(self, where: str | None) -> None:
        """Open the compendium on a tab (`/compendium locations`) or on a name (`/compendium Wren`)."""
        s = self.session
        if not self.has_compendium:
            s.add_system("This server does not offer the compendium.", "yellow")
            self._kick()
            return
        if self._modal():
            return
        tab = where.lower() if where and where.lower() in TABS else None
        name = where if where and tab is None else None
        pending = await self.push_screen_wait(
            CompendiumScreen(self.api, self.ascii_only, s.set_unread, tab=tab, name=name)
        )
        try:
            if pending:
                s.set_unread(await self.api.compendium_seen(pending))
        except ApiError:
            pass  # the marks are only a convenience; the next opening shows them again
        self._kick()

    def action_status(self) -> None:
        if isinstance(self.screen, StatusScreen):
            self.screen.action_close()
        else:
            self.run_worker(self._status_flow(), group="flow")

    async def _status_flow(self, character: str | None = None) -> None:
        if not self.has_status:
            self.session.add_system("This server does not offer the status page.", "yellow")
            self._kick()
            return
        if self._modal():
            return
        await self.push_screen_wait(StatusScreen(self.api, self.ascii_only, character))
        self._kick()

    def action_thinking(self) -> None:
        self.run_worker(self._thinking_flow(None), group="flow")

    async def _thinking_flow(self, enabled: bool | None) -> None:
        """Switch the model's thinking (None: flip it). Held by the server until changed or restarted."""
        s = self.session
        if not self.debug_server:
            s.add_system("The server is not in debug mode (start it with --debug).", "yellow")
        else:
            try:
                self.model_thinking = await self.api.set_thinking(not self.model_thinking if enabled is None else enabled)
            except ApiError as e:
                s.add_system(e.message, "red")
            else:
                s.add_system("Model thinking is now " + ("on." if self.model_thinking else "off."))
        self._kick()

    async def _story_flow(self) -> None:
        """Print the whole story plan (debug servers only: it is all spoilers)."""
        s = self.session
        if not self.debug_server:
            s.add_system("The server is not in debug mode (start it with --debug).", "yellow")
        else:
            try:
                plan = await self.api.debug_story()
            except ApiError as e:
                s.add_system(e.message, "red")
            else:
                s.add_system(plan.get("text") or "This game has no story plan.", "yellow")
        self._kick()

    def action_cancel_turn(self) -> None:
        if self._turn is not None and self.session.busy:
            self._turn.cancel()

    # ---- chat ---------------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt":
            return
        text = decode_prompt(event.value)
        event.input.value = ""
        if not text:
            return
        cmd = parse_command(text)
        if cmd is not None:
            self.run_worker(self._run_command(cmd), group="flow")
            return
        if not self.session.can_input:
            return
        self._turn = self.run_worker(self._run_turn(text), exclusive=True, group="turn")

    async def _run_turn(self, text: str) -> None:
        s = self.session
        s.begin_turn(text)
        self._kick()
        try:
            async for event in self.api.stream_chat(text):
                s.apply(event)
        except ApiError as e:
            s.fail(e.message if e.code != "conflict" else "A turn is already in progress for this session.")
        except asyncio.CancelledError:
            s.interrupted()
            self._kick()
            raise
        finally:
            if s.busy:  # stream ended without a terminal event
                s.fail("Connection closed unexpectedly")
            self._kick()

    # ---- save / load / new flows --------------------------------------------------------

    def _require_idle(self) -> bool:
        if self.session.busy:
            self.session.add_system("Wait for the GM to finish, or press Esc to cancel the turn.", "yellow")
            self._kick()
            return False
        return True

    def action_save(self) -> None:
        self.run_worker(self._save_flow(None), group="flow")

    def action_load(self) -> None:
        self.run_worker(self._load_flow(None), group="flow")

    def action_new_game(self) -> None:
        self.run_worker(self._new_flow(), group="flow")

    async def _save_flow(self, name: str | None, overwrite: bool = False) -> bool:
        s = self.session
        if not self._require_idle():
            return False
        if name is None:
            name = await self.push_screen_wait(SaveDialog(self.api, s.game_name or suggest_name()))
            if name is None:
                return False
        try:
            info = await self.api.save(name, overwrite)
        except ApiError as e:
            if e.code == "already_exists" and not overwrite:
                if await self.push_screen_wait(
                    ConfirmDialog(f"'{name}' already exists. Overwrite?", "Overwrite")
                ):
                    return await self._save_flow(name, True)
                return False
            s.add_system(f"Save failed: {e.message}", "red")
            self._kick()
            return False
        s.mark_saved(name)
        s.add_system(f"Saved as '{name}' ({info.get('message_count', '?')} messages).")
        self._kick()
        return True

    async def _load_flow(self, name: str | None) -> None:
        s = self.session
        if not self._require_idle():
            return
        if name is None:
            name = await self.push_screen_wait(LoadDialog(self.api, s.dirty))
            if name is None:
                return
        if s.dirty and not await self.push_screen_wait(
            ConfirmDialog(f"Discard the current game and load '{name}'?", "Load anyway")
        ):
            return
        try:
            await self.api.restore(name)
            state = await self.api.chat_state()
        except ApiError as e:
            s.add_system(f"Load failed: {e.message}", "red")
            self._kick()
            return
        s.load_history(
            state["messages"], state.get("phase", ""), state.get("ruleset_name", ""), state.get("story"),
            state.get("compendium"),
        )
        s.mark_loaded(name)
        s.add_system(f"Loaded '{name}'." + (f" ({s.phase_label})" if s.phase_label else ""))
        self._kick()

    async def _new_flow(self) -> None:
        s = self.session
        if not self._require_idle():
            return
        has_game = s.dirty or any(isinstance(b, (UserBlock, MarkdownBlock)) for b in s.transcript.blocks)
        if has_game:
            choice = await self.push_screen_wait(NewGameDialog(s.dirty))
            if choice == "save":
                if not await self._save_flow(None):
                    return
            elif choice != "discard":
                return
        try:
            result = await self.api.new_game()
        except ApiError as e:
            s.add_system(f"New game failed: {e.message}", "red")
            self._kick()
            return
        s.new_game(result.get("phase", ""), result.get("ruleset_name", ""))
        s.add_system("New game started. " + intro_text(s.phase))
        self._kick()

    # ---- slash commands -----------------------------------------------------------------

    async def _run_command(self, cmd: Command) -> None:
        s = self.session
        match cmd.name:
            case "help":
                s.add_system(HELP + (DEBUG_HELP if self.debug_server else ""))
            case "context":
                await self._context_flow()
            case "compendium":
                await self._compendium_flow(" ".join(cmd.args) or None)
            case "status":
                await self._status_flow()
            case "sheet":
                await self._status_flow(" ".join(cmd.args))
            case "story":
                await self._story_flow()
            case "thinking":
                words = {"on": True, "off": False}
                if cmd.arg is not None and cmd.arg.lower() not in words:
                    s.add_system("Use /thinking on, /thinking off, or /thinking to switch.", "yellow")
                    self._kick()
                else:
                    await self._thinking_flow(None if cmd.arg is None else words[cmd.arg.lower()])
            case "quit":
                self.exit()
            case "reconnect":
                await self._startup()
            case "new":
                await self._new_flow()
            case "save":
                await self._save_flow(cmd.arg, overwrite="overwrite" in cmd.flags)
            case "load":
                await self._load_flow(cmd.arg)
            case "saves":
                await self._list_saves()
            case "info" | "delete" if not cmd.arg:
                s.add_system(f"Usage: /{cmd.name} NAME", "yellow")
            case "info":
                await self._info(cmd.arg)
            case "delete":
                await self._delete(cmd.arg)
            case _:
                s.add_system(f"Unknown command: /{cmd.arg or ''}. Type /help.", "yellow")
        self._kick()

    async def _list_saves(self) -> None:
        try:
            saves = await self.api.list_histories()
        except ApiError as e:
            self.session.add_system(e.message, "red")
            return
        if not saves:
            self.session.add_system("No saved games.")
        for h in saves:
            note = story_note(h.get("story"))
            self.session.add_system(
                f"  {h['name']}  ({h.get('message_count', '?')} messages, {h.get('saved_at', '')})"
                + (f", {note}" if note else "")
            )

    async def _info(self, name: str) -> None:
        try:
            info = await self.api.history_info(name)
        except ApiError as e:
            self.session.add_system(e.message, "red")
            return
        self.session.add_system(
            f"{info['name']}: {info.get('message_count')} messages, saved {info.get('saved_at')}, "
            f"model {info.get('model')}\n  last: {info.get('last_message_preview', '(none)')}"
            + (f"\n  {story_note(info.get('story'))}" if story_note(info.get("story")) else "")
        )

    async def _delete(self, name: str) -> None:
        if not await self.push_screen_wait(ConfirmDialog(f"Delete saved game '{name}'?", "Delete")):
            return
        try:
            await self.api.delete(name)
        except ApiError as e:
            self.session.add_system(e.message, "red")
            return
        self.session.add_system(f"Deleted '{name}'.")
