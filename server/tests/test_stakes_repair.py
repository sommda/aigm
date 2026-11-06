"""Stakes, step 3 (docs/STAKES.md 3 to 5, STORY.md 8.2): repairing a failed quest, the clock in chapters 1 and 2."""

import pytest

from aigm import story as st
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.story import Deadline
from aigm.world import World, WorldTime
from aigm.world.curator import CuratorError, EntityProposal, QuestProposal
from aigm.world.plot import repair_brief, run_repair_plot
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService
from tests.test_plot import CAMPAIGN, world
from tests.test_story import short_story


def failed_story(chapter=2, quest="m3", turn=20):
    s = short_story()
    s.chapter = chapter
    st.settle_ready(s)
    m = s.milestone(quest)
    m.status, m.outcome, m.done_turn = "failed", "The bridge burned.", turn
    return s


def backup(key="b1", chapter=2, **kw):
    return QuestProposal(key, chapter, "Another Way", "Find another way.", "small", "a way on", **kw)


# ---- the pure rules ----------------------------------------------------------------------


def test_a_failed_required_quest_needs_a_repair_and_blocks_the_chapter():
    s = failed_story()
    assert st.needs_repair(s).id == "m3"
    s.milestone("m4").status = "done"
    assert not st.chapter_complete(s)  # a failed quest still blocks
    assert st.needs_repair(short_story()) is None and st.needs_repair(st.Story(st.ENDLESS)) is None


def test_a_failed_side_quest_needs_no_repair():
    s = failed_story(1, "side")
    assert st.needs_repair(s) is None


def test_a_repair_puts_the_backup_in_the_failed_quests_place():
    s = failed_story()
    new = st.Milestone("m06", 2, "Another Way", "b", requires=[])
    new2 = st.Milestone("m07", 2, "The Last Mile", "b", requires=["m06"])
    s.milestone("m4").requires = ["m3"]
    opened = st.apply_repair(s, "m3", [new, new2])
    assert not s.milestone("m3").required and s.milestone("m3").status == "failed"
    assert (new.backup_for, new2.backup_for) == ("m3", "m3") and new.required
    assert s.milestone("m4").requires == ["m07"]  # whatever waited on m3 now waits on the end of the new chain
    assert opened == ["m06"] and st.needs_repair(s) is None


def test_the_backups_inherit_what_the_failed_quest_required():
    s = failed_story()
    s.milestone("m3").requires = ["m1"]
    new = st.Milestone("m06", 2, "Another Way", "b")
    st.apply_repair(s, "m3", [new])
    assert new.requires == ["m1"]


def test_a_second_failure_of_the_same_line_is_deeper():
    s = failed_story()
    first = st.Milestone("m06", 2, "Another Way", "b")
    st.apply_repair(s, "m3", [first])
    first.status = "failed"
    assert st.repair_depth(s, s.milestone("m3")) == 1 and st.repair_depth(s, first) == 2


def test_a_quest_nobody_repairs_is_given_up_after_the_stall():
    s = failed_story(turn=20)
    assert st.expire_failed(s, 59) == []
    assert st.expire_failed(s, 60) == ["m3"]
    assert s.milestone("m3").status == "skipped" and "moved on" in s.milestone("m3").outcome


# ---- the clock ---------------------------------------------------------------------------


def clocked(chapter):
    s = short_story()
    s.chapter = chapter
    st.settle_ready(s)
    quest = s.in_chapter(chapter)[0]
    quest.deadline = Deadline(WorldTime(3, 12), "the storm", fixed=True)
    w = World()
    w.time = WorldTime(3, 14)
    return s, quest, w


def test_a_chapter_one_deadline_slides_and_the_delay_is_written_down():
    s, quest, w = clocked(1)
    notes = st.settle_due(s, w, 9)
    assert notes and quest.status == "active"
    assert quest.deadline.at == WorldTime(4, 14) and quest.deadline.fixed
    assert s.costs[-1]["kind"] == "time" and "slid a day" in s.costs[-1]["text"]
    assert st.settle_due(s, w, 10) == []  # it is a day away again


def test_a_chapter_two_deadline_fails_the_quest_at_a_cost():
    s, quest, w = clocked(2)
    st.settle_due(s, w, 9)
    assert quest.status == "failed" and quest.deadline is None and s.costs[-1]["kind"] == "position"
    assert st.needs_repair(s) is quest


# ---- the plotter's repair ----------------------------------------------------------------


def test_the_brief_asks_for_a_backup_and_a_cost_in_chapter_two():
    s = failed_story()
    text = repair_brief(s, s.milestone("m3"))
    assert "The bridge burned." in text and "add no region" in text and "`cost`" in text and "harder" not in text
    s.costs.append({"turn": 20, "chapter": 2, "milestone": "m3", "kind": "resource", "text": "80 gold"})
    assert "80 gold" in repair_brief(s, s.milestone("m3"))


