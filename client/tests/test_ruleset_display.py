"""The chosen ruleset shows in the status line (docs/RULESETS.md)."""

from aigm_client import events as ev
from aigm_client.events import MessageEnd, MessageStart, parse_event
from aigm_client.session import ChatSession
from aigm_client.transcript import Transcript
from tests.fake_server import FakeServer
from tests.test_app_pilot import make_app, send, settle, start


def status_text(app) -> str:
    return str(app.query_one("#status").render())


def test_events_carry_the_ruleset_name_when_the_server_sends_it():
    start_event = parse_event("message_start", '{"message_id": "m", "session_id": "s", "phase": "session_zero", "ruleset_name": "AD&D 1e"}')
    assert start_event == MessageStart("m", "s", "session_zero", "AD&D 1e")
    end_event = parse_event("message_end", '{"message_id": "m", "stop_reason": "end_turn", "usage": {}, "phase": "adventure", "ruleset_name": "B/X"}')
    assert isinstance(end_event, MessageEnd) and end_event.ruleset_name == "B/X"
    older = parse_event("message_end", '{"message_id": "m", "stop_reason": "end_turn", "usage": {}}')
    assert older.ruleset_name == ""


def test_session_follows_the_ruleset_and_keeps_it_when_a_server_omits_it():
    s = ChatSession(Transcript())
    s.apply(ev.MessageStart("m", "s", "session_zero", "D&D 5.5e"))
    assert s.ruleset_name == "D&D 5.5e"
    s.apply(ev.MessageEnd("m", "end_turn", {}, "session_zero", "AD&D 1e"))  # chosen during the turn
    assert s.ruleset_name == "AD&D 1e"
    s.apply(ev.MessageStart("m2", "s", "session_zero"))  # an older server says nothing
    assert s.ruleset_name == "AD&D 1e"
    s.load_history([], "adventure", "Pathfinder 2e")
    assert s.ruleset_name == "Pathfinder 2e"
    s.new_game("session_zero", "D&D 5.5e")
    assert s.ruleset_name == "D&D 5.5e"
    s.load_history([], "adventure")
    assert s.ruleset_name == ""


async def test_status_line_shows_mode_and_ruleset():
    fake = FakeServer()
    fake.phase, fake.ruleset_name = "session_zero", "AD&D 1e"
    app = make_app(fake)
    async with app.run_test(size=(110, 30)) as pilot:
        await start(app, pilot)
        await settle(pilot, lambda: "AD&D 1e" in status_text(app))
        assert "mode: Session 0 · AD&D 1e" in status_text(app)


async def test_status_line_without_a_ruleset_is_unchanged():
    fake = FakeServer()
    fake.phase = "adventure"
    app = make_app(fake)
    async with app.run_test(size=(110, 30)) as pilot:
        await start(app, pilot)
        await settle(pilot, lambda: "mode: Adventure" in status_text(app))
        assert "·" not in status_text(app).split("game:")[0]


async def test_a_ruleset_chosen_in_a_turn_appears_when_the_turn_ends():
    fake = FakeServer(
        [
            ("message_start", {"message_id": "m", "session_id": "default", "phase": "session_zero", "ruleset_name": "D&D 5.5e"}),
            ("text", {"delta": "Done."}),
            ("message_end", {"message_id": "m", "stop_reason": "end_turn", "usage": {}, "phase": "session_zero", "ruleset_name": "B/X"}),
        ]
    )
    fake.phase, fake.ruleset_name = "session_zero", "D&D 5.5e"
    app = make_app(fake)
    async with app.run_test(size=(110, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "let us play B/X")
        await settle(pilot, lambda: "Session 0 · B/X" in status_text(app))
