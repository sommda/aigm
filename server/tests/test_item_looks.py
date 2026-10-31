"""The Look of a key item: validation, who is describable, what the model is shown and the sweep (docs/KEY_ITEMS.md 7)."""

import json

import pytest

from aigm.compendium import Compendium, detail, entries
from aigm.looks import ITEM, Look, frame_of, problems
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.tools import dispatch
from aigm.world import World
from aigm.world.curator import CuratorError, ItemLookRequest
from aigm.world.describe_items import _subject, describable, needing_items, run_item_looks, too_alike
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import LOOK_RETRY_TURNS, CuratorService

BODY = (
    "{name} is a heavy brass key as long as a hand, its bow cast in the shape of a bird's head with a small round "
    "eye. The shaft is smooth and slightly bent from use, and the bit has three square teeth of unequal length. Green "
    "tarnish gathers in the grooves of the feathers while the edges of the bow are polished bright by many thumbs. A "
    "loop of frayed grey cord is knotted through the bird's beak. Near the bit a tiny stamped mark, a circle with a "
    "line through it, shows the maker. The whole key looks old but carefully kept, and rests alone on a plain surface."
)


def make_item_look(name="Sluice Key", **over) -> Look:
    look = Look(
        "A heavy brass key with a bird's head bow and three square teeth.",
        BODY.format(name=name),
        {"form": "key", "frame": "square", "size": "small", "material": "tarnished brass", "condition": "worn smooth",
         "markings": "a stamped circle with a line", "features": ["bird's head bow", "frayed grey cord"]},
    )  # fmt: skip
    for key, value in over.items():
        setattr(look, key, value)
    return look


def shelf():
    """A held key, a held ledger, a key the party only knows of, and one it has not heard of."""
    w = World()
    town = w.add_entity("Ashby", "location")
    ids = {}
    for name in ("Sluice Key", "Steward's Ledger", "Chest Key", "Secret Seal"):
        item = w.add_entity(name, "item")
        ids[name] = item.id
        w.add_fact(f"{name} is a plain old thing.", [item.id], aspect="appearance")
        w.add_fact(f"SECRET: {name} is cursed.", [item.id], aspect="secret")
    w.add_fact("The ledger proves the steward sold the grain.", [ids["Steward's Ledger"]], aspect="purpose")
    w.set_holding(ids["Sluice Key"], "acquired", "Taken from the gatehouse.", turn=3)
    w.set_holding(ids["Steward's Ledger"], "acquired", "Found.", turn=5)
    w.set_holding(ids["Chest Key"], "learned", turn=2)
    ids["Ashby"] = town.id
    return w, ids


# ---- the Look of an item -----------------------------------------------------------------


def test_a_good_item_look_has_no_problems():
    assert problems(make_item_look(), "Sluice Key", ITEM) == []
    assert problems(make_item_look(), "Sluice Key") != []  # a person's rules do not fit


def test_the_frame_is_optional_and_read_as_square_when_missing_or_unknown():
    look = make_item_look()
    del look.tags["frame"]
    assert problems(look, "Sluice Key", ITEM) == [] and frame_of(look) == "square"
    look.tags["frame"] = "wide"
    assert problems(look, "Sluice Key", ITEM) == [] and frame_of(look) == "square"
    look.tags["frame"] = "landscape"
    assert frame_of(look) == "landscape"


@pytest.mark.parametrize(
    "tags, fragment",
    [({"form": "sword"}, "tag 'form'"), ({"size": "huge"}, "tag 'size'"), ({"flavor": "x"}, "unknown tags")],
)
def test_bad_tags_are_reported(tags, fragment):
    look = make_item_look()
    look.tags.update(tags)
    assert any(fragment in p for p in problems(look, "Sluice Key", ITEM))


def test_the_description_may_be_shorter_than_a_persons_and_must_use_the_name():
    short = make_item_look(description="Sluice Key is a brass key with a bird's head bow, worn smooth by hands. " * 4)
    assert problems(short, "Sluice Key", ITEM) == []
    assert any("must have 60 to 140" in p for p in problems(make_item_look(description="Sluice Key is brass."), "Sluice Key", ITEM))
    assert any("name" in p for p in problems(make_item_look(description=BODY.format(name="The thing")), "Sluice Key", ITEM))
    loose = make_item_look(description=BODY.format(name="The sluice gate key"))
    assert problems(loose, "Sluice Key", ITEM) == []  # all of the name's words, in any order


