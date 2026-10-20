"""The debug-only switch for the model's thinking (docs/API.md PUT /debug/thinking)."""

import pytest
from textual.widgets import Static

from aigm_client.api import ApiClient, ApiError
from aigm_client.commands import parse_command
from tests.fake_server import FakeServer
from tests.test_app_pilot import make_app, screen_text, send, settle, start


def status_text(app) -> str:
    return str(app.query_one("#status", Static).render())


def puts(fake):
    return [c for c in fake.calls if c[1] == "/debug/thinking"]


async def test_api_sends_the_flag_and_a_plain_server_answers_404():
    fake = FakeServer()
    fake.debug = True
    api = ApiClient(session_id="s1", transport=fake.transport())
    assert await api.set_thinking(False) is False
    assert puts(fake)[0][2] == {"enabled": False}
    fake.debug = False
    with pytest.raises(ApiError) as err:
        await api.set_thinking(True)
    assert err.value.status == 404
    await api.aclose()


def test_thinking_is_a_known_command():
    assert parse_command("/thinking off").name == "thinking"
    assert parse_command("/thinking off").arg == "off"


async def test_f6_flips_it_and_the_status_line_says_so():
    fake = FakeServer()
    fake.debug = True
    app = make_app(fake)
    async with app.run_test(size=(100, 30)) as pilot:
        await start(app, pilot)
        assert app.model_thinking is True
        await pilot.press("f6")
        await settle(pilot, lambda: fake.thinking is False)
        await settle(pilot, lambda: "no thinking" in status_text(app))
        await pilot.press("f6")
        await settle(pilot, lambda: fake.thinking is True and "no thinking" not in status_text(app))


async def test_the_command_takes_on_and_off_and_refuses_anything_else():
    fake = FakeServer()
    fake.debug = True
    app = make_app(fake)
    async with app.run_test(size=(100, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "/thinking off")
        await settle(pilot, lambda: fake.thinking is False)
        await send(app, pilot, "/thinking off")  # setting, not flipping
        await settle(pilot, lambda: len(puts(fake)) == 2)
        assert fake.thinking is False
        await send(app, pilot, "/thinking maybe")
        await settle(pilot, lambda: "/thinking on" in screen_text(app))
        assert len(puts(fake)) == 2
        await send(app, pilot, "/thinking on")
        await settle(pilot, lambda: fake.thinking is True)


async def test_a_server_without_debug_is_told_so_and_not_called():
    fake = FakeServer()
    fake.debug = False
    app = make_app(fake)
    async with app.run_test(size=(100, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "/thinking off")
        await settle(pilot, lambda: "not in debug mode" in screen_text(app))
        assert puts(fake) == []
