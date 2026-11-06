"""The `attempt` of a roll (docs/ATTEMPTS.md 6): checked before the dice, recorded after them."""

import d20
import pytest

from aigm.session.state import GameState, Phase
from aigm.tools import dispatch
from aigm.world import Block, World, WorldTime

REAL = d20.roll


@pytest.fixture
def state(monkeypatch):
    s = GameState(Phase.ADVENTURE, {"setting": "x", "party": [{"name": "Kit"}, {"name": "Mira"}], "party_size": 2, "level": 1})
    w = s.world
    hall = w.add_entity("Great hall", "location")
    cellar = w.add_entity("Cellar", "location")
    w.add_entity("Vault door", "concept")
    w.set_scene(hall.id, [])
    w.set_route(hall.id, cellar.id, 3, "the stair", block=Block("locked", "A rusted gate bars the stair.", "the key"))
    s.turn = 3
    return s


def total(monkeypatch, n):
    monkeypatch.setattr(d20, "roll", lambda expr, **kw: REAL(str(n)))


def attempt(**over):
    base = dict(who="Kit", kind="lock", task="pick the vault lock", about="Vault door", failure="a pick snaps")
    return {**base, **over}


def roll(state, dc=18, **over):
    attempt_arg = over.pop("attempt", attempt())
    call = {"expression": "1d20+5 # lockpicking", "narration": "Kit kneels at the vault lock.", "dc": dc, "attempt": attempt_arg, **over}
    return dispatch("roll_dice", "t1", call, state)


def facts(state):
    return [f.text for f in state.world.facts.values() if f.aspect == "attempts" and f.active]


def test_a_failed_costly_attempt_stays_open_and_is_recorded(state, monkeypatch):
    total(monkeypatch, 12)
    out = roll(state)
    assert not out.is_error and "Failure by 6" in out.content and "can be tried again" in out.content
    a = state.world.attempts["a001"]
    assert (a.status, a.tries, a.who, a.kind, a.about) == ("open", 1, "Kit", "lock", "e003")
    assert facts(state) == ["Kit tried to pick the vault lock and failed; a pick snaps"]
    assert "10 minutes pass" in out.content and state.world.time == WorldTime(1, 8, 10)  # the type's default minutes
    assert state.world.facts[a.fact].disclosure == "known"


def test_a_retry_counts_the_tries_and_replaces_the_fact(state, monkeypatch):
    total(monkeypatch, 12)
    roll(state)
    out = roll(state, attempt=attempt(failure="the lock jams"))
    a = state.world.attempts["a001"]
    assert len(state.world.attempts) == 1 and a.tries == 2 and a.failure == "the lock jams"
    assert facts(state) == ["Kit tried to pick the vault lock twice and failed; the lock jams"]
    assert "2 tries" in out.content


def test_success_after_failures_resolves_the_chain(state, monkeypatch):
    total(monkeypatch, 12)
    roll(state)
    roll(state)
    total(monkeypatch, 22)
    out = roll(state)
    a = state.world.attempts["a001"]
    assert a.status == "resolved" and "third try" in out.content
    assert facts(state) == ["Kit managed to pick the vault lock on the third try."]
    assert state.world.find_attempt("Kit", "lock", a.about) is None


def test_a_success_with_no_chain_records_nothing(state, monkeypatch):
    total(monkeypatch, 22)
    out = roll(state)
    assert "Success by 4" in out.content and not state.world.attempts and not facts(state)


def test_a_failed_once_attempt_is_closed_and_refuses_a_second_roll(state, monkeypatch):
    total(monkeypatch, 5)
    kw = dict(attempt=attempt(kind="search", task="search the vault room", failure="nothing but dust"))
    out = roll(state, **kw)
    a = state.world.attempts["a001"]
    assert a.status == "closed" and "shut to Kit" in out.content and "place.." not in out.content
    assert a.reopens_if.startswith("A new method")  # the type's default way back
    before = (state.world.time, len(state.world.facts))
    again = roll(state, **kw)
    assert not again.is_error and again.content.startswith("No roll.") and again.event is None
    assert again.say == "Kit kneels at the vault lock."
    assert (state.world.time, len(state.world.facts)) == before  # no time, no fact
    assert state.world.attempts["a001"].tries == 1


