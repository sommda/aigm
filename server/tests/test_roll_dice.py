import pytest

from aigm.models import DiceRoll
from aigm.tools import dispatch, tool_schemas
from aigm.tools.roll_dice import MAX_EXPRESSION_LENGTH, roll_dice


def roll(expr):
    return roll_dice("toolu_1", {"expression": expr, "narration": "The dice tumble across the table."})


def test_simple_roll():
    out = roll("1d20+5")
    assert not out.is_error
    ev = out.event
    assert isinstance(ev, DiceRoll)
    assert ev.tool_use_id == "toolu_1" and ev.expression == "1d20+5"
    assert 6 <= ev.total <= 25
    assert out.content == ev.result
    assert len(ev.dice) == 1
    term = ev.dice[0]
    assert (term.notation, term.count, term.sides) == ("1d20", 1, 20)
    assert len(term.rolls) == 1 and term.rolls[0].kept
    assert term.rolls[0].value + 5 == ev.total
    assert ev.crit in {"none", "crit", "fail"}


def test_keep_highest_structure_and_invariants():
    for _ in range(50):
        ev = roll("4d6kh3+2").event
        term = ev.dice[0]
        assert term.notation == "4d6kh3" and term.count == 4
        assert len(term.rolls) == 4
        assert sum(1 for r in term.rolls if r.kept) == 3
        kept_sum = sum(r.value for r in term.rolls if r.kept)
        assert term.total == kept_sum
        assert ev.total == kept_sum + 2
        assert all(1 <= r.value <= 6 for r in term.rolls)


def test_multiple_terms_and_no_dice():
    ev = roll("2d8+1d4+3").event
    assert [t.notation for t in ev.dice] == ["2d8", "1d4"]
    assert roll("5+3").event.dice == []
    assert roll("5+3").event.total == 8


def test_advantage_keeps_one():
    term = roll("2d20kh1").event.dice[0]
    assert term.count == 2
    assert sum(r.kept for r in term.rolls) == 1


def test_comment_and_annotation_survive():
    out = roll("1d20+5 [slashing] # hit goblin")
    assert not out.is_error
    assert out.event.comment == "hit goblin"
    assert "slashing" in out.event.result


@pytest.mark.parametrize("expr", ["2x20", "", "   ", "1d", "((", "d", "1d20+", None, 5])
def test_malformed(expr):
    out = roll(expr)
    assert out.is_error and out.event is None
    assert out.content.startswith("Invalid dice expression")
    assert "Expected syntax" in out.content


def test_missing_expression():
    assert roll_dice("t", {}).is_error


def test_too_long():
    out = roll("1+" * MAX_EXPRESSION_LENGTH + "1")
    assert out.is_error and "longer than" in out.content


def test_too_many_rolls():
    out = roll("100000d6")
    assert out.is_error


def test_registry():
    assert [s["name"] for s in tool_schemas()] == ["roll_dice", "recall", "establish", "set_scene", "award"]
    assert not dispatch("roll_dice", "t", {"expression": "1d6", "narration": "The die spins."}).is_error
    assert dispatch("nope", "t", {}).is_error
