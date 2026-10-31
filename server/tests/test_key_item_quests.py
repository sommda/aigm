"""Quests and key items (docs/KEY_ITEMS.md 6): find-the-item quests, quests an item opens, and the award."""

import json
from dataclasses import replace

import pytest

from aigm import story as st
from aigm.errors import CorruptSave
from aigm.session.state import GameState, Phase
from aigm.story import Milestone, Story
from aigm.tools import dispatch
from aigm.world import World
from aigm.world.briefing import build_briefing
from aigm.world.curator import EntityProposal, FactProposal, PlotProposal, PlotRequest, QuestProposal
from aigm.world.plot import run_chapter_plot, run_plot
from aigm.world.scripted import ScriptedCurator
from tests.test_plot import CAMPAIGN, world as plot_world
from tests.test_story import endings, ms, short_story


def vault():
    """A town, a vault where the ledger lies, and two items: a ledger (hidden whereabouts) and a key (none)."""
    w = World()
    town = w.add_entity("Ashby", "location")
    ledger = w.add_entity("Steward's Ledger", "item")
    key = w.add_entity("Sluice Key", "item")
    w.add_fact("The ledger lies in the steward's vault.", [ledger.id, town.id], aspect="whereabouts")
    w.add_fact("The ledger is a thick green-bound book.", [ledger.id], aspect="appearance")
    w.add_fact("The key is a heavy brass key.", [key.id], aspect="appearance")
    w.set_scene(town.id, [])
    return w, {"town": town.id, "ledger": ledger.id, "key": key.id}


# ---- the plan holds items ----------------------------------------------------------------


def test_finds_and_needs_are_saved_and_an_older_plan_loads():
    story = short_story()
    story.milestones[0].finds, story.milestones[1].needs = "e002", ["e002", "e003"]
    again = Story.from_dict(json.loads(json.dumps(story.to_dict())))
    assert again.milestones[0].finds == "e002" and again.milestones[1].needs == ["e002", "e003"]
    old = story.to_dict()
    for m in old["milestones"]:
        del m["finds"], m["needs"]
    loaded = Story.from_dict(old)
    assert loaded.milestones[0].finds is None and loaded.milestones[0].needs == []
    with pytest.raises(CorruptSave):  # a malformed one is refused
        Story.from_dict({**old, "milestones": [{**old["milestones"][0], "finds": 7}]})


# ---- a quest that needs an item ------------------------------------------------------------


def test_a_quest_waits_for_the_item_and_opens_when_the_party_has_had_it():
    w, ids = vault()
    story = short_story()
    story.milestones[2].needs = [ids["ledger"]]  # the side quest
    story.milestones[2].status = "pending"
    assert st.settle_ready(story, w) == [] and story.milestone("side").status == "pending"
    w.set_holding(ids["ledger"], "acquired", turn=4)
    assert st.settle_ready(story, w) == ["side"]


def test_a_spent_or_lost_item_does_not_take_the_quest_away_and_a_known_one_does_not_open_it():
    w, ids = vault()
    story = short_story()
    story.milestones[2].needs, story.milestones[2].status = [ids["ledger"]], "pending"
    w.set_holding(ids["ledger"], "learned", turn=2)
    assert st.settle_ready(story, w) == []  # heard of is not had
    w.set_holding(ids["ledger"], "acquired", turn=3)
    w.set_holding(ids["ledger"], "lost", turn=4)
    assert st.settle_ready(story, w) == ["side"]


def test_without_a_world_a_gated_quest_stays_pending():
    story = short_story()
    story.milestones[2].needs, story.milestones[2].status = ["e002"], "pending"
    assert st.settle_ready(story) == [] and st.items_in_hand(None, [])


def test_an_item_got_in_one_chapter_opens_a_quest_of_the_next_when_it_begins():
    w, ids = vault()
    story = short_story()
    story.milestones[3].needs, story.milestones[3].status = [ids["key"]], "pending"
    story.goal.revealed = True
    for m in ("m1", "m2", "side"):
        st.report(story, m, "done", "Done.", 5, w)
    assert story.chapter == 2 and story.milestone("m3").status == "pending"  # the chapter began; the key is not had yet
    w.set_holding(ids["key"], "acquired", turn=6)
    assert st.settle_ready(story, w) == ["m3"]