def test_a_changed_approach_reopens_a_closed_attempt_and_rolls(state, monkeypatch):
    total(monkeypatch, 5)
    kw = dict(attempt=attempt(kind="search", task="search the vault room", failure="nothing but dust"))
    roll(state, **kw)
    kw["attempt"] = {**kw["attempt"], "changed": "a lantern and a pry bar"}
    total(monkeypatch, 25)
    out = roll(state, **kw)
    assert out.event is not None and "Success" in out.content
    assert state.world.attempts["a001"].status == "resolved"


def test_another_character_may_try_unless_it_was_closed_to_everyone(state, monkeypatch):
    total(monkeypatch, 5)
    roll(state, attempt=attempt(kind="search", task="search the vault room"))
    assert roll(state, attempt=attempt(who="Mira", kind="search", task="search the vault room")).event is not None
    roll(state, attempt=attempt(kind="climb", task="climb the vault wall", scope="anyone", closes=True))
    assert roll(state, attempt=attempt(who="Mira", kind="climb", task="climb the vault wall")).content.startswith("No roll.")


def test_the_gm_can_close_a_costly_attempt_and_set_a_clock(state, monkeypatch):
    total(monkeypatch, 5)
    out = roll(state, attempt=attempt(closes=True, reopens_if="the key", after_minutes=60))
    a = state.world.attempts["a001"]
    assert a.status == "closed" and a.reopens_if == "the key" and "shut to Kit" in out.content
    assert a.reopens_at == state.world.time.plus_minutes(60)
    state.world.set_time(a.reopens_at)
    assert state.world.find_attempt("Kit", "lock", a.about).status == "open"


def test_the_gm_can_keep_a_once_attempt_open(state, monkeypatch):
    total(monkeypatch, 5)
    roll(state, attempt=attempt(kind="lore", task="recall the old legend", closes=False))
    assert state.world.attempts["a001"].status == "open"


def test_minutes_are_the_rolls_or_the_types_but_never_nothing(state, monkeypatch):
    total(monkeypatch, 22)
    roll(state)
    assert state.world.time == WorldTime(1, 8, 10)
    roll(state, minutes=45)
    assert state.world.time == WorldTime(1, 8, 55)
    roll(state, minutes=0)
    assert state.world.time == WorldTime(1, 8, 56)


def test_a_success_opens_the_blocked_way_and_a_failure_does_not(state, monkeypatch):
    hall = state.world.find("Great hall").id
    cellar = state.world.find("Cellar").id
    opens = {"from": "Great hall", "to": "Cellar"}
    total(monkeypatch, 5)
    out = roll(state, attempt=attempt(about="Cellar", opens=opens, task="force the rusted gate", kind="force"))
    assert state.world.find_route(hall, cellar, "the stair").block is not None
    assert state.world.attempts["a001"].about == cellar and "can be tried again" in out.content
    total(monkeypatch, 25)
    out = roll(state, attempt=attempt(about="Cellar", opens=opens, task="force the rusted gate", kind="force"))
    assert state.world.find_route(hall, cellar, "the stair").block is None and "no longer blocked" in out.content


def test_opens_by_the_words_of_a_way_out_of_here(state, monkeypatch):
    total(monkeypatch, 25)
    roll(state, attempt=attempt(kind="force", task="force the rusted gate", opens="the stair"))
    assert state.world.find_route(state.world.find("Great hall").id, state.world.find("Cellar").id, "the stair").block is None
    out = roll(state, attempt=attempt(kind="force", task="force the rusted gate", opens="the stair"))
    assert out.is_error and "not blocked" in out.content


