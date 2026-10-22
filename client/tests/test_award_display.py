"""How the client shows experience and levels (docs/PROGRESSION.md)."""

from aigm_client import events as ev
from aigm_client.blocks import award_text, history_to_blocks
from tests.fake_server import FakeServer
from tests.test_app_pilot import make_app, screen_text, send, settle, start


def test_the_award_event_is_parsed():
    data = '{"xp_gained": 120, "xp": 340, "level": 2, "previous_level": 1, "reason": "the wolves"}'
    assert ev.parse_event("award", data) == ev.Award(120, 340, 2, 1, "the wolves")
    assert ev.parse_event("award", "{}") == ev.Award()


def test_award_lines():
    assert award_text(120, 340, 1, False, "the wolves") == "  +120 XP (total 340) for the wolves"
    assert award_text(0, 340, 3, True, "the first quest") == "  Level up! The party is now level 3 for the first quest"
    assert award_text(50, 400, 3, True, "") == "  +50 XP (total 400). Level up! The party is now level 3"


def test_history_shows_awards_again():
    messages = [{"role": "assistant", "content": [
        {"type": "tool_use", "id": "a1", "name": "award", "input": {"xp": 90, "reason": "the bridge troll"}},
        {"type": "tool_use", "id": "a2", "name": "award", "input": {"level": 2, "reason": "the first quest"}},
    ]}]  # fmt: skip
    text = "\n".join(str(b.__dict__) for b in history_to_blocks(messages))
    assert "+90 XP for the bridge troll" in text and "Level up! The party is now level 2" in text


async def test_a_live_award_is_shown_in_the_transcript():
    end = {"message_id": "m1", "stop_reason": "end_turn", "usage": {}}
    award = {"tool_use_id": "a", "xp_gained": 120, "xp": 120, "level": 1, "previous_level": 1, "reason": "the wolves"}
    up = {"tool_use_id": "b", "xp_gained": 0, "xp": 120, "level": 2, "previous_level": 1, "reason": "the quest"}
    fake = FakeServer([("message_start", {"message_id": "m1", "session_id": "default"}), ("award", award),
                       ("award", up), ("text", {"delta": "The wolves lie still. "}), ("message_end", end)])  # fmt: skip
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "I fight")
        await settle(pilot, lambda: not app.session.busy and "Level up" in screen_text(app))
        text = screen_text(app)
        assert "+120 XP (total 120) for the wolves" in text and "The party is now level 2" in text
