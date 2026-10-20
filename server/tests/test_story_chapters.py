"""Chapters 2 and 3 (docs/STORY.md 5, 6.4, 8): planning the next chapter, the curator backstop, the limits."""

import pytest
from fastapi.testclient import TestClient

from aigm import story as st
from aigm.app import create_app
from aigm.config import Settings
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.tools import dispatch
from aigm.world import World
from aigm.world.curator import (
    CuratorError,
    EntityProposal,
    Extraction,
    FactProposal,
)
from aigm.world.ops import AddEntity, apply_ops
from aigm.world.passes import PassConfig, run_pass
from aigm.world.plot import run_chapter_plot
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService
from tests.conftest import chat
from tests.test_plot import CAMPAIGN, Fixing, world
from tests.test_story import short_story
from tests.test_story_gm import state_with_story
from tests.test_world_pass import FakeCurator, convo


def medium_story():
    """A medium game that has just reached chapter 2, whose quests are not written yet."""
    s = st.Story("medium", goal=st.Goal("The Crown", "It binds the river.", [], True, "Level 5"))
    s.chapters = [st.Chapter("One", "p", 3), st.Chapter("Two", "p", 5), st.Chapter("Three", "p", 7)]
    s.endings = [st.Ending("end1", "Free", "x"), st.Ending("end2", "Lost", "y")]
    s.milestones = [
        st.Milestone(f"m0{i}", 1, f"Quest {i}", "b", scale="small", gives="a boon", status="done", outcome="Did it.")
        for i in range(1, 6)
    ]
    s.chapter = 2
    return s


# ---- planning the next chapter -----------------------------------------------------------


def test_a_story_waits_for_the_plan_of_the_chapter_it_has_reached():
    s = medium_story()
    assert st.needs_plan(s) == 2
    s.milestones.append(st.Milestone("m06", 2, "T", "B", scale="small"))
    assert st.needs_plan(s) is None
    assert st.needs_plan(short_story()) is None  # chapter 1 is planned with the game
    done = medium_story()
    st.conclude(done, "end1", "x")
    assert st.needs_plan(done) is None and st.needs_plan(st.Story("short")) is None


async def test_the_next_chapter_is_written_against_the_story_so_far():
    story, curator = medium_story(), Fixing(lambda out: None)
    result = await run_chapter_plot(world(), CAMPAIGN, story, 2, curator)
    request = curator.requests[0]
    assert request.chapters == (2,) and "Quest 3 (chapter 1" not in request.story_so_far
    assert "Did it." in request.story_so_far and "Goal: The Crown" in request.story_so_far
    assert [m.id for m in result.milestones] == ["m06", "m07", "m08", "m09", "m10"]
    assert all(m.chapter == 2 for m in result.milestones) and result.chapter == 2
    assert len(story.milestones) == 5  # the story given is not changed


async def test_a_chapter_plan_that_breaks_the_rules_is_sent_back_once():
    def too_few(out):
        out.quests[:] = out.quests[:1]

    curator = Fixing(too_few)
    result = await run_chapter_plot(world(), CAMPAIGN, medium_story(), 2, curator)
    assert len(curator.requests) == 2 and any("chapter 2 has" in f for f in curator.requests[1].feedback)
    assert len(result.milestones) == 5
    curator.always = True
    with pytest.raises(CuratorError, match="chapter 2"):
        await run_chapter_plot(world(), CAMPAIGN, medium_story(), 2, curator)


async def test_the_quests_are_pointed_at_the_live_world_when_they_are_added():
    w = world()
    result = await run_chapter_plot(w, CAMPAIGN, medium_story(), 2, ScriptedCurator())
    assert result.names and all(m.entities == [] or all(e in result.names for e in m.entities) for m in result.milestones)
    live = world()
    live.add_entity("Something New", "npc")  # the live world moved on: ids are not the snapshot's any more
    live.add_entity("Another", "npc")
    result.milestones[0].entities = [next(i for i, n in result.names.items() if n == "Ashby")]
    result.rebind(live)
    assert result.milestones[0].entities == [live.find("Ashby").id]


def idle_session():
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, CAMPAIGN, world(), structure="medium", story=medium_story(), turn=30)
    return session


async def test_the_service_plans_the_chapter_in_the_background():
    session = idle_session()
    service = CuratorService(ScriptedCurator())
    assert service.plan_due(session)
    assert await service.run_if_due(session)
    story = session.state.story
    assert st.needs_plan(story) is None and len(story.in_chapter(2)) == 5
    assert [m.id for m in st.active(story)] == ["m06"] and story.last_progress_turn == 30
    assert not service.plan_due(session)
    assert not await service.run_if_due(session)  # and nothing else is due