@pytest.mark.parametrize(
    "bad, word",
    [
        (dict(who="Nobody"), "party member"),
        (dict(kind="juggle"), "kind"),
        (dict(kind="social"), "social_check"),
        (dict(task="x"), "`task`"),
        (dict(failure=""), "`failure`"),
        (dict(failure="word " * 30), "`failure`"),
        (dict(about="The moon"), "not recorded"),
        (dict(scope="party"), "`scope`"),
        (dict(after_minutes=0), "after_minutes"),
        (dict(closes="yes"), "`closes`"),
        (dict(opens="the sky"), "no recorded way"),
    ],
)
def test_a_bad_attempt_is_refused_before_the_dice(state, monkeypatch, bad, word):
    total(monkeypatch, 22)
    out = roll(state, attempt=attempt(**bad))
    assert out.is_error and out.event is None and "Nothing was rolled" in out.content and word in out.content
    assert state.world.time == WorldTime(1, 8) and not state.world.attempts


def test_an_attempt_needs_a_dc(state):
    out = dispatch("roll_dice", "t1", {"expression": "1d20", "narration": "Kit works the lock.", "attempt": attempt()}, state)
    assert out.is_error and "needs a `dc`" in out.content


def test_the_attempt_defaults_to_the_place_the_party_is_in(state, monkeypatch):
    total(monkeypatch, 5)
    a = attempt()
    del a["about"]
    roll(state, attempt=a)
    assert state.world.attempts["a001"].about == state.world.find("Great hall").id


def test_session_zero_ignores_the_attempt():
    s = GameState(Phase.SESSION_ZERO)
    out = dispatch("roll_dice", "t1", {"expression": "1d20", "narration": "Kit works the lock.", "attempt": attempt()}, s)
    assert not out.is_error and out.event is not None and not s.world.attempts


def test_a_long_failure_still_fits_a_fact(state, monkeypatch):
    total(monkeypatch, 5)
    long = " ".join(f"w{i}" for i in range(25))
    roll(state, attempt=attempt(task="pick the vault lock with a long hairpin carefully slowly", failure=long))
    assert facts(state) and all(len(t.split()) <= 40 for t in facts(state))


# ---- rolls that look like tasks ----------------------------------------------------------------------------


def _bare(state, comment, **over):
    call = {"expression": f"1d20+5 # {comment}", "narration": "Kit studies the wall closely.", "dc": 15, **over}
    return dispatch("roll_dice", "t1", call, state)


@pytest.mark.parametrize("label", ["Kit, Perception on the wall", "lockpicking", "Kit, Thieves' Tools", "Mira, Medicine", "Kit, Stealth"])
def test_a_dc_roll_labelled_as_a_task_needs_its_attempt(state, monkeypatch, label):
    total(monkeypatch, 5)
    out = _bare(state, label)
    assert out.is_error and out.event is None and "has no `attempt`" in out.content
    assert state.world.time == WorldTime(1, 8) and not state.world.attempts


@pytest.mark.parametrize("label", ["Kit, attack roll", "Kit, Dex saving throw", "Kit, Athletics grapple", "initiative", "damage"])
def test_fights_and_saves_are_not_tasks(state, monkeypatch, label):
    total(monkeypatch, 5)
    out = _bare(state, label)
    assert not out.is_error and out.event is not None


def test_a_task_label_without_a_dc_or_with_an_attempt_is_fine(state, monkeypatch):
    total(monkeypatch, 5)
    assert not _bare(state, "Kit, Perception on the wall", dc=None).is_error
    assert not _bare(state, "lockpicking", attempt=attempt()).is_error


def test_session_zero_never_demands_an_attempt():
    s = GameState(Phase.SESSION_ZERO)
    out = dispatch("roll_dice", "t1", {"expression": "1d20 # Perception", "narration": "Kit looks around.", "dc": 12}, s)
    assert not out.is_error
