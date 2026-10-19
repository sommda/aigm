"""Every roll carries the narration that leads into it, and the server shows it as story text before the dice."""

import json

import pytest

from aigm.game import Game
from aigm.llm.base import Completed, TextChunk
from aigm.llm.loop import run_turn
from aigm.session.store import Session
from aigm.tools import tool_schemas
from aigm.tools.roll_dice import MIN_NARRATION_CHARS, roll_dice
from aigm.world.passes import transcript


def roll_call(expression="1d20+3", narration="The counterweight lurches loose above you.", id="r1"):
    given = {"expression": expression}
    if narration is not None:
        given["narration"] = narration
    return {"type": "tool_use", "id": id, "name": "roll_dice", "input": given}


class Scripted:
    """Answers with the given responses in order: each is (streamed text, tool calls, stop reason)."""

    def __init__(self, *responses):
        self.responses = list(responses)

    async def stream(self, *, system, messages, tools):
        text, calls, stop = self.responses.pop(0)
        if text:
            yield TextChunk(text)
        yield Completed(content=([{"type": "text", "text": text}] if text else []) + calls, stop_reason=stop)


async def play(llm, **kw):
    session = Session("s")
    events = [e async for e in run_turn(session=session, user_text="I crawl on.", llm=llm, game=Game(), max_iters=6, **kw)]
    return events, session


def kinds(events):
    return [type(e).__name__ for e in events]


def shown(events):
    return "".join(e.delta for e in events if type(e).__name__ == "TextDelta")


def test_the_schema_requires_a_narration():
    schema = next(s for s in tool_schemas() if s["name"] == "roll_dice")["input_schema"]
    assert "narration" in schema["properties"] and set(schema["required"]) == {"expression", "narration"}


@pytest.mark.parametrize("narration", [None, "", "   ", "Roll.", 5])
def test_a_roll_without_a_real_narration_is_refused_and_nothing_is_rolled(narration):
    given = {"expression": "1d20"}
    if narration is not None:
        given["narration"] = narration
    out = roll_dice("t", given)
    assert out.is_error and out.event is None and out.say == ""
    assert "narration" in out.content and "Nothing was rolled" in out.content
    assert MIN_NARRATION_CHARS > len("Roll.")


def test_a_valid_roll_carries_its_narration_to_be_shown():
    out = roll_dice("t", {"expression": "1d20", "narration": "  The counterweight lurches loose.  "})
    assert not out.is_error and out.say == "The counterweight lurches loose." and out.event is not None


def test_a_bad_expression_shows_no_narration_so_the_retry_does_not_repeat_it():
    out = roll_dice("t", {"expression": "2x20", "narration": "The counterweight lurches loose."})
    assert out.is_error and out.say == ""


async def test_the_narration_is_streamed_as_text_before_the_dice():
    llm = Scripted(("", [roll_call()], "tool_use"), ("You dive clear.", [], "end_turn"))
    events, _ = await play(llm)
    order = kinds(events)
    first_text = order.index("TextDelta")
    assert events[first_text].delta == "The counterweight lurches loose above you.\n\n"
    assert first_text < order.index("DiceRoll")  # the player reads it before the dice land
    assert shown(events) == "The counterweight lurches loose above you.\n\nYou dive clear."


async def test_text_already_written_is_separated_from_the_narration():
    llm = Scripted(("You edge forward.", [roll_call()], "tool_use"), ("Done.", [], "end_turn"))
    events, _ = await play(llm)
    assert shown(events) == "You edge forward.\n\nThe counterweight lurches loose above you.\n\nDone."


async def test_several_rolls_each_show_their_own_narration_in_order():
    calls = [roll_call("1d20+5 # attack", "You lunge at the goblin.", "a"), roll_call("1d6", "If it lands, it bites.", "b")]
    llm = Scripted(("", calls, "tool_use"), ("Hit.", [], "end_turn"))
    events, _ = await play(llm)
    assert shown(events) == "You lunge at the goblin.\n\nIf it lands, it bites.\n\nHit."
    names = kinds(events)
    assert names.index("DiceRoll") < len(names) - 1 and names.count("DiceRoll") == 2


async def test_a_roll_without_narration_shows_nothing_and_the_model_can_try_again():
    llm = Scripted(("", [roll_call(narration=None)], "tool_use"), ("", [roll_call()], "tool_use"), ("Safe.", [], "end_turn"))
    events, session = await play(llm)
    assert kinds(events).count("DiceRoll") == 1  # only the repaired call rolled
    assert shown(events) == "The counterweight lurches loose above you.\n\nSafe."
    results = [b for m in session.messages if m["role"] == "user" for b in m["content"] if b.get("type") == "tool_result"]
    assert results[0]["is_error"] and "narration" in results[0]["content"] and not results[1]["is_error"]


async def test_the_narration_stays_in_the_saved_tool_call():
    llm = Scripted(("", [roll_call()], "tool_use"), ("Done.", [], "end_turn"))
    _, session = await play(llm)
    assert "The counterweight lurches loose above you." in json.dumps(session.messages)


def test_the_curator_reads_the_narration_as_part_of_the_gm_text():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "crawl on"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "You edge forward."}, roll_call()]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "r1", "content": "1d20 (9) + 3 = `12`"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "You dive clear."}]},
    ]
    assert transcript(messages).split("\n\n") == [
        "PLAYER: crawl on",
        "GM: You edge forward.",
        "GM: The counterweight lurches loose above you.",
        "GM: You dive clear.",
    ]
