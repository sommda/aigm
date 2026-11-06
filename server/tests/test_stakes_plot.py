"""Stakes, step 7 (docs/STAKES.md 2, 8, 10): the plotter writes failure, the plan is held to it, the GM is told."""

import pytest

from aigm import story as st
from aigm.story import Deadline, Doom
from aigm.world import World, WorldTime
from aigm.world.anthropic_curator import PLOT_SCHEMA, _deadline
from aigm.world.curator import DeadlineProposal, DoomProposal
from aigm.world.plot import run_chapter_plot
from aigm.world.render import render_plot
from tests.test_plot import CAMPAIGN, Fixing, plot, world
from tests.test_story import short_story
from tests.test_story_chapters import medium_story


async def test_the_scripted_plan_carries_failure_into_the_story():
    result = await plot("short", Fixing(lambda out: None))
    story = result.story
    ch3 = [m for m in story.in_chapter(3) if m.required]
    assert all(len(m.fails_if) >= 3 for m in ch3)
    assert all(m.ending == "end2" for m in ch3) and len(ch3[-1].fails_if) == 5
    assert sum(1 in d.chapters for d in story.dooms) == 0
    assert sum(2 in d.chapters for d in story.dooms) == 1 and sum(3 in d.chapters for d in story.dooms) == 3
    assert [d.id for d in story.dooms] == ["d1", "d2", "d3"] and all(d.ending == "end2" for d in story.dooms)


async def test_a_later_chapter_adds_its_quests_and_dooms():
    story = medium_story()
    curator = Fixing(lambda out: None)
    result = await run_chapter_plot(world(), CAMPAIGN, story, 3, curator)
    assert curator.requests[0].now.startswith("Day")
    assert [d.id for d in result.dooms] == ["d1", "d2", "d3"] and all(d.chapters == [3] for d in result.dooms)
    assert all(m.ending == "end2" for m in result.milestones)


@pytest.mark.parametrize(
    "break_it, message",
    [
        (lambda o: setattr(o.quests[-1], "fails_if", ["only one"]), "gauntlet"),
        (lambda o: setattr(o.quests[-1], "ending", ""), "needs an `ending`"),
        (lambda o: setattr(o.quests[-1], "ending", "Nonsense"), "not one of the endings"),
        (lambda o: o.dooms.clear(), "dooms"),
        (lambda o: setattr(o.dooms[0], "chapters", [1]), "never in chapter 1"),
        (lambda o: setattr(o.dooms[0], "ending", ""), "doom d1 needs an `ending`"),
        (lambda o: setattr(o.quests[0], "fails_if", ["a", "b"]), "at most one way"),
        (lambda o: setattr(o.quests[0], "deadline", DeadlineProposal(1, 8, "the sun")), "not after the time now"),
        (lambda o: setattr(o.quests[0], "deadline", DeadlineProposal(9, 8, "")), "needs a `cue`"),
        (lambda o: setattr(o.quests[0], "deadline", DeadlineProposal(9, 30, "x")), "not a real time"),
    ],
)
async def test_a_plan_that_breaks_the_stakes_rules_is_sent_back(break_it, message):
    curator = Fixing(break_it)
    result = await plot("short", curator)
    assert len(curator.requests) == 2 and any(message in f for f in curator.requests[1].feedback), curator.requests[1].feedback
    assert result.story is not None


async def test_a_deadline_and_a_doom_deadline_are_read_into_the_plan():
    def add(out):
        out.quests[0].deadline = DeadlineProposal(6, 18, " the second sun ", True)
        out.dooms[0].deadline = DeadlineProposal(20, 0, "the ritual's glow")

    result = await plot("short", Fixing(add))
    story = result.story
    assert story.milestones[0].deadline.at == WorldTime(6, 18) and story.milestones[0].deadline.cue == "the second sun"
    assert story.milestones[0].deadline.fixed and story.dooms[0].deadline.at == WorldTime(20, 0)


