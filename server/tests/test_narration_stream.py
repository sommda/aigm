"""The incremental extractor of a tool call's `narration` (docs/NARRATION_STREAMING.md, section 5)."""

import json

import pytest

from aigm.llm.narration import NarrationStream


def run(pieces: list[str]) -> tuple[str, NarrationStream]:
    stream = NarrationStream()
    out = "".join(stream.feed(p) for p in pieces) + stream.finish()
    return out, stream


def every_split(text: str):
    yield [text]
    yield list(text)  # one character at a time
    for i in range(1, len(text)):
        yield [text[:i], text[i:]]


SAMPLES = [
    {"expression": "1d20+5", "narration": "You swing the blade."},
    {"narration": "First.\n\nSecond \"quoted\" and \\ slash / done", "expression": "1d20"},
    {"expression": "1d20", "narration": "Café ☃ \U0001f40d snake 😀 face"},
    {"expression": "1d20", "narration": "  padded with spaces and a newline \n\n "},
    {"x": {"narration": "nested", "a": [1, {"narration": "deeper"}]}, "narration": "the real one", "y": [1, 2]},
    {"note": 'has "narration": "fake" and } { inside', "narration": "genuine text", "n": None, "t": True, "k": -1.5e3},
    {"expression": "1d20", "narration": ""},
    {"expression": "1d20"},
]


@pytest.mark.parametrize("sample", SAMPLES)
@pytest.mark.parametrize("ascii_only", [True, False])
def test_every_split_gives_the_whole_narration(sample, ascii_only):
    raw = json.dumps(sample, ensure_ascii=ascii_only)
    expected = sample.get("narration", "").strip() if isinstance(sample.get("narration"), str) else ""
    for pieces in every_split(raw):
        out, stream = run(pieces)
        assert out == expected, pieces
        assert not stream.failed and stream.complete


def test_text_comes_out_before_the_input_ends():
    stream = NarrationStream()
    assert stream.feed('{"expression": "1d20", "narr') == ""
    assert stream.feed('ation": "You plant your fe') == "You plant your fe"
    assert stream.feed("et and swing") == "et and swing"
    assert stream.feed('."}') == "."


def test_an_escape_cut_in_the_middle_waits_for_the_rest():
    stream = NarrationStream()
    assert stream.feed('{"narration": "a\\') == "a"
    assert stream.feed("nb") == "\nb"
    assert stream.feed("\\u00") == ""
    assert stream.feed('e9"}') == "é"


def test_a_surrogate_pair_split_across_fragments_is_one_character():
    out, _ = run(['{"narration": "x\\ud83d', '\\ude00y"}'])
    assert out == "x\U0001f600y"


def test_a_lone_surrogate_becomes_a_replacement_character():
    assert run(['{"narration": "a\\ud83dz"}'])[0] == "a�z"
    assert run(['{"narration": "a\\ude00z"}'])[0] == "a�z"
    assert run(['{"narration": "a\\ud83d"}'])[0] == "a�"


def test_leading_whitespace_is_dropped_and_trailing_whitespace_is_held_back():
    stream = NarrationStream()
    assert stream.feed('{"narration": "  \\n ') == ""
    assert stream.feed("Hello ") == "Hello"
    assert stream.feed("  ") == ""
    assert stream.feed("there \\n") == "   there"
    assert stream.feed('"}') == ""


def test_a_duplicate_narration_key_fails_the_stream():
    out, stream = run(['{"narration": "first", "narration": "second"}'])
    assert out == "first" and stream.failed


def test_a_narration_that_is_not_a_string_produces_nothing():
    for raw in ('{"narration": 12, "expression": "1d20"}', '{"narration": {"a": "b"}}', '{"narration": null}'):
        out, stream = run([raw])
        assert out == "" and not stream.failed, raw


@pytest.mark.parametrize(
    "raw",
    [
        'narration',  # no object
        '{"narration" "x"}',  # missing colon
        '{"narration": "bad \\q escape"}',
        '{"narration": "bad \\u12g4"}',
        '{"narration": }',
        '{"a": 1} trailing',
    ],
)
def test_malformed_input_fails_and_stops_producing(raw):
    stream = NarrationStream()
    stream.feed(raw)
    assert stream.failed
    assert stream.feed('{"narration": "more"}') == ""


def test_text_shown_before_a_failure_stays_returned():
    stream = NarrationStream()
    assert stream.feed('{"narration": "Hello, ') == "Hello,"
    assert stream.feed("world\\q more") == " world"
    assert stream.failed


def test_input_that_ends_early_marks_the_stream_failed():
    out, stream = run(['{"narration": "cut off'])
    assert out == "cut off" and stream.failed and not stream.complete


def test_a_bare_control_character_is_accepted():
    assert run(['{"narration": "line\none"}'])[0] == "line\none"
