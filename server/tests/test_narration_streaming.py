"""Roll narration is shown while the model is still writing the call (docs/NARRATION_STREAMING.md)."""

import json

from aigm.game import Game
from aigm.llm.base import Completed, TextChunk, ToolInputChunk, ToolInputStarted, ToolInputStopped
from aigm.llm.loop import ALREADY_SHOWN, run_turn
from aigm.session.store import Session

NARRATION = "The counterweight lurches loose above you."


def call(expression="1d20+3", narration=NARRATION, id="r1"):
    return {"type": "tool_use", "id": id, "name": "roll_dice", "input": {"expression": expression, "narration": narration}}


def fragments(text: str, size: int = 7) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


class Streaming:
    """Answers with the given responses in order. Each is (reply text, tool calls, stop reason); the tool calls'
    input goes out as JSON fragments, expression first like the real model writes it."""

    def __init__(self, *responses, size=7):
        self.responses, self.size = list(responses), size

    async def stream(self, *, system, messages, tools):
        text, calls, stop = self.responses.pop(0)
        if text:
            yield TextChunk(text)
        for block in calls:
            yield ToolInputStarted(block["id"], block["name"])
            given = block["input"]
            raw = json.dumps({**{k: v for k, v in given.items() if k != "narration"}, "narration": given.get("narration")})
            for piece in fragments(raw, self.size):
                yield ToolInputChunk(block["id"], piece)
            yield ToolInputStopped(block["id"])
        yield Completed(content=([{"type": "text", "text": text}] if text else []) + calls, stop_reason=stop)


async def play(llm, **kw):
    session = Session("s")
    events = [e async for e in run_turn(session=session, user_text="I crawl on.", llm=llm, game=Game(), max_iters=6, **kw)]
    return events, session


def kinds(events):
    return [type(e).__name__ for e in events]


def shown(events):
    return "".join(e.delta for e in events if type(e).__name__ == "TextDelta")


def results(session):
    return [b for m in session.messages if m["role"] == "user" for b in m["content"] if b.get("type") == "tool_result"]


async def test_the_narration_arrives_in_pieces_before_the_call_is_dispatched():
    events, _ = await play(Streaming(("", [call()], "tool_use"), ("You dive clear.", [], "end_turn")))
    order = kinds(events)
    pieces = [i for i, e in enumerate(events) if kinds([e]) == ["TextDelta"]]
    assert len([p for p in pieces if p < order.index("ToolCall")]) > 3  # streamed, not one burst
    assert max(p for p in pieces if p < order.index("ToolCall")) < order.index("ToolCall") < order.index("DiceRoll")
    assert shown(events) == f"{NARRATION}\n\nYou dive clear."  # shown once, not again at dispatch


async def test_text_already_written_is_separated_from_the_streamed_narration():
    events, _ = await play(Streaming(("You edge forward.", [call()], "tool_use"), ("Done.", [], "end_turn")))
    assert shown(events) == f"You edge forward.\n\n{NARRATION}\n\nDone."


async def test_several_rolls_show_narration_after_narration_and_then_the_dice():
    calls = [call("1d20+5", "You lunge at the goblin.", "a"), call("1d6", "If it lands, it bites.", "b")]
    events, _ = await play(Streaming(("", calls, "tool_use"), ("Hit.", [], "end_turn")))
    assert shown(events) == "You lunge at the goblin.\n\nIf it lands, it bites.\n\nHit."
    order = kinds(events)
    assert order.index("DiceRoll") > max(i for i, e in enumerate(events) if kinds([e]) == ["TextDelta"] and i < order.index("ToolCall"))


async def test_the_fragment_size_does_not_change_what_is_shown():
    for size in (1, 3, 50, 500):
        events, _ = await play(Streaming(("Go.", [call()], "tool_use"), ("Ok.", [], "end_turn"), size=size))
        assert shown(events) == f"Go.\n\n{NARRATION}\n\nOk.", size


