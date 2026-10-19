"""Client side of the history reduction and metrics (docs/HISTORY.md): the digest color, header and turn line."""

from aigm_client import events as ev
from aigm_client.context_model import KIND_STYLES, ContextModel
from aigm_client.events import MessageEnd, parse_event
from aigm_client.session import ChatSession, metrics_line
from aigm_client.transcript import Transcript
from tests.fake_server import sample_context

METRICS = {
    "first_text_ms": 1234,
    "total_ms": 8421,
    "input_tokens": 12345,
    "cache_read_tokens": 11000,
    "cache_write_tokens": 900,
    "output_tokens": 640,
    "model_calls": 2,
}


def test_message_end_carries_the_metrics_and_older_servers_have_none():
    end = parse_event("message_end", '{"message_id": "m", "stop_reason": "end_turn", "usage": {}, "metrics": {"total_ms": 5}}')
    assert isinstance(end, MessageEnd) and end.metrics == {"total_ms": 5}
    assert parse_event("message_end", '{"message_id": "m", "stop_reason": "end_turn"}').metrics == {}


def test_metrics_line_is_short_and_readable():
    line = metrics_line(METRICS)
    assert line == "first text 1.2s · total 8.4s · in 12.3k (cached 11.0k, written 900) · out 640 · 2 call(s)"
    assert "first text -" in metrics_line({})  # a missing number never breaks the line


def end_event():
    return ev.MessageEnd("m", "end_turn", {}, "adventure", "", METRICS)


def line_count(s):
    return len(s.transcript.blocks)


def test_the_turn_line_appears_only_for_a_debug_server():
    quiet = ChatSession(Transcript())
    quiet.apply(end_event())
    assert line_count(quiet) == 0
    loud = ChatSession(Transcript())
    loud.show_metrics = True
    loud.apply(end_event())
    assert line_count(loud) == 1
    loud.apply(ev.MessageEnd("m", "end_turn", {}, "adventure"))  # no metrics: nothing to show
    assert line_count(loud) == 1


def digest_context():
    data = sample_context()
    data["reduction"] = {"digested_turns": 11, "trimmed_turns": 6, "history_tokens_saved": 4200}
    history = next(s for s in data["sections"] if s["id"] == "history")
    history["children"].insert(
        0,
        {
            "id": "history/9", "kind": "user", "title": "Turn 13 · Player: go", "tokens": 90,
            "children": [
                {"id": "history/9/0", "kind": "digest", "title": "Story so far (11 earlier turns condensed)",
                 "tokens": 80, "text": "<story_so_far>\n[Turn 2] The party met Wren.\n</story_so_far>"},
            ],
        },
    )  # fmt: skip
    return data


def test_the_header_reports_what_the_reduction_saved():
    head = ContextModel(digest_context()).header_text
    assert head.splitlines()[1] == "History reduced: 11 turns as digests, 6 trimmed, ~4,200 tokens saved"
    assert "reduced" not in ContextModel(sample_context()).header_text


def test_digest_blocks_have_their_own_color_and_show_as_text():
    assert KIND_STYLES["digest"] not in (KIND_STYLES["briefing"], KIND_STYLES["assistant"], KIND_STYLES["tools"])
    m = ContextModel(digest_context())
    m.toggle("history/9")
    m.toggle("history/9/0")
    text = "\n".join(t.plain for t in m.lines(80)[0])
    assert "digest · ~80 tok" in text and "[Turn 2] The party met Wren." in text


def test_a_rolls_narration_is_replayed_as_story_text_before_the_dice():
    from aigm_client.blocks import DiceBlock, MarkdownBlock, history_to_blocks

    messages = [
        {"role": "user", "content": [{"type": "text", "text": "crawl on"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "You edge forward."},
                {
                    "type": "tool_use",
                    "id": "r1",
                    "name": "roll_dice",
                    "input": {"expression": "1d20+3", "narration": "The counterweight lurches loose."},
                },
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "r1", "content": "1d20 (9) + 3 = `12`"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "You dive clear."}]},
    ]
    blocks = history_to_blocks(messages)
    kinds = [type(b) for b in blocks]
    assert kinds[-4:] == [MarkdownBlock, MarkdownBlock, DiceBlock, MarkdownBlock]
