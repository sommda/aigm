"""The story plan and its rules (docs/STORY.md): pure logic, saves."""

import json

import pytest

from aigm import story as st
from aigm.errors import CorruptSave
from aigm.session.state import GameState, Phase
from aigm.story import Chapter, Ending, Goal, Milestone, Story
from aigm.world import World


def ms(id, chapter=1, requires=(), **kw):
    return Milestone(id, chapter, f"Quest {id}", f"Do {id}.", requires=list(requires), **kw)


def endings():
    return [Ending("e1", "Freed", "The goal is destroyed."), Ending("e2", "Fallen", "The party fails.")]


def short_story(**kw):
    """Chapter 1 with m1 then m2 (and an optional side quest), chapter 2 with m3, m4."""
    s = Story(
        "short",
        goal=Goal("The Crown", "A crown binds the river.", [], False, "Level 5"),
        chapters=[Chapter("Ashby", "Learn the vale"), Chapter("The road", "Go north"), Chapter("The vault", "End it")],
        milestones=[
            ms("m1"),
            ms("m2", requires=["m1"]),
            ms("side", required=False),
            ms("m3", 2),
            ms("m4", 2, requires=["m3"]),
        ],
        endings=endings(),
    )
    for k, v in kw.items():
        setattr(s, k, v)
    st.settle_ready(s)
    return s


# ---- saving and reading ------------------------------------------------------------------


def test_a_story_survives_a_round_trip():
    s = short_story()
    s.goal.revealed = True
    st.report(s, "m1", "done", "Found the miller.", 5)
    again = Story.from_dict(json.loads(json.dumps(s.to_dict())))
    assert again == s and again is not s


def test_copy_is_independent():
    s = short_story()
    c = s.copy()
    c.milestone("m1").status = "done"
    assert s.milestone("m1").status == "active"


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.update(length="epic"), "length"),
        (lambda d: d["milestones"][1].update(requires=["nope"]), "unknown nope"),
        (lambda d: d["milestones"][1].update(id="m1"), "unique"),
        (lambda d: d["milestones"][0].update(scale="huge"), "scale"),
        (lambda d: d["milestones"][0].update(status="stuck"), "status"),
        (lambda d: d["milestones"][0].update(chapter=4), "chapter"),
        (lambda d: d.update(chapter=9), "chapter"),
        (lambda d: d.update(endings=d["endings"] + d["endings"][:1]), "ending ids"),
        (lambda d: d.update(milestones="none"), "milestones"),
        (lambda d: d["goal"].update(revealed="yes"), "revealed"),
    ],
)
def test_a_damaged_story_is_a_corrupt_save(mutate, message):
    data = short_story().to_dict()
    mutate(data)
    with pytest.raises(CorruptSave, match=message):
        Story.from_dict(data)


def test_a_story_that_is_not_an_object_is_corrupt():
    with pytest.raises(CorruptSave):
        Story.from_dict([])


# ---- game state ---------------------------------------------------------------------------


def adventure(**kw):
    return GameState(Phase.ADVENTURE, {"setting": "x"}, **kw)


def test_state_round_trips_structure_and_story():
    state = adventure(structure="short", story=short_story())
    loaded = GameState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert loaded.structure == "short" and loaded.story == state.story


def test_state_copy_copies_the_story():
    state = adventure(structure="short", story=short_story())
    copy = state.copy()
    copy.story.milestone("m1").status = "done"
    assert state.story.milestone("m1").status == "active"


def test_an_endless_state_saves_no_story():
    data = adventure().to_dict()
    assert data["structure"] == "endless" and data["story"] is None


def test_saves_from_before_stories_are_endless():
    state = GameState.from_dict({"phase": "adventure", "campaign": {"setting": "x"}})
    assert state.structure == "endless" and state.story is None


def test_a_plan_may_be_missing_while_the_plotter_has_not_run():
    state = GameState.from_dict(adventure(structure="medium").to_dict())
    assert state.structure == "medium" and state.story is None