async def test_the_tool_status_ends_when_the_narration_starts():
    events, _ = await play(Streaming(("", [call()], "tool_use"), ("Ok.", [], "end_turn")))
    order = kinds(events)
    statuses = [i for i, e in enumerate(events) if kinds([e]) == ["Status"]]
    assert [events[i].done for i in statuses] == [False, True]
    assert statuses[0] < statuses[1] < order.index("TextDelta")


async def test_the_first_visible_text_is_the_first_piece_of_narration():
    events, _ = await play(Streaming(("", [call()], "tool_use"), ("Ok.", [], "end_turn")))
    end = events[-1]
    first = end.metrics["requests"][0]
    assert first["first_text_ms"] is not None and first["narration_chars"] == len(NARRATION)
    assert end.metrics["requests"][1]["narration_chars"] == 0 and end.metrics["first_text_ms"] is not None


async def test_a_refused_call_after_streamed_narration_tells_the_model_it_was_shown():
    llm = Streaming(
        ("", [call(expression="2x20")], "tool_use"),
        ("", [call(narration="It hits you for real this time.", id="r2")], "tool_use"),
        ("Safe.", [], "end_turn"),
    )
    events, session = await play(llm)
    first, second = results(session)
    assert first["is_error"] and ALREADY_SHOWN in first["content"] and not second["is_error"]
    assert kinds(events).count("DiceRoll") == 1
    assert shown(events) == f"{NARRATION}\n\nIt hits you for real this time.\n\nSafe."  # shown once each


async def test_a_too_short_narration_is_refused_even_though_it_was_shown():
    llm = Streaming(("", [call(narration="Roll.")], "tool_use"), ("", [call(id="r2")], "tool_use"), ("Ok.", [], "end_turn"))
    events, session = await play(llm)
    first, second = results(session)
    assert first["is_error"] and "Nothing was rolled" in first["content"] and ALREADY_SHOWN in first["content"]
    assert not second["is_error"] and kinds(events).count("DiceRoll") == 1


async def test_a_call_without_narration_shows_nothing_and_is_refused():
    llm = Streaming(("", [call(narration=None)], "tool_use"), ("", [call(id="r2")], "tool_use"), ("Ok.", [], "end_turn"))
    events, session = await play(llm)
    first, _ = results(session)
    assert first["is_error"] and ALREADY_SHOWN not in first["content"]
    assert shown(events) == f"{NARRATION}\n\nOk."


async def test_a_client_that_streams_no_tool_input_still_shows_the_narration_at_dispatch():
    class Plain:
        def __init__(self):
            self.responses = [[call()], []]

        async def stream(self, *, system, messages, tools):
            calls = self.responses.pop(0)
            yield Completed(content=calls or [{"type": "text", "text": "Ok."}], stop_reason="tool_use" if calls else "end_turn")

    events, _ = await play(Plain())
    assert shown(events) == f"{NARRATION}\n\n"


async def test_an_unreadable_call_keeps_what_was_shown_and_does_not_repeat_it_at_dispatch():
    class Broken:
        def __init__(self):
            self.turns = 0

        async def stream(self, *, system, messages, tools):
            self.turns += 1
            if self.turns == 2:
                yield TextChunk("Ok.")
                yield Completed(content=[{"type": "text", "text": "Ok."}], stop_reason="end_turn")
                return
            yield ToolInputStarted("r1", "roll_dice")
            yield ToolInputChunk("r1", '{"expression": "1d20", "narration": "You step out, then ')
            yield ToolInputChunk("r1", "\\q the rest")  # an invalid escape: the extractor gives up
            yield ToolInputStopped("r1")
            yield Completed(content=[call(narration="You step out, then q the rest")], stop_reason="tool_use")

    events, _ = await play(Broken())
    assert shown(events) == "You step out, then\n\nOk."  # the partial text stays; the dispatch does not add it again