async def test_a_failed_plan_is_retried_a_few_turns_later_and_not_every_turn():
    class Down(ScriptedCurator):
        async def plot(self, request):
            raise RuntimeError("down")

    session = idle_session()
    service = CuratorService(Down())
    assert not await service.run_if_due(session)
    assert session.state.story.in_chapter(2) == [] and not session.curating
    assert not service.plan_due(session)  # not on the very next turn
    session.state.turn += 3
    assert service.plan_due(session)


async def test_a_plan_for_a_chapter_that_has_since_changed_is_dropped():
    session = idle_session()
    service = CuratorService(ScriptedCurator())
    plan = await run_chapter_plot(session.state.world, CAMPAIGN, session.state.story, 2, ScriptedCurator())
    session.state.story.milestones += plan.milestones  # someone else planned it meanwhile
    count = len(session.state.story.milestones)
    session.pending_plans.append(plan)
    session.drain_pending()
    assert len(session.state.story.milestones) == count


async def test_planning_waits_while_a_turn_is_running():
    session = idle_session()
    session.busy = True
    assert not CuratorService(ScriptedCurator()).plan_due(session)


# ---- the curator reads quest progress from the narration ---------------------------------


def reporting(*reports, revealed=False):
    return FakeCurator(Extraction(quest_reports=list(reports), goal_revealed=revealed))


async def test_the_extract_step_is_told_the_open_quests_and_returns_reports():
    story = short_story()
    curator = reporting(("m1", "done", "Found the miller."), ("zz", "done", "x"), ("m2", "done", "not open yet"),
                        ("side", "won", "x"), ("side", "skipped", "  "), revealed=True)  # fmt: skip
    result = await run_pass(World(), convo("The miller confesses."), curator, story=story)
    request = curator.requests[0]
    assert [q[0] for q in request.quests] == ["m1", "side"] and "The Crown" in request.goal
    assert result.story_reports == [
        {"quests": [{"id": "m1", "status": "done", "outcome": "Found the miller."}], "goal_revealed": True}
    ]


async def test_no_story_no_reports():
    curator = reporting(("m1", "done", "x"))
    result = await run_pass(World(), convo("Hello."), curator)
    assert curator.requests[0].quests == [] and curator.requests[0].goal == "" and result.story_reports == []


async def test_a_known_goal_is_not_asked_about_again():
    story = short_story()
    story.goal.revealed = True
    curator = reporting(revealed=True)
    result = await run_pass(World(), convo("x"), curator, story=story)
    assert curator.requests[0].goal == "" and result.story_reports == []


def test_reports_are_applied_between_turns_and_the_ones_the_gm_made_are_skipped():
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, CAMPAIGN, world(), structure="short", story=short_story(), turn=9)
    scene = dispatch("set_scene", "t", {"story": {"quests": [{"id": "m1", "status": "done", "outcome": "GM said"}]}},
                     session.state)  # fmt: skip
    assert not scene.is_error
    session.pending_reports.append(
        {"quests": [{"id": "m1", "status": "done", "outcome": "curator says"}, {"id": "side", "status": "skipped",
                                                                               "outcome": "went round"}],
         "goal_revealed": True}  # fmt: skip
    )
    session.drain_pending()
    story = session.state.story
    assert story.milestone("m1").outcome == "GM said" and story.milestone("side").status == "skipped"
    assert story.goal.revealed and story.chapter == 1  # m2 was opened by m1 and is still open: no advance yet
    assert session.pending_reports == []


def test_reports_in_the_middle_of_a_turn_wait():
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, CAMPAIGN, world(), structure="short", story=short_story())
    session.busy = True
    session.pending_reports.append({"quests": [{"id": "m1", "status": "done", "outcome": "x"}]})
    session.drain_pending()
    assert session.state.story.milestone("m1").status == "active"


# ---- no major additions in chapters 2 and 3 -------------------------------------------------


def establish(state, **entity):
    return dispatch("establish", "t", {"entities": [entity]}, state)


def test_establish_refuses_major_additions_in_chapter_two():
    state = state_with_story(chapter=2)
    for entity in (
        {"name": "Iron Hand", "kind": "faction"},
        {"name": "The Old Faith", "kind": "concept"},
        {"name": "Karth", "kind": "location"},
        {"name": "Far Hold", "kind": "location", "parent": "The Vale"},
    ):
        out = establish(state, **entity)
        assert out.is_error and "major addition" in out.content, entity
    assert state.world.find("Karth") is None and state.world.find("Iron Hand") is None


