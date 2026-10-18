"""The reduced history the model is shown (docs/HISTORY.md): trimming, digests, and cache stability."""

import copy

import pytest

from aigm.history import (
    STORY_OPEN,
    HistoryPolicy,
    cut,
    reduce_history,
    trim_turn,
    turns,
)
from aigm.session.persistence import validate_messages
from aigm.world.digest import Digest


def text(t):
    return [{"type": "text", "text": t}]


def make_history(n_turns, *, tools=True):
    """A record turn (the first), then `n_turns - 1` turns, each with thinking, a dice roll and narration."""
    msgs = [
        {"role": "user", "content": text("note")},
        {"role": "assistant", "content": text("RECORD")},
    ]
    for n in range(2, n_turns + 1):
        msgs.append({"role": "user", "content": text(f"player {n}")})
        if tools:
            msgs.append(
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": f"think {n}", "signature": "sig"},
                        {"type": "text", "text": f"GM {n} before"},
                        {"type": "tool_use", "id": f"t{n}", "name": "roll_dice", "input": {"expression": "1d20+5"}},
                    ],
                }
            )
            msgs.append(
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": f"t{n}", "content": "1d20 (13) + 5 = `18`"}],
                }
            )
        msgs.append({"role": "assistant", "content": text(f"GM {n} after")})
    return msgs


def make_digests(messages):
    return {t.start: Digest(t.start, t.end, t.number, f"digest {t.number}", 10) for t in turns(messages)[1:]}


def all_text(messages):
    return "\n".join(b.get("text", "") for m in messages for b in m["content"] if b["type"] == "text")


def test_turns_split_at_player_messages_not_at_tool_results():
    msgs = make_history(4)
    ts = turns(msgs)
    assert [(t.start, t.end, t.number) for t in ts] == [(0, 2, 1), (2, 6, 2), (6, 10, 3), (10, 14, 4)]
    assert turns([]) == []


def test_cut_moves_in_steps_and_keeps_the_newest_turns():
    assert [cut(t, 12, 12) for t in (1, 12, 23, 24, 35, 36, 40)] == [0, 0, 0, 12, 12, 24, 24]
    assert all(t - cut(t, 4, 6) >= min(t, 4) for t in range(1, 100))
    assert cut(10, 0, 0) == 9  # nonsense settings are clamped, not divided by zero


def test_nothing_to_reduce_returns_the_same_list():
    msgs = make_history(5)
    assert reduce_history(msgs, {}, HistoryPolicy(trim_keep=4, trim_step=6)).messages is msgs
    assert reduce_history(msgs, make_digests(msgs), HistoryPolicy(trim=False, digest=False)).messages is msgs
    assert reduce_history([], {}, HistoryPolicy()).messages == []


def test_trim_drops_thinking_and_folds_tool_calls_into_notes():
    msgs = make_history(3)
    out = trim_turn(msgs[2:6])
    assert [m["role"] for m in out] == ["user", "assistant"]
    blocks = out[1]["content"]
    assert [b["type"] for b in blocks] == ["text", "text", "text"]
    assert blocks[0]["text"] == "GM 2 before"
    assert blocks[1]["text"] == "(Rolled 1d20+5: 1d20 (13) + 5 = 18)"
    assert blocks[2]["text"] == "GM 2 after"


def test_trim_handles_several_calls_in_a_row_and_unanswered_calls():
    use = lambda i, name, inp: {"type": "tool_use", "id": i, "name": name, "input": inp}  # noqa: E731
    res = lambda i, c, **kw: {"type": "tool_result", "tool_use_id": i, "content": c, **kw}  # noqa: E731
    msgs = [
        {"role": "user", "content": text("go")},
        {"role": "assistant", "content": [use("a", "roll_dice", {"expression": "1d4"}), use("b", "lookup", {"q": "x"})]},
        {"role": "user", "content": [res("a", "1d4 (2) = `2`"), res("b", "no such thing", is_error=True)]},
        {"role": "assistant", "content": [use("c", "roll_dice", {"expression": "bad"})]},
        {"role": "user", "content": [res("c", "Invalid dice expression", is_error=True)]},
        {"role": "assistant", "content": text("done")},
    ]
    out = trim_turn(msgs)
    assert [m["role"] for m in out] == ["user", "assistant"]
    notes = [b["text"] for b in out[1]["content"]]
    assert notes == [
        "(Rolled 1d4: 1d4 (2) = 2)",
        '(Used lookup {"q": "x"}: error: no such thing)',
        "(Rolled bad: error: Invalid dice expression)",
        "done",
    ]
    assert trim_turn(msgs[:2])[1]["content"][0]["text"].endswith("no result)")


def test_trim_keeps_a_message_that_is_only_thinking():
    msgs = [
        {"role": "user", "content": text("hi")},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "hmm", "signature": "s"}]},
    ]
    assert trim_turn(msgs)[1]["content"][0]["type"] == "thinking"