def test_structure_and_story_must_agree():
    data = adventure(structure="short", story=short_story()).to_dict()
    for bad in ({"structure": "long"}, {"structure": "endless"}, {"structure": "forever"}):
        with pytest.raises(CorruptSave):
            GameState.from_dict({**data, **bad})


def test_session_zero_has_no_story_but_may_have_a_structure():
    zero = GameState(structure="long").to_dict()
    assert GameState.from_dict(zero).structure == "long"
    with pytest.raises(CorruptSave, match="session_zero"):
        GameState.from_dict({**zero, "structure": "short", "story": short_story().to_dict()})


# ---- checking a plan ---------------------------------------------------------------------


def test_a_good_plan_has_no_problems():
    assert st.validate_plan(short_story()) == []


def test_the_plan_needs_a_goal_and_two_to_four_endings():
    s = short_story(goal=None, endings=endings()[:1])
    problems = st.validate_plan(s)
    assert any("no goal" in p for p in problems) and any("endings" in p for p in problems)


def test_chapters_are_sized_for_the_length():
    s = short_story()
    s.milestones += [ms(f"x{i}", 2) for i in range(5)]
    assert any("chapter 2 has 7" in p for p in st.validate_plan(s))
    thin = short_story(milestones=[ms("m1"), ms("m2", 2), ms("m3", 2), ms("m4", 2)])
    assert st.validate_plan(thin) == []  # one short of the range is within the slack
    bare = short_story(milestones=[ms("m1", required=False), ms("m2", 2), ms("m3", 2)])
    assert any("chapter 1 has 0" in p for p in st.validate_plan(bare))


def test_a_chapter_with_no_quests_is_not_checked_yet():
    s = short_story(milestones=[ms("m1"), ms("m2", requires=["m1"])])
    assert st.validate_plan(s) == []


def test_quest_scale_must_fit_the_length():
    s = short_story()
    s.milestone("m1").scale = "large"
    assert any("m1 is a large quest" in p for p in st.validate_plan(s))
    long = Story("long", goal=s.goal, endings=endings(), milestones=[ms(f"q{i}", scale="large") for i in range(10)])
    assert st.validate_plan(long) == []


def test_cycles_and_forward_requirements_are_refused():
    s = short_story()
    s.milestone("m1").requires = ["m2"]
    assert any("never become available" in p for p in st.validate_plan(s))
    t = short_story()
    t.milestone("m2").requires = ["m3"]
    assert any("requires m3, which is in chapter 2" in p for p in st.validate_plan(t))
    u = short_story()
    u.milestone("m1").requires = ["m1"]
    assert any("requires itself" in p for p in st.validate_plan(u))


def test_named_entities_must_exist_in_the_world():
    world = World()
    here = world.add_entity("Ashby", "location")
    s = short_story()
    s.goal.entities = [here.id]
    s.milestone("m1").entities = ["e999"]
    problems = st.validate_plan(s, world)
    assert problems == ["m1 names e999, which is not in the world"]


# ---- moving through the story ------------------------------------------------------------


def test_only_quests_with_settled_requirements_are_active():
    s = short_story()
    assert [m.id for m in st.active(s)] == ["m1", "side"]
    assert s.milestone("m3").status == "pending"  # a later chapter waits


def test_finishing_a_quest_opens_the_next():
    s = short_story()
    result = st.report(s, "m1", "done", "Found the miller.", 5)
    assert result.ok and result.opened == ["m2"] and s.last_progress_turn == 5
    assert s.milestone("m1").outcome == "Found the miller." and s.milestone("m1").done_turn == 5
    assert s.choices[-1] == {"turn": 5, "milestone": "m1", "note": "Found the miller."}


def test_reports_are_checked():
    s = short_story()
    cases = [
        (("nope", "done", "x"), "no milestone"),
        (("m2", "done", "x"), "pending"),
        (("m1", "won", "x"), "status"),
        (("m1", "done", "  "), "outcome"),
    ]
    for args, message in cases:
        result = st.report(s, *args, 3)
        assert not result.ok and message in result.message
    assert s.milestone("m1").status == "active" and s.last_progress_turn == 1
    st.report(s, "m1", "done", "ok", 4)
    assert "done" in st.report(s, "m1", "done", "again", 5).message


