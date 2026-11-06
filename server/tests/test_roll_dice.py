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
    assert [s["name"] for s in tool_schemas()] == ["roll_dice", "recall", "establish", "key_item", "set_scene", "pass_time", "update_character", "set_combat", "set_motive", "social_check", "award", "defeat"]
    assert not dispatch("roll_dice", "t", {"expression": "1d6", "narration": "The die spins."}).is_error
    assert dispatch("nope", "t", {}).is_error


# ---- difficulty (docs/ATTEMPTS.md 6.1) ----------------------------------------------------------------------

import d20 as _d20

_REAL_ROLL = _d20.roll


def _fix_total(monkeypatch, total):
    """Make every roll come to this total, whatever the expression."""
    monkeypatch.setattr(_d20, "roll", lambda expr, **kw: _REAL_ROLL(str(total)))


def _roll(expression, **extra):
    from aigm.tools import dispatch

    return dispatch("roll_dice", "t1", {"expression": expression, "narration": "The lock resists her picks.", **extra})


def test_a_dc_gives_a_verdict_for_the_gm(monkeypatch):
    _fix_total(monkeypatch, 14)
    out = _roll("1d20+3", dc=18)
    assert "Failure by 4 (DC 18)." in out.content and not out.is_error
    assert "Success by 1 (DC 13)." in _roll("1d20+3", dc=13).content
    assert "exactly the DC" in _roll("1d20+3", dc=14).content


def test_roll_under_succeeds_at_or_below_the_dc(monkeypatch):
    _fix_total(monkeypatch, 14)
    assert "Success by 3 (DC 17 (roll under))." in _roll("1d20", dc=17, dc_mode="under").content
    assert "Failure by 4 (DC 10 (roll under))." in _roll("1d20", dc=10, dc_mode="under").content


def test_no_dc_no_verdict_and_bad_dcs_are_refused_before_rolling():
    assert "DC" not in _roll("1d20+3").content
    for bad in ({"dc": 0}, {"dc": 101}, {"dc": 3.5}, {"dc": True}, {"dc": 10, "dc_mode": "sideways"}, {"dc_mode": "under"}):
        out = _roll("1d20", **bad)
        assert out.is_error and "Nothing was rolled" in out.content and out.event is None


def test_the_verdict_comes_before_the_time_that_passed(monkeypatch):
    from aigm.session.state import GameState, Phase
    from aigm.tools import dispatch

    _fix_total(monkeypatch, 20)
    state = GameState(Phase.ADVENTURE, {"setting": "x"})
    out = dispatch("roll_dice", "t1", {"expression": "1d20", "narration": "She works the lock.", "dc": 15, "minutes": 10}, state)
    assert "Success by 5 (DC 15). 10 minutes pass." in out.content