def test_establish_allows_details_in_chapter_two():
    state = state_with_story(chapter=2)
    assert not establish(state, name="Old Wren", kind="npc").is_error
    out = establish(state, name="The Cellar", kind="location", parent="Ashby")
    assert not out.is_error and state.world.find("The Cellar").parent == state.world.find("Ashby").id


def test_chapter_one_and_endless_games_may_establish_anything():
    for state in (state_with_story(), GameState(Phase.ADVENTURE, {"setting": "x"}, World())):
        assert not establish(state, name="Iron Hand", kind="faction").is_error
    done = state_with_story(chapter=2)
    st.conclude(done.story, "e1", "x")
    assert not establish(done, name="Karth", kind="location").is_error


def test_a_refusal_changes_nothing_else_in_the_call():
    state = state_with_story(chapter=2)
    out = dispatch(
        "establish", "t",
        {"entities": [{"name": "Iron Hand", "kind": "faction"}], "facts": [{"text": "Wren is old.", "about": ["Ashby"]}]},
        state,
    )  # fmt: skip
    assert out.is_error and "Nothing was recorded" in out.content and not state.world.facts_about(state.world.find("Ashby").id)


async def test_the_expand_pass_drops_major_additions_and_caps_new_entities():
    w = World()
    vale = w.add_entity("The Vale", "location")
    ashby = w.add_entity("Ashby", "location", parent=vale.id)
    w.add_fact("Ashby is a market town.", [ashby.id])
    w.set_scene(ashby.id, [])
    story = short_story(chapter=2)
    offered = Extraction(
        entities=[
            EntityProposal("Iron Hand", "faction"),
            EntityProposal("New Province", "location"),
            EntityProposal("Old Wren", "npc"),
            EntityProposal("The Cellar", "location", parent="Ashby"),
            EntityProposal("The Deep Cellar", "location", parent="The Cellar"),
            EntityProposal("Far Hold", "location", parent="New Province"),
        ],
        facts=[FactProposal(f"{n} has a long history in the Vale.", [n, "Ashby"]) for n in
               ("Iron Hand", "New Province", "Old Wren", "The Cellar", "The Deep Cellar", "Far Hold")],
    )  # fmt: skip
    curator = FakeCurator(expansions=[offered])
    config = PassConfig(max_expand_entities=1, max_entities_per_call=10, max_facts_per_call=10)
    result = await run_pass(w, [], curator, config=config, story=story)
    added = [o.name for o in result.ops if isinstance(o, AddEntity)]
    assert added == ["Old Wren", "The Cellar", "The Deep Cellar"]
    assert any("major addition" in n for n in result.notes)
    # the same offer in chapter one is accepted whole (up to the pass cap)
    free = await run_pass(w, [], FakeCurator(expansions=[offered]), config=config, story=short_story())
    assert len([o for o in free.ops if isinstance(o, AddEntity)]) == 6


async def test_chapter_two_passes_add_at_most_a_few_entities():
    w = World()
    vale = w.add_entity("The Vale", "location")
    ashby = w.add_entity("Ashby", "location", parent=vale.id)
    w.add_fact("Ashby is a market town.", [ashby.id])
    w.set_scene(ashby.id, [])
    people = Extraction(
        entities=[EntityProposal(f"Person {i}", "npc") for i in range(6)],
        facts=[FactProposal(f"Person {i} lives near Ashby.", [f"Person {i}", "Ashby"]) for i in range(6)],
    )
    config = PassConfig(max_expand_entities=1, max_new_entities=8, max_entities_per_call=8, story_entities=3)
    result = await run_pass(w, [], FakeCurator(expansions=[people]), config=config, story=short_story(chapter=2))
    assert len([o for o in result.ops if isinstance(o, AddEntity)]) == 3


# ---- the whole game, with the scripted model -----------------------------------------------


def settings(tmp_path):
    return Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None)


def live(app):
    return app.state.sessions.get("default").state


def test_a_medium_game_plans_chapter_two_when_it_is_reached(tmp_path):
    app = create_app(settings(tmp_path))
    client = TestClient(app)
    chat(client, "structure medium")
    chat(client, "begin")
    state = live(app)
    assert len(state.story.milestones) == 5 and {m.chapter for m in state.story.milestones} == {1}
    state.story.chapter = 2  # as if chapter 1 had just ended
    state.story.goal.revealed = True
    chat(client, "echo on we go")
    state = live(app)
    assert len(state.story.in_chapter(2)) == 5 and st.active(state.story)
    assert state.story.chapter == 2
