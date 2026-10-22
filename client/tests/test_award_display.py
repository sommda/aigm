"""How the client shows experience and levels (docs/PROGRESSION.md)."""

from aigm_client import events as ev
from aigm_client.blocks import award_lines, history_to_blocks
from tests.fake_server import FakeServer
from tests.test_app_pilot import make_app, screen_text, send, settle, start

DATA = (
    '{"xp_gained": 120, "to": ["Maren"], "everyone": false, "average_level": 1.5, "reason": "the wolves",'
    ' "characters": [{"name": "Maren", "xp": 340, "level": 2, "previous_level": 1}]}'
)


def test_the_award_event_is_parsed():
    award = ev.parse_event("award", DATA)
    assert (award.xp_gained, award.to, award.everyone, award.average_level) == (120, ("Maren",), False, 1.5)
    assert award.characters == (ev.Standing("Maren", 340, 2, 1),)
    assert ev.parse_event("award", "{}") == ev.Award()


def test_award_lines():
    assert award_lines(120, [], True, [], "the wolves") == ["  +120 XP to the party for the wolves"]
    assert award_lines(50, ["Maren", "Ilyr"], False, [], "") == ["  +50 XP each to Maren, Ilyr"]
    assert award_lines(50, ["Maren"], False, [], "") == ["  +50 XP to Maren"]
    assert award_lines(0, [], False, [("Maren", 3), ("Ilyr", 2)], "the quest") == [
        "  Maren reaches level 3! for the quest", "  Ilyr reaches level 2!"
    ]  # fmt: skip


def test_history_shows_awards_again():
    messages = [{"role": "assistant", "content": [
        {"type": "tool_use", "id": "a1", "name": "award", "input": {"xp": 90, "reason": "the bridge troll"}},
        {"type": "tool_use", "id": "a2", "name": "award", "input": {"level_up": ["Maren"], "reason": "the first quest"}},
    ]}]  # fmt: skip
    text = "\n".join(str(b.__dict__) for b in history_to_blocks(messages))
    assert "+90 XP to the party for the bridge troll" in text and "Maren gains a level!" in text


async def test_a_live_award_is_shown_in_the_transcript():
    end = {"message_id": "m1", "stop_reason": "end_turn", "usage": {}}
    award = {"tool_use_id": "a", "xp_gained": 120, "to": ["Maren"], "everyone": False, "average_level": 1.5,
             "reason": "the wolves", "characters": [{"name": "Maren", "xp": 340, "level": 2, "previous_level": 1}]}  # fmt: skip
    fake = FakeServer([("message_start", {"message_id": "m1", "session_id": "default"}), ("award", award),
                       ("text", {"delta": "The wolves lie still. "}), ("message_end", end)])  # fmt: skip
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "I fight")
        await settle(pilot, lambda: not app.session.busy and "reaches level 2" in screen_text(app))
        text = screen_text(app)
        assert "+120 XP to Maren for the wolves" in text and "Maren reaches level 2!" in text
