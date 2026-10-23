"""The compendium on screen, against the fake server."""

import pytest

from aigm_client import compendium_screen
from aigm_client.app import AigmApp
from aigm_client.compendium_screen import CompendiumScreen, LinesView
from tests.fake_server import FakeServer, sample_compendium
from tests.test_app_pilot import make_app, send, settle, start


@pytest.fixture(autouse=True)
def quick_reading(monkeypatch):
    monkeypatch.setattr(compendium_screen, "DWELL", 0.05)
    monkeypatch.setattr(compendium_screen, "FLUSH", 0.1)


def fake_with_compendium() -> FakeServer:
    fake = FakeServer()
    fake.compendium = sample_compendium()
    return fake


def pane_text(screen, pane) -> str:
    view = screen.query_one(pane, LinesView)
    return "\n".join("".join(seg.text for seg in strip) for strip in view._strips)


async def open_screen(app, pilot) -> CompendiumScreen:
    await pilot.press("ctrl+g")
    await settle(pilot, lambda: isinstance(app.screen, CompendiumScreen))
    screen = app.screen
    await settle(pilot, lambda: "Harrow Mine" in pane_text(screen, "#cp-list"))
    return screen


async def test_ctrl_g_opens_the_screen_with_the_tabs_lists_and_detail():
    fake = fake_with_compendium()
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        screen = await open_screen(app, pilot)
        listing = pane_text(screen, "#cp-list")
        assert "Ashby Vale" in listing and "Thornwood" in listing and "new" in listing
        await settle(pilot, lambda: "Ashby Vale" in pane_text(screen, "#cp-detail"))
        assert "farming valley" in pane_text(screen, "#cp-detail")
        await pilot.press("2")
        await settle(pilot, lambda: "Wren runs the Rusty Flagon." in pane_text(screen, "#cp-detail"))
        await pilot.press("escape")
        await settle(pilot, lambda: not isinstance(app.screen, CompendiumScreen))


async def test_looking_at_an_entry_marks_it_read_and_the_indicator_follows():
    fake = fake_with_compendium()
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await settle(pilot, lambda: app.session.compendium_unread == 3)  # from /chat/history
        screen = await open_screen(app, pilot)
        await pilot.press("down", "down")  # onto Harrow Mine, new
        await settle(pilot, lambda: "e007" in fake.seen)
        await settle(pilot, lambda: app.session.compendium_unread < 3)
        assert "e020" not in fake.seen  # only what was dwelt on
        assert "new" in pane_text(screen, "#cp-list")  # the mark stays while the screen is open
        await pilot.press("escape")
        await settle(pilot, lambda: not isinstance(app.screen, CompendiumScreen))


async def test_closing_sends_marks_not_yet_sent():
    fake = fake_with_compendium()
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        screen = await open_screen(app, pilot)
        await pilot.press("3")  # the Thorn Guild, new
        await settle(pilot, lambda: "e020" in screen.model.read)
        screen.model.pending = ["e020"]
        screen._flush_later = lambda: None  # the timer must not get there first
        await pilot.press("escape")
        await settle(pilot, lambda: "e020" in fake.seen)


async def test_a_marks_everything_read():
    fake = fake_with_compendium()
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await open_screen(app, pilot)
        await pilot.press("a")
        await settle(pilot, lambda: {"e003", "e007", "e020"} <= fake.seen)
        await settle(pilot, lambda: app.session.compendium_unread == 0)


async def test_n_jumps_to_the_next_unread_entry():
    fake = fake_with_compendium()
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        screen = await open_screen(app, pilot)
        await pilot.press("n")
        assert screen.model.current_id == "e003"


async def test_links_jump_and_backspace_returns():
    fake = fake_with_compendium()
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        screen = await open_screen(app, pilot)
        await pilot.press("down", "down")
        await settle(pilot, lambda: "Thorn Guild" in pane_text(screen, "#cp-detail"))
        await pilot.press("tab", "down", "enter")  # Inside Thornwood, then the guild
        await settle(pilot, lambda: screen.model.current_id == "e020")
        await settle(pilot, lambda: "controls the toll road" in pane_text(screen, "#cp-detail"))
        await pilot.press("backspace")
        await settle(pilot, lambda: screen.model.current_id == "e007")


async def test_the_filter_asks_the_server():
    fake = fake_with_compendium()
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        screen = await open_screen(app, pilot)
        await pilot.press("slash")
        for ch in "harrow":
            await pilot.press(ch)
        await pilot.press("enter")
        await settle(pilot, lambda: "Thornwood" not in pane_text(screen, "#cp-list"))
        assert any(c[1] == "/compendium/locations" and c[2].get("q") == "harrow" for c in fake.calls)
        await pilot.press("escape")  # clears the filter first
        await settle(pilot, lambda: "Thornwood" in pane_text(screen, "#cp-list"))
        assert isinstance(app.screen, CompendiumScreen)


async def test_the_command_opens_a_tab_or_an_entry():
    fake = fake_with_compendium()
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "/compendium characters")
        await settle(pilot, lambda: isinstance(app.screen, CompendiumScreen))
        screen = app.screen
        await settle(pilot, lambda: screen.model.tab == "characters" and "Wren" in pane_text(screen, "#cp-list"))
        await pilot.press("escape")
        await settle(pilot, lambda: not isinstance(app.screen, CompendiumScreen))
        await send(app, pilot, "/journal thorn guild")
        await settle(pilot, lambda: isinstance(app.screen, CompendiumScreen))
        screen = app.screen
        await settle(pilot, lambda: screen.model.current_id == "e020")


async def test_a_narrow_terminal_shows_the_list_then_the_detail():
    fake = fake_with_compendium()
    app = make_app(fake)
    async with app.run_test(size=(70, 24)) as pilot:
        await start(app, pilot)
        screen = await open_screen(app, pilot)
        assert screen.query_one("#cp-detail").display is False
        await pilot.press("enter")
        await settle(pilot, lambda: screen.query_one("#cp-detail").display and not screen.query_one("#cp-list").display)
        await pilot.press("escape")
        await settle(pilot, lambda: screen.query_one("#cp-list").display)
        assert isinstance(app.screen, CompendiumScreen)


async def test_the_status_line_shows_the_unread_count():
    fake = fake_with_compendium()
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await settle(pilot, lambda: "✦ 3 new" in str(app.query_one("#status").render()))


async def test_an_old_server_has_no_compendium():
    fake = FakeServer()
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await pilot.press("ctrl+g")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, CompendiumScreen)
        await send(app, pilot, "/compendium")
        await settle(pilot, lambda: any("does not offer the compendium" in b.text for b in app.transcript.blocks if hasattr(b, "text")))


async def test_a_failing_server_shows_an_error_and_retries():
    fake = fake_with_compendium()
    fake.compendium_down = True
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await pilot.press("ctrl+g")
        await settle(pilot, lambda: isinstance(app.screen, CompendiumScreen))
        screen = app.screen
        await settle(pilot, lambda: "Could not load the compendium" in pane_text(screen, "#cp-list"))
        fake.compendium_down = False
        await pilot.press("r")
        await settle(pilot, lambda: "Harrow Mine" in pane_text(screen, "#cp-list"))