# ---- checking the plan -----------------------------------------------------------------------


def checked(story, world=None):
    return st.validate_plan(story, world)


def test_a_plan_naming_things_that_are_not_key_items_is_refused():
    w, ids = vault()
    story = short_story()
    story.milestones[0].finds = ids["town"]  # a place
    story.milestones[1].needs = ["e999"]
    found = " ".join(checked(story, w))
    assert f"names {ids['town']}, which is not a key item" in found and "e999" in found


def test_a_quest_cannot_find_and_need_the_same_item():
    w, ids = vault()
    story = short_story()
    story.milestones[0].finds = story.milestones[0].needs[:] or ids["ledger"]
    story.milestones[0].needs = [ids["ledger"]]
    assert any("both finds and needs" in p for p in checked(story, w))


def test_an_item_a_quest_needs_must_be_obtainable():
    w, ids = vault()
    story = short_story()
    story.milestones[1].needs = [ids["key"]]  # no finder, no whereabouts
    assert any("no quest finds it and the world does not say where" in p for p in checked(story, w))
    story.milestones[0].finds = ids["key"]  # now a quest finds it
    assert not any("does not say where" in p for p in checked(story, w))
    story.milestones[0].finds = None
    story.milestones[1].needs = [ids["ledger"]]  # the world says where
    assert not any("does not say where" in p for p in checked(story, w))


def test_a_quest_cannot_wait_for_an_item_only_a_quest_that_waits_for_it_can_give():
    w, ids = vault()
    story = short_story()
    story.milestones[0].needs = [ids["key"]]  # m1 needs the key ...
    story.milestones[1].finds = ids["key"]  # ... which only m2 finds, and m2 requires m1
    assert any("can never become available" in p for p in checked(story, w))


def test_a_quest_cannot_need_an_item_a_later_chapter_finds():
    w, ids = vault()
    story = short_story()
    story.milestones[0].needs = [ids["key"]]
    story.milestones[3].finds = ids["key"]  # m3, chapter 2
    assert any("in chapter 2, finds" in p for p in checked(story, w))


def test_a_good_item_plan_passes():
    w, ids = vault()
    story = short_story()
    story.milestones[0].finds = ids["ledger"]
    story.milestones[1].needs = [ids["ledger"]]
    assert not [p for p in checked(story, w) if "item" in p or "never become" in p]


# ---- what the GM is told --------------------------------------------------------------------


def test_the_story_notes_show_the_item_a_quest_is_about_and_the_ones_waiting_for_an_item():
    w, ids = vault()
    story = short_story()
    story.milestones[0].finds = ids["ledger"]
    story.milestones[2].needs, story.milestones[2].status = [ids["key"]], "pending"
    text = st.briefing_block(story, w, 3)
    assert "Finding: Steward's Ledger (the party has not heard of it yet" in text and "call key_item `learned`" in text
    assert "[side] Quest side is not offered until the party has Sluice Key" in text
    w.set_holding(ids["ledger"], "learned", turn=2)
    assert "knows of it and is looking for it" in st.briefing_block(story, w, 3)
    w.set_holding(ids["ledger"], "acquired", turn=3)
    assert "(the party has it)" in st.briefing_block(story, w, 3)
    w.set_holding(ids["key"], "acquired", turn=3)
    assert "is not offered" not in st.briefing_block(story, w, 3)


# ---- the key_item tool ---------------------------------------------------------------------


def adventure(story=None):
    s = GameState(Phase.ADVENTURE, {"setting": "x"})
    s.world, ids = vault()
    s.story, s.turn = story, 5
    return s, ids


def test_getting_a_find_the_item_item_completes_the_quest_and_the_quests_award_covers_it():
    story = short_story()
    story.milestones[0].finds = None
    s, ids = adventure(story)
    story.milestones[1].finds = ids["ledger"]
    st.report(story, "m1", "done", "Done.", 2, s.world)  # m2 is now active
    out = dispatch("key_item", "t", {"events": [{"name": "Steward's Ledger", "event": "acquired"}]}, s)
    assert not out.is_error
    assert "completes the quest [m2] Quest m2" in out.content and "not a second one" in out.content
    assert "should usually earn an award" not in out.content


