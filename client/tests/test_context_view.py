"""The context viewer in the app: only offered by debug servers (docs/CONTEXT.md)."""

import httpx
import pytest
from textual.widgets import Input

from aigm_client.api import ApiClient, ApiError
from aigm_client.commands import parse_command
from aigm_client.context_screen import ContextScreen, ContextView
from tests.fake_server import FakeServer
from tests.test_app_pilot import make_app, screen_text, send, settle, start


def view_text(app) -> str:
    view = app.screen.query_one(ContextView)
    return "\n".join("".join(seg.text for seg in strip) for strip in view._strips)


def context_calls(fake):
    return [c for c in fake.calls if c[1] == "/debug/context"]


def enabled_actions(app) -> set[str]:
    """The actions the footer would offer."""
    return {ab.binding.action for ab in app.active_bindings.values() if ab.enabled}


async def type_text(pilot, text):
    await pilot.click("#prompt")
    for ch in text:
        await pilot.press(ch if ch != " " else "space")


async def open_view(app, pilot):
    await pilot.press("ctrl+k")
    await settle(pilot, lambda: isinstance(app.screen, ContextScreen) and "System prompt" in view_text(app))


# ---- the api and the command -----------------------------------------------------------------------------


async def test_api_context_sends_session_and_draft():
    fake = FakeServer()
    fake.debug = True
    api = ApiClient(session_id="s1", transport=fake.transport())
    data = await api.context("I open the door")
    assert data["phase"] == "adventure"
    assert context_calls(fake)[0][2] == {"session_id": "s1", "draft": "I open the door"}
    fake.debug = False
    with pytest.raises(ApiError) as err:
        await api.context()
    assert err.value.status == 404
    await api.aclose()


def test_context_is_a_known_command():
    assert parse_command("/context").name == "context"


# ---- servers that are not in debug mode -----------------------------------------------------------


@pytest.mark.parametrize("debug", [False, None])
async def test_not_offered_without_debug(debug):
    fake = FakeServer()
    fake.debug = debug
    app = make_app(fake)
    async with app.run_test(size=(100, 30)) as pilot:
        await start(app, pilot)
        assert app.debug_server is False
        await pilot.press("ctrl+k")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, ContextScreen) and not context_calls(fake)
        await send(app, pilot, "/context")
        await settle(pilot, lambda: "not in debug mode" in screen_text(app))
        assert not context_calls(fake)
        assert "context" not in enabled_actions(app)
        assert "DEBUG" not in str(app.query_one("#status").render())
        await send(app, pilot, "/help")
        await settle(pilot, lambda: "Commands:" in screen_text(app))
        assert "/context" not in screen_text(app)


async def test_ctrl_k_still_edits_the_prompt_without_debug():
    fake = FakeServer()
    app = make_app(fake)
    async with app.run_test(size=(100, 30)) as pilot:
        await start(app, pilot)
        await type_text(pilot, "hello world")
        for _ in range(5):
            await pilot.press("left")
        await pilot.press("ctrl+k")  # the Input's own "delete to end of line"
        assert app.query_one("#prompt", Input).value == "hello "


# ---- debug servers --------------------------------------------------------------------------------


async def test_debug_server_offers_the_view_with_ctrl_k():
    fake = FakeServer()
    fake.debug = True
    app = make_app(fake)
    async with app.run_test(size=(110, 40)) as pilot:
        await start(app, pilot)
        assert app.debug_server is True and "DEBUG" in str(app.query_one("#status").render())
        assert "context" in enabled_actions(app)
        await open_view(app, pilot)
        text = view_text(app)
        assert "System prompt" in text and "History (3 messages)" in text
        assert "«your next message goes here»" in text and "prompt-cache breakpoint" in text
        assert "You are the game master." not in text and "It is cold." not in text  # collapsed by default
        head = str(app.screen.query_one("#ctx-head").render())
        assert "adventure" in head and "turn 2" in head and "~321" in head
        await pilot.press("escape")
        await settle(pilot, lambda: not isinstance(app.screen, ContextScreen))


