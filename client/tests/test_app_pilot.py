import asyncio

from textual.widgets import Input

from aigm_client.api import ApiClient
from aigm_client.app import AigmApp
from aigm_client.blocks import plain
from tests.fake_server import FakeServer

LONG = [
    ("message_start", {"message_id": "m", "session_id": "default"}),
    ("text", {"delta": "\n\n".join(f"Paragraph {i} of the tale." for i in range(12))}),
    ("message_end", {"message_id": "m", "stop_reason": "end_turn", "usage": {}}),
]


def make_app(fake):
    return AigmApp(ApiClient(transport=fake.transport()))


async def settle(pilot, cond, timeout=3.0):
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        await pilot.pause(0.05)
        if cond():
            return
    raise AssertionError("condition not reached")


def screen_text(app):
    return "\n".join(plain(app.transcript.visible_lines()))


async def start(app, pilot):
    await settle(pilot, lambda: app.connected is not None and app.session.can_input)
    await settle(pilot, lambda: not app.query_one("#prompt", Input).disabled)


async def send(app, pilot, text):
    await pilot.click("#prompt")
    for ch in text:
        await pilot.press(ch if ch != " " else "space")
    await pilot.press("enter")


async def test_startup_and_basic_turn():
    fake = FakeServer()
    app = make_app(fake)
    async with app.run_test(size=(80, 24)) as pilot:
        await start(app, pilot)
        assert "Welcome" in screen_text(app)
        await send(app, pilot, "I attack")
        await settle(pilot, lambda: "You swing." in screen_text(app) and not app.session.busy)
        text = screen_text(app)
        assert "You: I attack" in text
        assert app.session.dirty
        assert not app.query_one("#prompt", Input).disabled


async def test_paging_holds_text_and_space_advances():
    fake = FakeServer(LONG)
    app = make_app(fake)
    async with app.run_test(size=(60, 12)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "tell me a tale")
        await settle(pilot, lambda: app.session.dirty and not app.session.busy)
        t = app.transcript
        assert t.held > 0  # stream finished and was fully buffered, but the page is full
        assert app.query_one("#prompt", Input).disabled
        assert "MORE" in str(app.query_one("#pager").render())
        assert "Paragraph 11" not in screen_text(app)
        guard = 0
        while t.held > 0 and guard < 20:
            await pilot.press("space")
            await pilot.pause(0.1)
            guard += 1
        await settle(pilot, lambda: t.view_top_override is None)  # page-turn animation finished
        assert "Paragraph 11" in screen_text(app)
        await settle(pilot, lambda: not app.query_one("#prompt", Input).disabled)


async def test_scrollback_and_return():
    fake = FakeServer(LONG)
    app = make_app(fake)
    async with app.run_test(size=(60, 12)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "tale")
        await settle(pilot, lambda: app.session.dirty and not app.session.busy)
        while app.transcript.held > 0:
            await pilot.press("enter")
            await pilot.pause(0.1)
        await settle(pilot, lambda: app.transcript.view_top_override is None)
        await pilot.press("pageup")
        await pilot.pause(0.1)
        assert app.transcript.scrolled_back
        assert "scrolled back" in str(app.query_one("#pager").render())
        await pilot.press("end")
        await pilot.pause(0.1)
        assert not app.transcript.scrolled_back


async def test_save_dialog_and_overwrite_confirm():
    fake = FakeServer()
    app = make_app(fake)
    async with app.run_test(size=(100, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "hello")
        await settle(pilot, lambda: app.session.dirty and not app.session.busy)
        await pilot.press("ctrl+s")
        await settle(pilot, lambda: len(app.screen_stack) > 1)
        await pilot.press(*"ctrl+a".split("+")[:0])  # no-op; field is prefilled
        await pilot.press("enter")
        await settle(pilot, lambda: len(app.screen_stack) == 1 and fake.saves)
        name = next(iter(fake.saves))
        assert app.session.game_name == name and not app.session.dirty
        # saving again under the same name asks to overwrite
        await pilot.press("ctrl+s")
        await settle(pilot, lambda: len(app.screen_stack) > 1)
        await pilot.press("enter")
        await settle(pilot, lambda: len(app.screen_stack) > 1 and app.screen.query("#yes"))
        await pilot.click("#yes")
        await settle(pilot, lambda: len(app.screen_stack) == 1)
        assert any(c[0] == "PUT" and c[2].get("overwrite") == "true" for c in fake.calls)


async def test_new_game_discard():
    fake = FakeServer()
    app = make_app(fake)
    async with app.run_test(size=(100, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "hello")
        await settle(pilot, lambda: app.session.dirty and not app.session.busy)
        await pilot.press("ctrl+n")
        await settle(pilot, lambda: len(app.screen_stack) > 1)
        await pilot.click("#discard")
        await settle(pilot, lambda: len(app.screen_stack) == 1 and not app.session.dirty)
        assert fake.messages == []
        assert "You: hello" not in screen_text(app)
        assert "New game started" in screen_text(app)


async def test_load_via_dialog_rebuilds_transcript():
    fake = FakeServer()
    fake.saves["old-game"] = [
        {"role": "user", "content": [{"type": "text", "text": "I open the door"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "It creaks open."}]},
    ]
    app = make_app(fake)
    async with app.run_test(size=(100, 30)) as pilot:
        await start(app, pilot)
        await pilot.press("ctrl+o")
        await settle(pilot, lambda: len(app.screen_stack) > 1)
        await settle(pilot, lambda: app.screen.query("#load") and not app.screen.query_one("#load").disabled)
        await pilot.click("#load")
        await settle(pilot, lambda: len(app.screen_stack) == 1 and app.session.game_name == "old-game")
        text = screen_text(app)
        assert "You: I open the door" in text and "It creaks open." in text


async def test_shortcuts_blocked_while_turn_in_flight():
    fake = FakeServer()
    app = make_app(fake)
    async with app.run_test(size=(100, 30)) as pilot:
        await start(app, pilot)
        app.session.busy = True  # simulate a streaming turn
        await pilot.press("ctrl+s")
        await pilot.pause(0.3)
        assert len(app.screen_stack) == 1
        assert "Wait for the GM" in "\n".join(plain(app.transcript.lines))


async def test_offline_server_message():
    import httpx

    def boom(req):
        raise httpx.ConnectError("refused")

    app = AigmApp(ApiClient(transport=httpx.MockTransport(boom)))
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot, lambda: app.connected is False)
        assert "Cannot reach server" in "\n".join(plain(app.transcript.lines))


async def test_page_turn_animates_and_keeps_overlap():
    fake = FakeServer(LONG)
    app = make_app(fake)
    async with app.run_test(size=(60, 12)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "tale")
        await settle(pilot, lambda: app.session.dirty and not app.session.busy)
        t = app.transcript
        before = plain(t.visible_lines())
        old_start = t.page_start
        await pilot.press("space")
        assert t.page_start > old_start
        assert t.view_top_override is not None or t.visible_range()[0] == t.page_start  # sliding or done
        await settle(pilot, lambda: t.view_top_override is None)
        after = plain(t.visible_lines())
        assert after[:3] == before[-3:]  # last three lines of the old page lead the new page
