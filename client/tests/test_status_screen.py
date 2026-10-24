"""The status screen, against the fake server."""

from textual.widgets import Static

from aigm_client.app import AigmApp
from aigm_client.compendium_screen import LinesView
from aigm_client.status_screen import StatusScreen
from tests.fake_server import FakeServer, sample_characters, sample_status
from tests.test_app_pilot import make_app, screen_text, send, settle, start


def fake_with_status() -> FakeServer:
    fake = FakeServer()
    fake.status_page = sample_status()
    fake.characters = sample_characters()
    return fake


def body_text(screen) -> str:
    view = screen.query_one("#st-body", LinesView)
    return "\n".join("".join(seg.text for seg in strip) for strip in view._strips)


async def test_f7_opens_the_page_and_escape_closes_it():
    fake = fake_with_status()
    app = make_app(fake)
    async with app.run_test(size=(100, 40)) as pilot:
        await start(app, pilot)
        await pilot.press("f7")
        await settle(pilot, lambda: isinstance(app.screen, StatusScreen))
        screen = app.screen
        await settle(pilot, lambda: "Gulls wheel" in body_text(screen))
        assert "Elian" in body_text(screen) and "Customs House" in body_text(screen)
        await pilot.press("escape")
        await settle(pilot, lambda: not isinstance(app.screen, StatusScreen))
        assert ("GET", "/status", {"session_id": "default"}) in fake.calls


async def test_the_slash_command_and_its_alias_open_it_and_r_asks_again():
    fake = fake_with_status()
    app = make_app(fake)
    async with app.run_test(size=(100, 40)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "/s")
        await settle(pilot, lambda: isinstance(app.screen, StatusScreen))
        await settle(pilot, lambda: "Gulls wheel" in body_text(app.screen))
        before = sum(1 for c in fake.calls if c[1] == "/status")
        fake.status_page["location"]["overview"] = "The tide has turned."
        await pilot.press("r")
        await settle(pilot, lambda: "The tide has turned." in body_text(app.screen))
        assert sum(1 for c in fake.calls if c[1] == "/status") == before + 1


async def test_a_server_without_the_page_says_so():
    fake = FakeServer()
    app = make_app(fake)
    async with app.run_test(size=(100, 40)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "/status")
        await settle(pilot, lambda: "does not offer the status page" in screen_text(app))
        assert not isinstance(app.screen, StatusScreen)


async def test_the_party_has_tabs_and_digits_and_arrows_switch_between_them():
    fake = fake_with_status()
    app = make_app(fake)
    async with app.run_test(size=(100, 40)) as pilot:
        await start(app, pilot)
        await pilot.press("f7")
        await settle(pilot, lambda: isinstance(app.screen, StatusScreen))
        screen = app.screen
        await settle(pilot, lambda: "Gulls wheel" in body_text(screen))
        assert "Toby" in screen.query_one("#st-tabs", Static).render().plain
        await pilot.press("2")
        await settle(pilot, lambda: "HP 11/15" in body_text(screen))
        assert "Shortsword" in body_text(screen) and ("GET", "/characters/Toby", {"session_id": "default"}) in fake.calls
        await pilot.press("right")
        await settle(pilot, lambda: "Dwarf Fighter with an axe." in body_text(screen))
        await pilot.press("1")
        await settle(pilot, lambda: "Gulls wheel" in body_text(screen))


async def test_sheet_opens_on_a_character_by_name_or_on_the_first():
    fake = fake_with_status()
    app = make_app(fake)
    async with app.run_test(size=(100, 40)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "/sheet gal")
        await settle(pilot, lambda: isinstance(app.screen, StatusScreen))
        await settle(pilot, lambda: "Dwarf Fighter with an axe." in body_text(app.screen))
        await pilot.press("escape")
        await settle(pilot, lambda: not isinstance(app.screen, StatusScreen))
        await send(app, pilot, "/sheet")
        await settle(pilot, lambda: isinstance(app.screen, StatusScreen))
        await settle(pilot, lambda: "HP 11/15" in body_text(app.screen))


async def test_the_arrows_keep_working_on_a_page_taller_than_the_screen():
    fake = fake_with_status()
    app = make_app(fake)
    async with app.run_test(size=(100, 8)) as pilot:
        await start(app, pilot)
        await pilot.press("f7")
        await settle(pilot, lambda: isinstance(app.screen, StatusScreen))
        screen = app.screen
        await settle(pilot, lambda: "Gulls wheel" in body_text(screen))
        await pilot.press("right")
        await settle(pilot, lambda: "HP 11/15" in body_text(screen))
        await pilot.press("right")
        await settle(pilot, lambda: "Dwarf Fighter with an axe." in body_text(screen))
        await pilot.press("left")
        await settle(pilot, lambda: "HP 11/15" in body_text(screen))
        await pilot.press("left")
        await settle(pilot, lambda: "Gulls wheel" in body_text(screen))