async def test_keys_open_close_and_reset():
    fake = FakeServer()
    fake.debug = True
    app = make_app(fake)
    async with app.run_test(size=(110, 40)) as pilot:
        await start(app, pilot)
        await open_view(app, pilot)
        await pilot.press("down", "enter")  # the first prompt file
        await settle(pilot, lambda: "You are the game master." in view_text(app))
        await pilot.press("enter")
        await settle(pilot, lambda: "You are the game master." not in view_text(app))
        await pilot.press("e")
        await settle(pilot, lambda: "Needs a check." in view_text(app) and "Time: day 1" in view_text(app))
        await pilot.press("c")
        await settle(pilot, lambda: "Needs a check." not in view_text(app) and "Time: day 1" not in view_text(app))
        await pilot.press("ctrl+k")  # the same key closes it
        await settle(pilot, lambda: not isinstance(app.screen, ContextScreen))


async def test_the_text_typed_so_far_is_sent_and_refresh_resends_it():
    fake = FakeServer()
    fake.debug = True
    app = make_app(fake)
    async with app.run_test(size=(110, 40)) as pilot:
        await start(app, pilot)
        await type_text(pilot, "we ride to Karth")
        await open_view(app, pilot)
        assert context_calls(fake)[-1][2]["draft"] == "we ride to Karth"
        await pilot.press("down", "down", "down", "enter")  # open something, then refresh keeps it open
        await pilot.press("r")
        await settle(pilot, lambda: len(context_calls(fake)) == 2)
        assert context_calls(fake)[-1][2]["draft"] == "we ride to Karth"
        await pilot.press("escape")
        await settle(pilot, lambda: not isinstance(app.screen, ContextScreen))
        assert app.query_one("#prompt", Input).value == "we ride to Karth"  # the draft is untouched


async def test_refresh_keeps_what_was_opened():
    fake = FakeServer()
    fake.debug = True
    app = make_app(fake)
    async with app.run_test(size=(110, 40)) as pilot:
        await start(app, pilot)
        await open_view(app, pilot)
        await pilot.press("down", "enter")
        await settle(pilot, lambda: "You are the game master." in view_text(app))
        await pilot.press("r")
        await settle(pilot, lambda: len(context_calls(fake)) == 2)
        await pilot.pause(0.1)
        assert "You are the game master." in view_text(app)


async def test_context_command_and_help_on_a_debug_server():
    fake = FakeServer()
    fake.debug = True
    app = make_app(fake)
    async with app.run_test(size=(110, 40)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "/help")
        await settle(pilot, lambda: "/context" in screen_text(app))
        await send(app, pilot, "/context")
        await settle(pilot, lambda: isinstance(app.screen, ContextScreen) and "System prompt" in view_text(app))


async def test_works_while_the_gm_is_writing():
    fake = FakeServer()
    fake.debug = True
    app = make_app(fake)
    async with app.run_test(size=(110, 40)) as pilot:
        await start(app, pilot)
        app.session.busy = True
        await pilot.press("ctrl+k")
        await settle(pilot, lambda: isinstance(app.screen, ContextScreen) and "System prompt" in view_text(app))
        app.session.busy = False


async def test_a_server_that_answers_404_gets_a_clear_message():
    fake = FakeServer()
    fake.debug = True
    app = make_app(fake)
    async with app.run_test(size=(110, 40)) as pilot:
        await start(app, pilot)
        fake.debug = False  # restarted without --debug since the client connected
        await pilot.press("ctrl+k")
        await settle(pilot, lambda: isinstance(app.screen, ContextScreen) and "--debug" in view_text(app))
        await pilot.press("q")
        await settle(pilot, lambda: not isinstance(app.screen, ContextScreen))


async def test_connection_failure_is_reported_in_the_view():
    fake = FakeServer()
    fake.debug = True
    app = make_app(fake)
    async with app.run_test(size=(110, 40)) as pilot:
        await start(app, pilot)
        app.api._http = httpx.AsyncClient(
            base_url="http://x", transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("no")))
        )
        await pilot.press("ctrl+k")
        await settle(pilot, lambda: isinstance(app.screen, ContextScreen) and "Could not load" in view_text(app))


async def test_ascii_mode_has_no_special_glyphs():
    fake = FakeServer()
    fake.debug = True
    from aigm_client.app import AigmApp

    app = AigmApp(ApiClient(transport=fake.transport()), ascii_only=True)
    async with app.run_test(size=(110, 40)) as pilot:
        await start(app, pilot)
        await open_view(app, pilot)
        text = view_text(app)
        assert "▌" not in text and "▸" not in text and "▾" not in text and "|" in text
