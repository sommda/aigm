from textual.widgets import Static

from aigm_client import events as ev
from aigm_client.events import MessageEnd, MessageStart, PhaseChange, parse_event
from aigm_client.blocks import plain
from aigm_client.session import ChatSession
from aigm_client.transcript import Transcript
from tests.fake_server import FakeServer
from tests.test_app_pilot import make_app, screen_text, send, settle, start


def test_parse_phase_fields():
    assert parse_event("message_start", '{"message_id":"m","session_id":"s","phase":"session_zero"}') == MessageStart(
        "m", "s", "session_zero"
    )
    assert parse_event("message_end", '{"message_id":"m","stop_reason":"end_turn","usage":{},"phase":"adventure"}') == MessageEnd(
        "m", "end_turn", {}, "adventure"
    )
    assert parse_event("phase_change", '{"previous":"session_zero","phase":"adventure"}') == PhaseChange(
        "session_zero", "adventure"
    )
    assert parse_event("message_start", '{"message_id":"m"}').phase == ""  # older servers


def make_session():
    return ChatSession(Transcript())


def test_session_tracks_phase_and_announces_the_switch():
    s = make_session()
    s.load_history([], "session_zero")
    assert s.phase_label == "Session 0"
    s.begin_turn("yes")
    s.apply(ev.Text("Off we go."))
    s.apply(ev.PhaseChange("session_zero", "adventure"))
    s.apply(ev.MessageEnd("m", "end_turn", {}, "adventure"))
    assert s.phase == "adventure" and s.phase_label == "Adventure"
    assert "Session 0 is over" in "\n".join(plain(s.transcript.visible_lines()))


def test_new_game_is_session_zero_and_unknown_phase_has_no_label():
    s = make_session()
    s.load_history([], "adventure")
    s.new_game()
    assert s.phase == "session_zero"
    s.load_history([], "")
    assert s.phase_label == ""


async def test_pilot_shows_phase_and_the_switch():
    fake = FakeServer(
        [
            ("message_start", {"message_id": "m", "session_id": "default", "phase": "session_zero"}),
            ("text", {"delta": "Here we go. "}),
            ("phase_change", {"previous": "session_zero", "phase": "adventure"}),
            ("message_end", {"message_id": "m", "stop_reason": "end_turn", "usage": {}, "phase": "adventure"}),
        ]
    )
    fake.phase = "session_zero"
    app = make_app(fake)
    async with app.run_test(size=(100, 24)) as pilot:
        await start(app, pilot)
        status = lambda: str(app.query_one("#status", Static).render())
        assert "Session 0" in screen_text(app) and "mode: Session 0" in status()
        await send(app, pilot, "yes")
        await settle(pilot, lambda: app.session.phase == "adventure" and not app.session.busy)
        assert "The adventure begins" in screen_text(app)
        await settle(pilot, lambda: "mode: Adventure" in status())


def test_server_inserted_notes_show_as_system_lines_not_player_text():
    from aigm_client.blocks import SystemBlock, UserBlock, history_to_blocks

    blocks = history_to_blocks(
        [
            {"role": "user", "content": [{"type": "text", "text": "[System: Session 0 is complete. Record follows.]"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "## Campaign record"}]},
            {"role": "user", "content": [{"type": "text", "text": "I look around"}]},
        ]
    )
    assert isinstance(blocks[0], SystemBlock) and "Session 0 is complete" in blocks[0].text
    assert isinstance(blocks[2], UserBlock)


def test_paste_encoding_roundtrips_line_breaks():
    from aigm_client.widgets import decode_prompt, encode_paste

    shown = encode_paste("first line\r\nsecond line\n\nfourth\n")
    assert "\n" not in shown and shown.count("⏎") == 3
    assert decode_prompt(shown) == "first line\nsecond line\n\nfourth"
    assert decode_prompt("  plain  ") == "plain"


async def test_pilot_multiline_paste_is_sent_whole():
    from textual import events

    fake = FakeServer()
    app = make_app(fake)
    async with app.run_test(size=(100, 24)) as pilot:
        await start(app, pilot)
        prompt = app.query_one("#prompt")
        prompt.focus()
        prompt.post_message(events.Paste("line one\nline two\nline three"))
        await pilot.pause(0.1)
        assert "line three" in prompt.value
        await pilot.press("enter")
        await settle(pilot, lambda: fake.messages and not app.session.busy)
        assert fake.messages[0]["content"][0]["text"] == "line one\nline two\nline three"


# ---- status events (preparing the world) --------------------------------------------------


def test_parse_status_event():
    assert parse_event("status", '{"stage":"world","message":"Preparing the world...","done":false}') == ev.Status(
        "world", "Preparing the world...", False
    )
    assert parse_event("status", '{"stage":"world","message":"The world is ready.","done":true}').done is True
    assert parse_event("status", "{}") == ev.Status("", "", False)


def test_status_shows_until_done_and_is_cleared_when_the_turn_ends_or_fails():
    s = make_session()
    s.begin_turn("yes")
    s.apply(ev.Status("world", "Preparing the world..."))
    assert s.status == "Preparing the world..."
    s.apply(ev.Status("world", "Detailing the Rusty Flagon..."))
    assert s.status == "Detailing the Rusty Flagon..."
    s.apply(ev.Status("world", "The world is ready.", True))
    assert s.status == ""
    for finish in (ev.MessageEnd("m", "end_turn", {}, "adventure"), ev.ErrorEvent("upstream_error", "boom", True)):
        s.begin_turn("again")
        s.apply(ev.Status("world", "Preparing the world..."))
        s.apply(finish)
        assert s.status == "" and not s.busy
    s.begin_turn("third")
    s.apply(ev.Status("world", "Preparing the world..."))
    s.interrupted()
    assert s.status == ""
    s.apply(ev.Status("world", "Preparing the world..."))
    s.new_game()
    assert s.status == ""


def test_status_does_not_add_transcript_lines():
    s = make_session()
    s.begin_turn("yes")
    before = len(plain(s.transcript.visible_lines()))
    s.apply(ev.Status("world", "Preparing the world..."))
    s.apply(ev.Status("world", "The world is ready.", True))
    assert len(plain(s.transcript.visible_lines())) == before


async def test_pilot_status_line_shows_the_server_message_in_place_of_writing():
    app = make_app(FakeServer([("message_start", {"message_id": "m", "session_id": "default"}),
                               ("message_end", {"message_id": "m", "stop_reason": "end_turn", "usage": {}})]))
    async with app.run_test(size=(100, 24)) as pilot:
        await start(app, pilot)
        status = lambda: str(app.query_one("#status", Static).render())
        app.session.busy = True
        app.session.apply(ev.Status("world", "Preparing the world..."))
        app._update_status()
        assert "Preparing the world..." in status() and "GM is writing" not in status()
        app.session.apply(ev.Status("world", "The world is ready.", True))
        app._update_status()
        assert "Preparing the world" not in status() and "GM is writing" in status()