def test_a_skipped_or_failed_quest_is_recorded_but_only_skipping_settles_it():
    s = short_story()
    st.report(s, "m1", "skipped", "The party went round.", 3)
    assert s.milestone("m2").status == "active" and s.choices == []
    t = short_story()
    st.report(t, "m1", "failed", "The miller died.", 3)
    assert t.milestone("m2").status == "pending" and t.milestone("m1").status == "failed"


def test_chapter_one_needs_the_goal_to_be_known():
    s = short_story()
    st.report(s, "m1", "done", "a", 2)
    result = st.report(s, "m2", "done", "b", 3)
    assert s.chapter == 1 and result.advanced_to is None and not st.chapter_complete(s)
    s.goal.revealed = True
    assert st.chapter_complete(s)  # the side quest is optional


def test_finishing_the_required_quests_advances_the_chapter():
    s = short_story()
    s.goal.revealed = True
    st.report(s, "m1", "done", "a", 2)
    result = st.report(s, "m2", "done", "b", 7)
    assert result.advanced_to == 2 and s.chapter == 2 and s.chapter_started_turn == 7
    assert result.opened == ["m3"] and [m.id for m in st.active(s)] == ["m3"]
    assert st.chapter_label(s) == "The road"


def test_only_the_third_chapter_ends_with_an_ending():
    s = short_story(chapter=3)
    s.milestones.append(ms("m5", 3))
    st.settle_ready(s)
    s.milestone("m5").status = "done"
    assert st.chapter_complete(s)
    assert st.advance_chapter(s, 20) == 3  # it stays on 3
    assert not st.conclude(s, "nope", "x").ok
    assert st.conclude(s, "e1", " The vale is free. ").ok
    assert s.concluded and s.ending == "e1" and s.epilogue == "The vale is free."
    assert st.chapter_label(s) == "The end" and not st.chapter_complete(s)
    assert not st.report(s, "m5", "done", "x", 30).ok and not st.conclude(s, "e2", "x").ok


def test_a_custom_ending_is_accepted():
    s = short_story()
    assert st.conclude(s, "end_custom", "Something else happened.").ok


def test_pace_rises_with_idle_turns():
    s = short_story(last_progress_turn=10)
    assert [st.pace(s, t, 12) for t in (10, 21, 22, 33, 34, 99)] == [0, 0, 1, 1, 2, 2]
    assert st.pace(s, 99, 0) == 0
    assert st.pace(Story("short"), 99, 12) == 0  # no plan yet
    st.conclude(s, "e1", "x")
    assert st.pace(s, 99, 12) == 0


# ---- what may be added to the world --------------------------------------------------------


def world_with_places():
    world = World()
    region = world.add_entity("The Vale", "location")
    town = world.add_entity("Ashby", "location", parent=region.id)
    return world, region, town


def test_chapter_one_and_endless_games_may_add_anything():
    world, region, _ = world_with_places()
    assert st.addition_allowed(None, world, "faction", None)[0]
    assert st.addition_allowed(short_story(), world, "location", None)[0]


def test_later_chapters_take_details_only():
    world, region, town = world_with_places()
    s = short_story(chapter=2)
    assert st.addition_allowed(s, world, "npc", None)[0]
    assert st.addition_allowed(s, world, "location", "Ashby")[0]  # a cellar in the town, by name
    assert st.addition_allowed(s, world, "location", town.id)[0]
    for kind, parent in (("faction", None), ("concept", None), ("location", None), ("location", region.id),
                         ("location", "Nowhere")):  # fmt: skip
        allowed, why = st.addition_allowed(s, world, kind, parent)
        assert not allowed and "major addition" in why, (kind, parent)


def test_a_finished_story_lifts_the_limits():
    world, _, _ = world_with_places()
    s = short_story()
    st.conclude(s, "e1", "x")
    assert st.addition_allowed(s, world, "faction", None)[0]
