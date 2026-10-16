from aigm_client.events import DiceRoll, ErrorEvent, MessageEnd, Text, Thinking, Unknown, parse_event
from aigm_client.sse import SSEDecoder


def decode_all(lines):
    d = SSEDecoder()
    return [m for m in (d.decode(l) for l in lines) if m]


def test_basic_message():
    msgs = decode_all(["event: text", 'data: {"delta":"hi"}', ""])
    assert [(m.event, m.data) for m in msgs] == [("text", '{"delta":"hi"}')]


def test_comments_and_blank_lines_ignored():
    msgs = decode_all([": ping", "", "event: text", "data: {}", "", ": ping", ""])
    assert len(msgs) == 1


def test_multiline_data_and_no_space_after_colon():
    msgs = decode_all(["event:x", "data:a", "data: b", ""])
    assert msgs[0].event == "x" and msgs[0].data == "a\nb"


def test_default_event_name_and_trailing_cr():
    msgs = decode_all(["data: 1\r", "\r"])
    assert msgs[0].event == "message" and msgs[0].data == "1"


def test_parse_known_events():
    assert parse_event("text", '{"delta":"x"}') == Text("x")
    assert parse_event("thinking", '{"status":"end","duration_ms":5}') == Thinking("end", "", 5)
    assert parse_event("message_end", '{"stop_reason":"end_turn"}') == MessageEnd("", "end_turn", {})
    assert parse_event("error", '{"code":"upstream_error","message":"m","retryable":true}') == ErrorEvent(
        "upstream_error", "m", True
    )


def test_parse_dice_roll():
    ev = parse_event(
        "dice_roll",
        '{"tool_use_id":"t","expression":"2d6","total":7,"result":"r","crit":"none","comment":null,'
        '"dice":[{"notation":"2d6","count":2,"sides":6,"total":7,"annotation":null,'
        '"rolls":[{"value":3,"kept":true,"values":[3]},{"value":4,"kept":false,"values":[4]}]}]}',
    )
    assert isinstance(ev, DiceRoll) and ev.total == 7
    assert [r.kept for r in ev.dice[0].rolls] == [True, False]


def test_unknown_event_and_bad_json():
    assert parse_event("future_thing", '{"a":1}') == Unknown("future_thing", {"a": 1})
    assert parse_event("text", "{not json") is None
    assert parse_event("text", "[1,2]") is None
