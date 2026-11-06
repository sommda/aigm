"""The social check's implied attempt (docs/ATTEMPTS.md 6.3)."""

import d20
import pytest

from aigm import rulesets
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch
from aigm.world import WorldTime

REAL = d20.roll


def make(ruleset="dnd55e", motive=False):
    s = GameState(Phase.ADVENTURE, {"setting": "x", "party": [{"name": "Kit"}], "party_size": 1, "level": 1}, ruleset=ruleset)
    w = s.world
    hall = w.add_entity("Great hall", "location")
    steward = w.add_entity("Steward Hale", "npc")
    w.set_scene(hall.id, [steward.id])
    s.turn = 2
    s.player_text = "Please, steward, let us into the vault; the baron sent us here"
    return s


def check(state, **over):
    call = {
        "character": "Kit", "skill": "Persuasion", "target": "Steward Hale", "quality": "ordinary", "modifier": 3,
        "spoken": "let us into the vault; the baron sent us here", "dc": 15, "failure": "the steward calls the guard",
        "narration": "Kit meets the steward's eye and speaks.", **over,
    }  # fmt: skip
    return dispatch("social_check", "t1", call, state)


def fix(monkeypatch, n):
    monkeypatch.setattr(d20, "roll", lambda expr, **kw: REAL(str(n)))


def test_a_failed_social_check_closes_and_records(monkeypatch):
    s = make()
    fix(monkeypatch, 9)
    out = check(s)
    a = s.world.attempts["a001"]
    assert (a.kind, a.who, a.status, a.about) == ("social", "Kit", "closed", s.world.find("Steward Hale").id)
    assert a.task == "use persuasion on Steward Hale" and "10 minutes pass" in out.content
    assert "shut to Kit" in out.content
    fact = s.world.facts[a.fact]
    assert fact.text == "Kit tried to use persuasion on Steward Hale and failed; the steward calls the guard"
    assert fact.aspect == "attempts" and fact.disclosure == "known"


def test_the_same_person_will_not_hear_it_again_until_something_changes(monkeypatch):
    s = make()
    fix(monkeypatch, 9)
    check(s)
    s.turn = 3
    s.player_text = "Please, steward, I beg you, let us into the vault; the baron sent us here"
    before = s.world.time
    out = check(s, spoken="I beg you, let us into the vault; the baron sent us here")
    assert out.content.startswith("No roll.") and out.event is None and s.world.time == before
    fix(monkeypatch, 22)
    s.turn = 4
    out = check(s, attempt={"changed": "she shows the baron's seal"}, spoken="let us into the vault; the baron sent us here")
    assert out.event is not None and "success" in out.content
    assert s.world.attempts["a001"].status == "resolved"


def test_a_success_leaves_nothing(monkeypatch):
    s = make()
    fix(monkeypatch, 22)
    out = check(s)
    assert "success by 7" in out.content and not s.world.attempts


def test_the_failure_clause_defaults_and_the_task_can_be_named(monkeypatch):
    s = make()
    fix(monkeypatch, 9)
    check(s, failure=None, attempt={"task": "win over the steward", "after_minutes": 120, "closes": True})
    a = s.world.attempts["a001"]
    assert a.task == "win over the steward" and a.failure == "Steward Hale was not moved"
    assert a.reopens_at == WorldTime(1, 8).plus_minutes(10 + 120)


def test_a_bad_attempt_extra_is_refused_before_rolling(monkeypatch):
    s = make()
    fix(monkeypatch, 22)
    out = check(s, attempt={"after_minutes": 0})
    assert out.is_error and "Nothing was rolled" in out.content and s.world.time == WorldTime(1, 8)
    assert (s.turn, s.world.find("Steward Hale").id) not in s.social_done  # a corrected call may try again


@pytest.mark.parametrize("ruleset", ["odnd", "basic", "becmi", "adnd1e", "adnd2e"])
def test_reaction_rulesets_say_which_totals_fail(ruleset, monkeypatch):
    assert rulesets.get(ruleset).reaction_fail == 5
    for other in rulesets.RULESETS:
        if other.social_style != "reaction":
            assert other.reaction_fail is None


@pytest.mark.parametrize("n, status", [(5, "closed"), (6, None)])
def test_a_reaction_roll_fails_at_or_below_the_rulesets_figure(n, status, monkeypatch):
    s = make("basic")
    fix(monkeypatch, n)
    out = check(s, dc=None, modifier=0)
    if status:
        assert s.world.attempts["a001"].status == status and "shut to Kit" in out.content
    else:
        assert not s.world.attempts


def test_pathfinder_degrees_decide_the_failure(monkeypatch):
    s = make("pf2e")
    fix(monkeypatch, 20)  # four under the DC of 15 + 3 modifier ... a plain failure
    check(s, dc=30)
    assert s.world.attempts["a001"].status == "closed"
    s2 = make("pf2e")
    fix(monkeypatch, 20)
    check(s2, dc=15)
    assert not s2.world.attempts