def test_getting_any_other_item_says_an_award_is_due_and_a_second_getting_does_not():
    s, ids = adventure()
    out = dispatch("key_item", "t", {"events": [{"name": "Sluice Key", "event": "acquired"}]}, s)
    assert "should usually earn an award" in out.content and "`award`" in out.content
    dispatch("key_item", "t", {"events": [{"name": "Sluice Key", "event": "lost"}]}, s)
    again = dispatch("key_item", "t", {"events": [{"name": "Sluice Key", "event": "acquired"}]}, s)
    assert "award" not in again.content
    learned = dispatch("key_item", "t", {"events": [{"name": "Steward's Ledger", "event": "learned"}]}, s)
    assert "award" not in learned.content


def test_getting_an_item_opens_the_quest_it_unlocks_and_says_so():
    story = short_story()
    s, ids = adventure(story)
    story.milestones[2].needs, story.milestones[2].status = [ids["ledger"]], "pending"
    out = dispatch("key_item", "t", {"events": [{"name": "Steward's Ledger", "event": "acquired"}]}, s)
    assert "Now active, since the party has the item: [side] Quest side" in out.content
    assert s.story.milestone("side").status == "active"
    assert story.milestone("side").status == "pending"  # the original object is untouched until the turn commits


# ---- the award --------------------------------------------------------------------------------


def hero_state():
    s, ids = adventure()
    s.campaign = {"setting": "x", "party": [{"name": "Kit", "sheet": "Rogue."}], "level": 1}
    return s, ids


def test_an_award_in_the_same_turn_clears_what_is_owed_and_none_is_asked_for_later():
    s, ids = hero_state()
    dispatch("key_item", "t", {"events": [{"name": "Sluice Key", "event": "acquired"}]}, s)
    assert s.world.find("Sluice Key").holding.owed == 5
    out = dispatch("award", "t", {"xp": 50, "reason": "Got the Sluice Key"}, s)
    assert not out.is_error and s.world.find("Sluice Key").holding.owed is None
    assert "Unawarded" not in build_briefing(s.world, turn=6)


def test_an_unawarded_item_is_mentioned_once_the_next_turn_and_then_dropped():
    s, ids = hero_state()
    dispatch("key_item", "t", {"events": [{"name": "Sluice Key", "event": "acquired"}]}, s)
    assert "Unawarded" not in build_briefing(s.world, turn=5)  # the same turn: the tool result already said so
    next_turn = build_briefing(s.world, turn=6)
    assert "Unawarded: the party got Sluice Key last turn" in next_turn
    assert "Unawarded" not in build_briefing(s.world, turn=7)


def test_what_the_party_starts_with_and_gets_back_earns_nothing():
    w, ids = vault()
    w.set_holding(ids["ledger"], "acquired", turn=1, source="seed")
    assert w.entities[ids["ledger"]].holding.owed is None
    w.set_holding(ids["key"], "acquired", turn=2)
    w.entities[ids["key"]].holding.owed = None
    w.set_holding(ids["key"], "lost", turn=3)
    w.set_holding(ids["key"], "acquired", turn=4)
    assert w.entities[ids["key"]].holding.owed is None


def test_the_owed_turn_is_saved_but_never_shown_to_the_player():
    from aigm.compendium import Compendium, detail

    w, ids = vault()
    w.set_holding(ids["key"], "acquired", turn=4)
    back = World.from_dict(json.loads(json.dumps(w.to_dict())))
    assert back.entities[ids["key"]].holding.owed == 4
    assert "owed" not in detail(w, Compendium(), ids["key"])["holding"]


# ---- the plotter ----------------------------------------------------------------------------