def test_trim_only_touches_turns_older_than_the_cut():
    msgs = make_history(20)
    policy = HistoryPolicy(digest=False, trim_keep=4, trim_step=6)  # T=20: turns before index 12 are trimmed
    reduced = reduce_history(msgs, {}, policy)
    ts = turns(msgs)
    assert reduced.info.trim_cut == 12 and reduced.info.trimmed_turns == 11 and reduced.info.digested_turns == 0
    assert reduced.messages[: ts[1].start] == msgs[: ts[1].start]  # the record turn is untouched
    verbatim = len(msgs) - ts[12].start
    assert reduced.messages[-verbatim:] == msgs[ts[12].start :]  # the newest turns are verbatim
    older = {b["type"] for m in reduced.messages[2:-verbatim] for b in m["content"]}
    assert older == {"text"}
    assert len(reduced.messages) < len(msgs)
    validate_messages(reduced.messages)


def test_digests_replace_old_turns_and_sit_in_front_of_the_oldest_full_turn():
    msgs = make_history(30)
    reduced = reduce_history(msgs, make_digests(msgs), HistoryPolicy(digest_keep=12, digest_step=12, trim=False))
    info = reduced.info
    assert info.digest_cut == 12 and info.digested_turns == 11  # turns 2..12 are digests
    first_full = reduced.messages[2]
    assert first_full["role"] == "user"
    story, original = first_full["content"][0]["text"], first_full["content"][1]["text"]
    assert story.startswith(STORY_OPEN) and "[Turn 2] digest 2" in story and "[Turn 12] digest 12" in story
    assert "[Turn 13]" not in story and original == "player 13"
    assert "GM 5 after" not in all_text(reduced.messages) and "GM 13 after" in all_text(reduced.messages)
    assert reduced.messages[:2] == msgs[:2]  # the record turn is always shown in full
    validate_messages(reduced.messages)


def test_a_missing_digest_stops_the_cut_there():
    msgs = make_history(30)
    digests = make_digests(msgs)
    del digests[turns(msgs)[6].start]  # turn 7 has none
    reduced = reduce_history(msgs, digests, HistoryPolicy(digest_keep=12, digest_step=12, trim=False))
    assert reduced.info.digest_cut == 6 and reduced.info.digested_turns == 5
    assert "[Turn 6] digest 6" in reduced.messages[2]["content"][0]["text"]
    assert "GM 7 after" in all_text(reduced.messages)


def test_a_digest_that_does_not_fit_the_turn_is_ignored():
    msgs = make_history(30)
    digests = make_digests(msgs)
    t = turns(msgs)[1]
    digests[t.start] = Digest(t.start, t.end + 1, t.number, "stale", 1)
    reduced = reduce_history(msgs, digests, HistoryPolicy(digest_keep=12, digest_step=12, trim=False))
    assert reduced.info.digested_turns == 0 and reduced.messages is msgs


def test_digested_and_trimmed_bands_combine_and_the_result_is_valid():
    msgs = make_history(40)
    policy = HistoryPolicy(trim_keep=4, trim_step=6, digest_keep=12, digest_step=12)
    reduced = reduce_history(msgs, make_digests(msgs), policy)
    info = reduced.info
    assert (info.digest_cut, info.trim_cut) == (24, 36)
    assert info.digested_turns == 23 and info.trimmed_turns == 12
    validate_messages(reduced.messages)
    assert len(info.turn_of) == len(reduced.messages)
    assert reduced.messages[2]["content"][0]["text"].startswith(STORY_OPEN)
    assert info.turn_of[2] == 25  # the story block rides on the first full turn


def test_the_stored_messages_are_never_changed():
    msgs = make_history(40)
    before = copy.deepcopy(msgs)
    digests = make_digests(msgs)
    reduce_history(msgs, digests, HistoryPolicy())
    assert msgs == before


@pytest.mark.parametrize("policy", [HistoryPolicy(), HistoryPolicy(trim_keep=2, trim_step=3, digest_keep=5, digest_step=4)])
def test_every_reduction_is_a_valid_conversation(policy):
    for n in range(1, 60):
        msgs = make_history(n)
        validate_messages(reduce_history(msgs, make_digests(msgs), policy).messages)


@pytest.mark.parametrize("policy", [HistoryPolicy(), HistoryPolicy(trim_keep=2, trim_step=3, digest_keep=5, digest_step=4)])
def test_the_start_of_the_request_only_changes_when_a_cut_moves(policy):
    """Prompt caching needs the same prefix from one request to the next."""
    rewrites = 0
    previous = None
    for n in range(2, 80):
        msgs = make_history(n)
        red = reduce_history(msgs, make_digests(msgs), policy)
        if previous is not None:
            prev_red, prev_msgs = previous
            same_cuts = (prev_red.info.digest_cut, prev_red.info.trim_cut) == (red.info.digest_cut, red.info.trim_cut)
            if same_cuts:
                assert red.messages[: len(prev_red.messages)] == prev_red.messages
            else:
                rewrites += 1
        previous = (red, msgs)
    assert rewrites <= 79 // policy.trim_step + 79 // policy.digest_step + 2


def test_size_estimates_leave_out_thinking_signatures():
    from aigm.history import block_chars, message_chars

    block = {"type": "thinking", "thinking": "abcd", "signature": "S" * 5000}
    assert block_chars(block) == block_chars({"type": "thinking", "thinking": "abcd"}) < 60
    assert message_chars([{"role": "assistant", "content": [block]}]) == block_chars(block)