def test_game_words_and_the_party_are_refused():
    assert any("the party" in p for p in problems(make_item_look(summary="Found by the party, a brass key."), "Sluice Key", ITEM))


def test_a_look_can_be_set_on_an_item_but_not_on_a_faction():
    w, ids = shelf()
    w.set_look(ids["Sluice Key"], make_item_look())
    assert w.entities[ids["Sluice Key"]].look.tags["form"] == "key"
    again = World.from_dict(json.loads(json.dumps(w.to_dict())))
    assert again.entities[ids["Sluice Key"]].look == make_item_look()


def test_two_alike_items_are_told_apart():
    a, b = make_item_look(), make_item_look("Chest Key")
    assert too_alike(a, b)
    b.tags.update(material="black iron")
    b.summary = "A squat black iron key with a plain ring bow."
    assert not too_alike(a, b)


# ---- who is describable and what the model sees -------------------------------------------


def test_only_items_the_party_has_had_are_describable_newest_first():
    w, ids = shelf()
    assert needing_items(w) == ["Steward's Ledger", "Sluice Key"]  # acquired later first
    assert not describable(w.entities[ids["Chest Key"]]) and not describable(w.entities[ids["Secret Seal"]])
    w.set_holding(ids["Sluice Key"], "lost", turn=8)  # lost items are still described
    assert describable(w.entities[ids["Sluice Key"]])
    assert needing_items(w, "The Sluice Key gleamed.")[0] == "Sluice Key"  # named in the last narration first


def test_the_model_sees_known_facts_and_how_it_was_found_and_nothing_secret():
    w, ids = shelf()
    sub = _subject(w, "Steward's Ledger", "The Steward's Ledger sat open. It was heavy.")
    text = " ".join(sub.facts)
    assert "plain old thing" in text and "proves the steward" in text
    assert "SECRET" not in text and "cursed" not in text and "The party has" not in text
    assert sub.found == "Found." and sub.narration and "Steward's Ledger" in sub.narration[0]


def test_a_hidden_fact_added_after_acquiring_stays_hidden_from_the_model():
    w, ids = shelf()
    w.add_fact("The ledger's page nine is forged.", [ids["Steward's Ledger"]], aspect="contents")
    assert "forged" not in " ".join(_subject(w, "Steward's Ledger", "").facts)


# ---- the sweep ---------------------------------------------------------------------------


class Recording(ScriptedCurator):
    def __init__(self):
        super().__init__()
        self.requests: list[ItemLookRequest] = []

    async def item_look(self, request):
        self.requests.append(request)
        return await super().item_look(request)


async def sweep(world, curator=None, **kw):
    return await run_item_looks(world, {"setting": "A cold north."}, "D&D 5.5e", curator or ScriptedCurator(), **kw)


async def test_the_sweep_describes_acquired_items_only_and_sets_a_frame():
    w, ids = shelf()
    cur = Recording()
    result = await sweep(w, cur)
    assert sorted(op.entity for op in result.ops) == ["Sluice Key", "Steward's Ledger"]
    assert all(op.look.tags["frame"] in ("square", "landscape", "portrait") and op.look.state == "provisional" for op in result.ops)
    asked = [s.name for r in cur.requests for s in r.subjects]
    assert "Chest Key" not in asked and "Secret Seal" not in asked  # never shown to the model


async def test_the_scripted_items_pass_the_rules_and_differ():
    w, _ = shelf()
    looks = [op.look for op in (await sweep(w)).ops]
    assert all(problems(lk, name, ITEM) == [] for lk, name in zip(looks, ("Steward's Ledger", "Sluice Key")))
    assert not too_alike(*looks)