class ItemPlotter(ScriptedCurator):
    """The scripted plan, with a key item the party must find and a later quest that needs it."""

    def __init__(self, mutate=None):
        super().__init__()
        self.mutate = mutate
        self.requests: list[PlotRequest] = []

    async def plot(self, request: PlotRequest) -> PlotProposal:
        self.requests.append(request)
        out = await super().plot(request)
        if request.story_so_far:
            return out
        out.entities.append(EntityProposal("Harbor Ledger", "item"))
        out.facts += [
            FactProposal("Harbor Ledger is a thick green-bound book with brass corners.", ["Harbor Ledger", "Ashby"], "appearance"),
            FactProposal("The Harbor Ledger is kept in the harbor master's strongbox.", ["Harbor Ledger", "Ashby"], "whereabouts"),
        ]
        quests = [q for q in out.quests if q.chapter == 1]
        quests[0].finds = "Harbor Ledger"
        quests[-1].needs = ["Harbor Ledger"]
        if self.mutate:
            self.mutate(out)
        return out


async def test_the_plotter_may_make_a_key_item_and_quests_about_it():
    result = await run_plot(plot_world(), CAMPAIGN, "short", ItemPlotter())
    assert any(op.__class__.__name__ == "AddEntity" and op.kind == "item" for op in result.ops)
    first, second = result.story.milestones[0], result.story.milestones[1]
    assert first.finds and second.needs == [first.finds]


async def test_the_curator_alone_still_cannot_make_an_item():
    from aigm.world.passes import PassConfig, _clean_extraction, PassResult
    from aigm.world.curator import Extraction

    ex = Extraction(entities=[EntityProposal("Sneaky Key", "item"), EntityProposal("Wren", "npc")])
    kept = _clean_extraction(ex, PassConfig(), PassResult())
    assert [e.name for e in kept.entities] == ["Wren"]
    ex = Extraction(entities=[EntityProposal("Plot Key", "item")])
    assert [e.name for e in _clean_extraction(ex, PassConfig(allow_items=True), PassResult()).entities] == ["Plot Key"]


async def test_a_plan_that_finds_an_item_the_world_lacks_is_sent_back():
    from aigm.world.curator import CuratorError

    def drop_the_item(out):
        out.entities[:] = [e for e in out.entities if e.kind != "item"]

    cur = ItemPlotter(drop_the_item)
    cur.always = True
    with pytest.raises(CuratorError, match="not a key item you created"):
        await run_plot(plot_world(), CAMPAIGN, "short", cur)
    assert len(cur.requests) == 2 and cur.requests[1].feedback  # sent back once with the reasons


async def test_a_later_chapter_plan_points_its_quests_at_the_live_worlds_items():
    w = plot_world()
    first = await run_plot(w, CAMPAIGN, "medium", ItemPlotter())
    from aigm.world.ops import apply_ops

    apply_ops(w, first.ops)
    story = first.story
    story.chapter = 2
    cur = ItemPlotter()

    async def plot_two(request):
        out = await ScriptedCurator.plot(cur, request)
        for q in out.quests:
            q.needs = ["Harbor Ledger"]
        return out

    cur.plot = plot_two  # type: ignore[method-assign]
    second = await run_chapter_plot(w, CAMPAIGN, story, 2, cur)
    second.rebind(w)
    ledger = w.find("Harbor Ledger")
    assert second.milestones and all(m.needs == [ledger.id] for m in second.milestones)


async def test_the_model_plotter_reads_finds_needs_and_may_make_an_item():
    from tests.test_plot import plot_reply
    from tests.test_world_curator import curator

    reply = plot_reply()
    reply["quests"][0].update(finds="The Ledger", needs=["The Key"])
    reply["entities"].append({"name": "The Ledger", "kind": "item", "aliases": [], "parent": None})
    cur, messages = curator(reply)
    request = PlotRequest("short", "A vale.", "Dusk.", 2, [("Wren", "A ranger.")], "", [], [], (1, 2, 3), (2, 3), ("small",))
    proposal = await cur.plot(request)
    assert (proposal.quests[0].finds, proposal.quests[0].needs) == ("The Ledger", ["The Key"])
    assert proposal.entities[-1].kind == "item"
    schema = messages.calls[0]["output_config"]["format"]["schema"]
    assert "item" in schema["properties"]["entities"]["items"]["properties"]["kind"]["enum"]
    assert {"finds", "needs"} <= set(schema["properties"]["quests"]["items"]["properties"])