def test_the_plotter_is_told_the_time_and_the_schema_is_strict():
    from aigm.world.curator import PlotRequest

    req = PlotRequest("short", "s", "o", 1, [], "", [], [], (1,), (2, 3), ("small",), now="Day 1, 08:00")
    assert "Day 1, 08:00" in render_plot(req)
    quest = PLOT_SCHEMA["properties"]["quests"]["items"]
    assert set(quest["properties"]) == set(quest["required"]) and {"fails_if", "deadline", "ending"} <= set(quest["properties"])
    assert "dooms" in PLOT_SCHEMA["properties"]
    assert _deadline({"deadline": "6 18 fixed the second sun slides toward the Spire"}) == DeadlineProposal(
        6, 18, "the second sun slides toward the Spire", True
    )
    assert _deadline({"deadline": "Day 3, 04:30 soft: the caravan's dust"}) == DeadlineProposal(3, 4, "the caravan's dust")
    assert _deadline({"deadline": ""}) is None and _deadline({"deadline": "0 8 fixed x"}) is None
    assert _deadline({"deadline": "soon"}) is None
    assert _deadline(None) is None


# ---- the clock and the briefing --------------------------------------------------------------


def staged(chapter):
    s = short_story()
    s.chapter = chapter
    st.settle_ready(s)
    return s


def test_a_deadline_knows_how_much_time_is_gone():
    d = Deadline(WorldTime(5, 0), "c", start=WorldTime(1, 0))
    assert d.used(WorldTime(1, 0)) == 0 and d.used(WorldTime(3, 0)) == 0.5 and d.used(WorldTime(9, 0)) == 1
    assert Deadline(WorldTime(5, 0)).used(WorldTime(3, 0)) is None
    assert Deadline.__dataclass_fields__["start"] and st.Story.from_dict(_with(d).to_dict()).milestones[0].deadline == d


def _with(d):
    s = staged(1)
    s.milestone("m1").deadline = d
    return s


def test_the_clock_starts_when_a_quest_opens_or_a_doom_applies():
    s = staged(1)
    s.milestone("m1").deadline = Deadline(WorldTime(5, 0), "c")
    w = World()
    w.time = WorldTime(2, 6)
    st.stamp_deadlines(s, w)
    assert s.milestone("m1").deadline.start == WorldTime(2, 6)
    w.time = WorldTime(3, 0)
    st.stamp_deadlines(s, w)
    assert s.milestone("m1").deadline.start == WorldTime(2, 6)  # only once


def hard(chapter, used_days):
    s = staged(chapter)
    s.dooms = [Doom("d1", "The ritual completes", [2, 3], Deadline(WorldTime(11, 0), "the glow", start=WorldTime(1, 0)), "e2")]
    w = World()
    w.time = WorldTime(1 + used_days, 0)
    return s, w


@pytest.mark.parametrize(
    "days, phrase",
    [(1, "a passing detail"), (5, "a remark from a companion"), (8, "an urgent line"), (9.5, "plain statement")],
)
def test_a_hard_deadline_grows_in_the_briefing(days, phrase):
    s, w = hard(2, 0)
    w.time = WorldTime(1, 0).plus_minutes(int(days * 24 * 60))
    text = st.briefing_block(s, w, 5)
    assert "Hard deadline (The ritual completes)" in text and "the glow" in text and phrase in text
    assert "never lose track" in text and "Never say what happens" in text


def test_a_soft_deadline_is_a_lighter_touch():
    s = staged(2)
    s.milestone("m3").deadline = Deadline(WorldTime(11, 0), "the caravan's dust", start=WorldTime(1, 0))
    w = World()
    w.time = WorldTime(2, 0)
    assert "Time limit" not in st.briefing_block(s, w, 5)
    w.time = WorldTime(6, 12)
    assert "give one hint" in st.briefing_block(s, w, 5)
    w.time = WorldTime(9, 0)
    assert "say it plainly" in st.briefing_block(s, w, 5)


def test_chapter_three_quest_deadlines_are_hard():
    s = staged(3)
    s.chapter = 3
    quest = next(m for m in s.in_chapter(2))  # the script puts the open quest in chapter 2: move it
    quest.chapter, quest.status = 3, "active"
    quest.deadline = Deadline(WorldTime(5, 0), "the suns", start=WorldTime(1, 0))
    w = World()
    w.time = WorldTime(2, 0)
    assert "Hard deadline" in st.briefing_block(s, w, 5)


@pytest.mark.parametrize("chapter, phrase", [(1, "Stakes are low"), (2, "Stakes are real"), (3, "Stakes are final")])
def test_the_briefing_states_the_stakes_and_the_hinting_rule(chapter, phrase):
    text = st.briefing_block(staged(chapter), World(), 5)
    assert phrase in text and "Hint at danger through the world" in text


def test_a_passed_deadline_is_not_shown():
    s, w = hard(2, 11)
    assert "Hard deadline" not in st.briefing_block(s, w, 5)
