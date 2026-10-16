from aigm.models import DiceRoll, TextDelta, Thinking
from aigm.sse import encode


def test_encode_text():
    assert encode(TextDelta(delta="hi")) == 'event: text\ndata: {"delta":"hi"}\n\n'


def test_newlines_are_escaped_in_single_line_data():
    out = encode(TextDelta(delta="a\nb\n\nc"))
    assert out.count("\n") == 3  # event line, data line, blank terminator... one newline each
    assert '"a\\nb\\n\\nc"' in out


def test_thinking_omits_unset_fields():
    assert encode(Thinking(status="start")) == 'event: thinking\ndata: {"status":"start"}\n\n'
    assert '"duration_ms":5' in encode(Thinking(status="end", duration_ms=5))


def test_dice_roll_keeps_null_fields():
    ev = DiceRoll(tool_use_id="t", expression="1d6", total=3, result="r", crit="none", comment=None, dice=[])
    assert '"comment":null' in encode(ev)


def test_unicode_not_escaped():
    assert "🎲" in encode(TextDelta(delta="🎲"))