async def test_a_rejected_answer_is_retried_once_with_the_reasons():
    class BadFirst(Recording):
        async def item_look(self, request):
            look = await super().item_look(request)
            if len(self.requests) == 1:
                look[0].tags["form"] = "sword"
            return look

    w, _ = shelf()
    cur = BadFirst()
    result = await sweep(w, cur)
    assert len(result.ops) == 2 and len(cur.requests) == 2
    assert any("tag 'form'" in line for lines in cur.requests[1].feedback.values() for line in lines)


async def test_a_batch_the_model_cannot_answer_is_split_in_two():
    class Big(Recording):
        async def item_look(self, request):
            if len(request.subjects) > 1:
                raise CuratorError("stopped with max_tokens")
            return await super().item_look(request)

    w, _ = shelf()
    result = await sweep(w, Big())
    assert len(result.ops) == 2 and any("trying two smaller" in n for n in result.notes)


async def test_a_curator_that_cannot_describe_items_changes_nothing():
    class Plain(ScriptedCurator):
        item_look = None  # type: ignore[assignment]

    w, _ = shelf()
    assert (await sweep(w, Plain())).ops == []


# ---- the service -------------------------------------------------------------------------


def adventure(turn=3):
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, {"setting": "A cold north.", "party": [{"name": "Toby Reed", "sheet": "Rogue."}]})
    session.state.world, _ = shelf()
    session.state.turn = turn
    session.messages = [{"role": "assistant", "content": [{"type": "text", "text": "You pocket the Sluice Key."}]}]
    return session


async def test_the_service_describes_items_after_a_turn_and_then_goes_quiet():
    session, svc = adventure(), CuratorService(ScriptedCurator())
    assert svc.item_looks_due(session) and await svc.run_item_looks_if_due(session)
    world = session.state.world
    assert world.find("Sluice Key").look is not None and world.find("Steward's Ledger").look is not None
    assert world.find("Chest Key").look is None and world.find("Secret Seal").look is None
    assert not svc.item_looks_due(session) and not await svc.run_item_looks_if_due(session)


async def test_a_failing_sweep_backs_off_and_a_replaced_game_drops_the_result():
    class Down(ScriptedCurator):
        async def item_look(self, request):
            raise RuntimeError("down")

    session, svc = adventure(turn=5), CuratorService(Down())
    assert not await svc.run_item_looks_if_due(session)
    assert session.item_looks_retry_turn == 5 + LOOK_RETRY_TURNS and not svc.item_looks_due(session)

    other = adventure()

    class Replacing(ScriptedCurator):
        async def item_look(self, request):
            other.reset_world_work()
            return await super().item_look(request)

    assert not await CuratorService(Replacing()).run_item_looks_if_due(other)
    assert other.state.world.find("Sluice Key").look is None


def test_not_due_in_session_zero_or_while_busy():
    svc = CuratorService(ScriptedCurator())
    assert not svc.item_looks_due(Session("z"))
    for attr in ("busy", "curating"):
        session = adventure()
        setattr(session, attr, True)
        assert not svc.item_looks_due(session)


# ---- what the player and the GM see -------------------------------------------------------


def test_the_look_shows_in_the_entry_and_the_gm_briefing_but_not_for_an_item_still_sought():
    w, ids = shelf()
    w.set_look(ids["Sluice Key"], make_item_look())
    page = detail(w, Compendium(), ids["Sluice Key"])
    assert page["look"]["summary"].startswith("A heavy brass key")
    assert detail(w, Compendium(), ids["Chest Key"])["look"] is None
    from aigm.world.briefing import build_briefing

    assert "Sluice Key: A heavy brass key with a bird's head bow" in build_briefing(w)
    assert all(r["summary"] for r in entries(w, Compendium(), "items"))


def test_establish_look_notes_do_not_make_a_known_item_describable():
    s = GameState(Phase.ADVENTURE, {"setting": "x"})
    dispatch("establish", "t", {"entities": [{"name": "Gate Key", "kind": "item", "look_notes": "a rusty key"}]}, s)
    dispatch("key_item", "t", {"events": [{"name": "Gate Key", "event": "learned"}]}, s)
    assert needing_items(s.world) == []
    dispatch("key_item", "t", {"events": [{"name": "Gate Key", "event": "acquired"}]}, s)
    assert needing_items(s.world) == ["Gate Key"]
