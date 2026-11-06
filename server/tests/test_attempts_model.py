"""The record of failed attempts (docs/ATTEMPTS.md 3, 4): the type table, the model, saving and the aspect."""

import pytest

from aigm import attempts
from aigm.session.state import GameState, Phase
from aigm.world import World, WorldError, WorldTime
from aigm.world.model import ASPECTS


@pytest.fixture
def w():
    world = World()
    world.vault = world.add_entity("Vault door", "concept")
    world.cellar = world.add_entity("Cellar", "location")
    return world


def test_every_type_has_a_policy_and_time_and_a_way_back():
    assert set(attempts.TYPES) == {
        "lock", "trap", "force", "climb", "repair", "treat", "search", "lore", "appraise", "sneak", "social",
        "inquire", "other",
    }  # fmt: skip
    for t in attempts.TYPES.values():
        assert t.policy in attempts.POLICIES and t.minutes >= 1 and t.reopens_if
    assert {k for k, t in attempts.TYPES.items() if t.policy == "costly"} == {
        "lock", "trap", "force", "climb", "repair", "treat",
    }
    assert attempts.type_of("social").policy == "once" and attempts.type_of("nonsense") is None


def test_add_find_and_count_tries(w):
    a = w.add_attempt("Kit", "lock", "pick the vault lock", w.vault.id, failure="a pick snaps", turn=4)
    assert a.id == "a001" and a.status == "open" and a.tries == 1 and a.at == w.time
    assert w.find_attempt("kit", "lock", w.vault.id) is a  # the name is matched like any name
    assert w.find_attempt("Mira", "lock", w.vault.id) is None  # another character's
    assert w.find_attempt("Kit", "search", w.vault.id) is None
    assert w.find_attempt("Kit", "lock", w.cellar.id) is None
    w.retry_attempt(a.id, failure="the lock jams", turn=5)
    assert (a.tries, a.failure, a.turn) == (2, "the lock jams", 5)


def test_a_closure_to_everyone_applies_to_every_character(w):
    a = w.add_attempt("Kit", "lock", "pick the vault lock", w.vault.id, status="closed", scope="anyone")
    assert w.find_attempt("Mira", "lock", w.vault.id) is a


def test_a_resolved_attempt_is_no_longer_found(w):
    a = w.add_attempt("Kit", "lock", "pick the vault lock", w.vault.id)
    w.set_attempt_status(a.id, "resolved")
    assert w.find_attempt("Kit", "lock", w.vault.id) is None
    assert w.attempts_about([w.vault.id]) == []
    assert w.attempts_about([w.vault.id], unresolved_only=False) == [a]


def test_a_closed_attempt_reopens_when_its_clock_runs_out(w):
    w.set_time(WorldTime(1, 9))
    a = w.add_attempt("Kit", "social", "persuade the steward", w.vault.id, status="closed")
    w.set_attempt_status(a.id, "closed", reopens_if="New facts.", reopens_at=WorldTime(2, 9))
    assert w.find_attempt("Kit", "social", w.vault.id).status == "closed"
    w.set_time(WorldTime(2, 9))
    assert w.find_attempt("Kit", "social", w.vault.id).status == "open"
    assert a.reopens_at is None and a.reopens_if == "New facts."


def test_attempts_are_checked(w):
    ok = dict(about=w.vault.id)
    for bad in (
        dict(who="", kind="lock", task="pick the lock", **ok),
        dict(who="Kit", kind="juggle", task="pick the lock", **ok),
        dict(who="Kit", kind="lock", task="x", **ok),
        dict(who="Kit", kind="lock", task="pick the lock", about="e999"),
        dict(who="Kit", kind="lock", task="pick the lock", status="resolved", **ok),
        dict(who="Kit", kind="lock", task="pick the lock", scope="party", **ok),
        dict(who="Kit", kind="lock", task="pick the lock", failure="x" * 300, **ok),
    ):
        with pytest.raises(WorldError):
            w.add_attempt(**bad)
    assert not w.attempts


def test_attempts_are_saved_and_old_saves_have_none(w):
    a = w.add_attempt("Kit", "lock", "pick the vault lock", w.vault.id, status="closed", failure="a pick snaps")
    w.set_attempt_status(a.id, "closed", reopens_if="Better picks.", reopens_at=WorldTime(3, 6, 30))
    again = World.from_dict(w.to_dict())
    assert again == w and again.attempts["a001"].reopens_at == WorldTime(3, 6, 30)
    assert again.add_attempt("Mira", "climb", "climb the cliff", again.cellar.id if hasattr(again, "cellar") else "e002").id == "a002"
    data = w.to_dict()
    del data["attempts"]
    del data["next_id"]["a"]
    assert World.from_dict(data).attempts == {}
    data = w.to_dict()
    data["attempts"][0]["about"] = "e999"
    from aigm.errors import CorruptSave

    with pytest.raises(CorruptSave):
        World.from_dict(data)


def test_the_attempts_aspect_is_valid_for_every_kind_but_not_a_checklist_slot(w):
    for name, kind in (("Kit", "npc"), ("Guild", "faction"), ("Sluice Key", "item")):
        ent = w.add_entity(name, kind)
        fact = w.add_fact(f"{name} was tried.", [ent.id], aspect="attempts", disclosure="known", source="play")
        assert fact.aspect == "attempts"
    w.add_fact("The cellar was tried.", [w.cellar.id], aspect="attempts", disclosure="known", source="play")
    assert all("attempts" not in slots for slots in ASPECTS.values())  # the curator never fills it
    with pytest.raises(WorldError):
        w.add_fact("Bad.", [w.cellar.id], aspect="nonsense")


def test_the_state_keeps_attempts_through_a_copy_and_a_save():
    state = GameState(Phase.ADVENTURE, {"setting": "x"})
    ent = state.world.add_entity("Vault door", "concept")
    state.world.add_attempt("Kit", "lock", "pick the vault lock", ent.id)
    assert state.copy().world.attempts.keys() == {"a001"}
    assert GameState.from_dict(state.to_dict()).world.attempts.keys() == {"a001"}