def test_the_brief_is_gentler_in_chapter_one_and_harder_on_a_second_failure():
    s = failed_story(1, "m1")
    assert "small and never blocks" in repair_brief(s, s.milestone("m1")) and "add no region" not in repair_brief(s, s.milestone("m1"))
    s = failed_story()
    first = st.Milestone("m06", 2, "Another Way", "b")
    st.apply_repair(s, "m3", [first])
    first.status = "failed"
    assert "failed 2 times" in repair_brief(s, first)


async def test_a_repair_is_planned_against_the_failure():
    s = failed_story()
    result = await run_repair_plot(world(), CAMPAIGN, s, s.milestone("m3"), ScriptedCurator())
    assert result.repair_of == "m3" and [m.chapter for m in result.milestones] == [2]
    assert result.cost and result.cost[0] == "resource"
    assert len(s.milestones) == 5  # the story given is not changed


async def test_a_repair_that_adds_a_faction_in_chapter_two_is_sent_back():
    s = failed_story()
    seen = []

    class Curator(ScriptedCurator):
        async def plot(self, request):
            seen.append(request.feedback)
            out = await super().plot(request)
            if not request.feedback:
                out.entities.append(EntityProposal("The Ash Guild", "faction"))
            return out

    result = await run_repair_plot(world(), CAMPAIGN, s, s.milestone("m3"), Curator())
    assert seen[0] == [] and any("major addition" in f for f in seen[1]) and result.milestones


async def test_a_repair_without_a_cost_is_sent_back_when_none_is_recorded():
    s = failed_story()

    class Curator(ScriptedCurator):
        async def plot(self, request):
            out = await super().plot(request)
            if not request.feedback:
                out.cost = ""
            return out

    curator = Curator()
    result = await run_repair_plot(world(), CAMPAIGN, s, s.milestone("m3"), curator)
    assert result.cost  # the second answer named one


async def test_too_many_backups_are_refused():
    s = failed_story()

    class Curator(ScriptedCurator):
        async def plot(self, request):
            out = await super().plot(request)
            out.quests = [backup(f"b{i}") for i in range(4)]
            return out

    with pytest.raises(CuratorError, match="repair of m3"):
        await run_repair_plot(world(), CAMPAIGN, s, s.milestone("m3"), Curator())


# ---- the service -------------------------------------------------------------------------


def session_with(story):
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, CAMPAIGN, world(), structure="short", story=story, turn=30)
    return session


async def test_the_service_mends_a_failed_quest_in_the_background():
    session = session_with(failed_story())
    service = CuratorService(ScriptedCurator())
    assert service.repair_due(session)
    assert await service.run_if_due(session)
    story = session.state.story
    assert st.needs_repair(story) is None and not story.milestone("m3").required
    [new] = [m for m in story.milestones if m.backup_for == "m3"]
    assert new.status == "active" and story.last_progress_turn == 30
    assert story.costs and story.costs[-1]["milestone"] == "m3"  # the plotter named the cost: the GM had not
    assert not service.repair_due(session)


async def test_a_repair_does_not_replace_the_gms_own_cost():
    story = failed_story()
    st.record_cost(story, 20, "m3", "ally", "Sister Orla left them.")
    session = session_with(story)
    await CuratorService(ScriptedCurator()).run_if_due(session)
    assert [c["text"] for c in session.state.story.costs] == ["Sister Orla left them."]


async def test_the_service_gives_up_on_a_quest_nothing_could_mend():
    class Broken(ScriptedCurator):
        async def plot(self, request):
            raise CuratorError("no")

    session = session_with(failed_story(turn=1))
    session.state.turn = 50
    service = CuratorService(Broken())
    await service.run_if_due(session)
    assert session.state.story.milestone("m3").status == "skipped"


async def test_the_service_applies_the_clock_after_a_turn():
    s, quest, w = clocked(1)
    session = session_with(s)
    session.state.world = w
    await CuratorService(ScriptedCurator()).run_if_due(session)
    assert quest.deadline.at == WorldTime(4, 14)


def test_the_briefing_tells_the_gm_a_repair_is_coming_and_drift_in_chapter_one():
    s = failed_story()
    text = st.briefing_block(s, World(), 30)
    assert "has failed and a way round is being written" in text
    one = short_story()
    one.milestone("m1").entities = ["e1"]
    assert "Drift:" in st.briefing_block(one, World(), 3)
    two = short_story()
    two.chapter = 2
    st.settle_ready(two)
    assert "Drift:" not in st.briefing_block(two, World(), 3)
