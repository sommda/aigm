"""The plotter: a story plan held to the rules, and put into a new game (docs/STORY.md 5)."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from aigm import story as st
from aigm.app import create_app
from aigm.config import Settings
from aigm.world import World
from aigm.world.curator import (
    ChapterProposal,
    CuratorError,
    EndingProposal,
    EntityProposal,
    FactProposal,
    PlotProposal,
    PlotRequest,
    QuestProposal,
)
from aigm.world.plot import chapters_to_plan, run_plot
from aigm.world.scripted import ScriptedCurator
from tests.conftest import chat
from tests.test_session_zero import GOOD

CAMPAIGN = {"setting": "The Vale: a river valley.", "opening": "Dusk at Ashby.", "level": 2,
            "party": [{"name": "Wren", "sheet": "A ranger."}], "gm_notes": ""}  # fmt: skip


def world():
    w = World()
    vale = w.add_entity("The Vale", "location")
    w.add_entity("Ashby", "location", parent=vale.id)
    w.add_fact("The Vale lies along a slow river.", [vale.id], disclosure="known")
    return w


async def plot(length, curator=None, w=None):
    return await run_plot(w or world(), CAMPAIGN, length, curator or ScriptedCurator())


# ---- a good plan --------------------------------------------------------------------------


@pytest.mark.parametrize("length, chapters", [("short", {1, 2, 3}), ("medium", {1}), ("long", {1})])
async def test_the_plan_covers_the_chapters_the_length_plans_now(length, chapters):
    result = await plot(length)
    story = result.story
    assert story.length == length and {m.chapter for m in story.milestones} == chapters
    assert st.validate_plan(story) == []
    low = st.LENGTHS[length].quests[0]
    assert len(story.in_chapter(1)) == low
    assert len(story.chapters) == 3 and story.chapter == 1 and not story.goal.revealed
    assert [m.id for m in st.active(story)] == ["m01"]  # the first quest is open, the rest wait
    assert chapters_to_plan(length) == tuple(sorted(chapters))


async def test_the_goal_and_its_cast_are_put_into_the_world_hidden():
    w = world()
    result = await plot("short", w=w)
    assert w.find("The Sunken Seal") is None  # the world given is not changed
    from aigm.world.ops import apply_ops

    apply_ops(w, result.ops)
    seal = w.find("The Sunken Seal")
    assert seal is not None and w.entity(seal.parent).name == "The Vale"
    facts = w.facts_about(seal.id)
    assert facts and all(f.disclosure == "hidden" for f in facts)
    assert result.story.goal.entities == [seal.id]
    assert all(m.entities == [seal.id] for m in result.story.milestones)  # ids from the world they were planned for


async def test_the_plan_is_numbered_by_the_server():
    story = (await plot("short")).story
    assert [m.id for m in story.milestones] == [f"m0{i}" for i in range(1, 7)]
    assert story.milestone("m02").requires == ["m01"] and story.milestone("m03").requires == ["m02"]
    assert [e.id for e in story.endings] == ["end1", "end2"]


# ---- holding the plotter to the rules -----------------------------------------------------


class Fixing(ScriptedCurator):
    """Plots badly the first time, then as the script does."""

    def __init__(self, break_it):
        super().__init__()
        self.break_it, self.requests = break_it, []

    async def plot(self, request: PlotRequest) -> PlotProposal:
        self.requests.append(request)
        out = await super().plot(request)
        if len(self.requests) == 1 or self.always:
            self.break_it(out)
        return out

    always = False


def dead_end(out):
    out.quests[0].requires = [out.quests[1].key]  # a cycle with the second quest


async def test_a_broken_plan_is_sent_back_once_with_the_reasons():
    curator = Fixing(dead_end)
    result = await plot("short", curator)
    assert result.story is not None and len(curator.requests) == 2
    assert curator.requests[0].feedback == []
    assert any("never become available" in x for x in curator.requests[1].feedback)


async def test_a_plan_that_stays_broken_is_an_error():
    curator = Fixing(dead_end)
    curator.always = True
    with pytest.raises(CuratorError, match="broke the rules"):
        await plot("short", curator)
    assert len(curator.requests) == 2


@pytest.mark.parametrize(
    "break_it, message",
    [
        (lambda o: setattr(o.quests[0], "requires", ["nope"]), "requires 'nope'"),
        (lambda o: setattr(o.quests[0], "scale", "large"), "does not fit a short game"),
        (lambda o: o.endings.clear(), "endings"),
        (lambda o: o.chapters.pop(), "three chapters"),
        (lambda o: setattr(o, "goal_title", ""), "no goal"),
        (lambda o: [setattr(q, "chapter", 1) for q in o.quests], "chapter 1 has 6"),
        (lambda o: setattr(o.quests[1], "key", o.quests[0].key), "unique"),
        (lambda o: setattr(o.quests[0], "brief", ""), "title and a brief"),
    ],
)
async def test_each_rule_is_reported(break_it, message):
    curator = Fixing(break_it)
    curator.always = True
    with pytest.raises(CuratorError) as err:
        await plot("short", curator)
    assert message in str(err.value) or any(message in x for x in curator.requests[-1].feedback)


async def test_a_plan_for_a_missing_chapter_is_refused():
    def drop_chapter_three(out):
        out.quests[:] = [q for q in out.quests if q.chapter != 3]

    curator = Fixing(drop_chapter_three)
    curator.always = True
    with pytest.raises(CuratorError, match="chapter 3"):
        await plot("short", curator)


async def test_later_chapters_of_a_long_game_are_left_for_later():
    class Greedy(ScriptedCurator):
        async def plot(self, request):
            out = await super().plot(replace(request, chapters=(1, 2, 3)))
            return out

    story = (await plot("long", Greedy())).story
    assert {m.chapter for m in story.milestones} == {1}


async def test_facts_that_break_the_independence_rules_are_dropped():
    class Leaky(ScriptedCurator):
        async def plot(self, request):
            out = await super().plot(request)
            out.facts += [
                FactProposal("The party will find the Seal.", ["The Sunken Seal", "The Vale"]),
                FactProposal("Wren is the seal's last keeper.", ["The Sunken Seal"]),
            ]
            return out

    w = world()
    result = await plot("short", Leaky(), w)
    from aigm.world.ops import apply_ops

    apply_ops(w, result.ops)
    texts = [f.text for f in w.facts.values()]
    assert not any("party" in t or "Wren" in t for t in texts)
    assert any("dropped plot fact" in n for n in result.notes)


async def test_unknown_entity_names_in_the_plan_are_left_out_not_fatal():
    class Vague(ScriptedCurator):
        async def plot(self, request):
            out = await super().plot(request)
            out.quests[0].entities = ["Nowhere At All"]
            return out

    result = await plot("short", Vague())
    assert result.story.milestone("m01").entities == []
    assert any("Nowhere At All" in n for n in result.notes)


async def test_a_curator_that_cannot_plot_is_an_error():
    class Plain:
        pass

    with pytest.raises(CuratorError, match="cannot plan"):
        await run_plot(world(), CAMPAIGN, "short", Plain())
    with pytest.raises(ValueError):
        await plot("epic")


# ---- the strength gap ---------------------------------------------------------------------


def long_story():
    s = st.Story(
        "long",
        goal=st.Goal("G", "g", [], False, "Level 9"),
        endings=[st.Ending("a", "A", "x"), st.Ending("b", "B", "y")],
    )
    for chapter in (1, 2, 3):
        for i in range(10):
            req = [f"c{chapter}{i - 1}"] if i else ([f"c{chapter - 1}9"] if chapter > 1 else [])
            s.milestones.append(
                st.Milestone(f"c{chapter}{i}", chapter, "T", "B", scale="large", requires=req, gives="a boon")
            )
    return s


def test_a_long_plan_that_builds_nothing_is_refused():
    s = long_story()
    assert st.validate_plan(s) == []
    for m in s.milestones:
        m.gives = ""
    assert any("builds up the party" in p for p in st.validate_plan(s))
    s.goal.min_strength = ""
    assert any("min_strength" in p for p in st.validate_plan(s))


def test_a_short_plan_may_have_no_gap():
    s = long_story()
    s.length, s.goal.min_strength = "short", ""
    s.milestones = [replace(m, scale="small") for m in s.milestones[:6]]
    for i, m in enumerate(s.milestones):
        m.chapter, m.gives, m.requires = i // 2 + 1, "", s.milestones[i - 1:i] and [s.milestones[i - 1].id] or []
    assert not [p for p in st.validate_plan(s) if "strength" in p or "builds" in p]


# ---- a new game ---------------------------------------------------------------------------


def settings(tmp_path, **kw):
    return Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None, **kw)


def begin(client, mode):
    chat(client, f"structure {mode}")
    return chat(client, "begin")


def live_state(app):
    return app.state.sessions.get("default").state


def test_a_story_game_is_planned_while_the_world_is_built(tmp_path):
    app = create_app(settings(tmp_path))
    client = TestClient(app)
    events = begin(client, "short")
    messages = [d["message"] for n, d in events if n == "status" and d.get("stage") == "world"]
    assert "Planning the story..." in messages and messages.index("Planning the story...") < len(messages) - 1
    state = live_state(app)
    assert state.structure == "short" and state.story is not None and state.story.length == "short"
    assert state.world.find("The Sunken Seal") is not None
    assert st.active(state.story)


def test_an_endless_game_is_not_planned(tmp_path):
    app = create_app(settings(tmp_path))
    events = begin(TestClient(app), "endless")
    assert not any(d.get("message") == "Planning the story..." for n, d in events if n == "status")
    assert live_state(app).story is None and app.state.curator.curator.calls.count("plot") == 0


def test_the_plan_is_saved_with_the_game(tmp_path):
    app = create_app(settings(tmp_path))
    client = TestClient(app)
    begin(client, "medium")
    client.put("/history/g/save")
    chat(client, "echo more")
    client.post("/history/g/restore")
    state = live_state(app)
    assert state.structure == "medium" and state.story.length == "medium" and len(state.story.milestones) == 5


def test_a_failed_plan_discards_the_turn(tmp_path):
    class Broken(ScriptedCurator):
        async def plot(self, request):
            raise RuntimeError("boom")

    from aigm.world.service import CuratorService

    app = create_app(settings(tmp_path), curator=CuratorService(Broken()))
    client = TestClient(app)
    chat(client, "structure long")
    events = chat(client, "begin")
    error = next(d for n, d in events if n == "error")
    assert error["retryable"] and "story could not be planned" in error["message"]
    assert client.get("/chat/history").json()["phase"] == "session_zero"
    assert live_state(app).structure == "long" and live_state(app).story is None


async def test_without_a_curator_a_story_becomes_an_endless_game():
    from aigm.session.store import Session
    from tests.test_session_zero import BeginThenMaybeFail, collect

    session = Session("s")
    session.state.structure = "long"
    await collect(session, BeginThenMaybeFail(fail=False))
    assert session.state.phase.value == "adventure" and session.state.structure == "endless"
    assert session.state.story is None


# ---- the model-driven plotter ---------------------------------------------------------------


def plot_reply():
    return {
        "goal_title": "Break the Seal", "goal_summary": "The Seal binds the river.", "min_strength": "Level 5",
        "goal_entities": ["The Seal"],
        "chapters": [{"title": "One", "purpose": "p", "target_level": 3}, {"title": "Two", "purpose": "p", "target_level": None},
                     {"title": "Three", "purpose": "p", "target_level": 7}],
        "quests": [{"key": "q1", "chapter": 1, "title": "T", "brief": "B", "scale": "small", "gives": "g",
                    "requires": [], "required": True, "entities": ["Ashby"]}],
        "endings": [{"title": "Free", "when": "The Seal breaks."}],
        "entities": [{"name": "The Seal", "kind": "location", "aliases": [], "parent": "The Vale"}],
        "facts": [{"text": "The Seal was made long ago.", "about": ["The Seal"], "aspect": None}],
    }  # fmt: skip


async def test_the_model_plotter_reads_its_answer():
    from tests.test_world_curator import curator

    cur, messages = curator(plot_reply(), expand_model="the-big-one")
    request = PlotRequest("short", "A vale.", "Dusk.", 2, [("Wren", "A ranger.")], "", [], [], (1, 2, 3), (2, 3), ("small",))
    proposal = await cur.plot(request)
    assert proposal.goal_title == "Break the Seal" and proposal.goal_entities == ["The Seal"]
    assert [c.target_level for c in proposal.chapters] == [3, None, 7]
    quest = proposal.quests[0]
    assert (quest.key, quest.chapter, quest.scale, quest.required, quest.entities) == ("q1", 1, "small", True, ["Ashby"])
    assert proposal.entities[0].parent == "The Vale" and proposal.facts[0].disclosure == "hidden"
    call = messages.calls[0]
    assert call["model"] == "the-big-one" and "plotter" in call["system"][0]["text"]
    assert call["output_config"]["format"]["schema"]["required"][0] == "goal_title"


def test_the_plot_schema_obeys_the_structured_output_limits():
    from tests.test_world_curator import walk
    from aigm.world.anthropic_curator import PLOT_SCHEMA

    walk(PLOT_SCHEMA)


def test_the_plot_request_is_rendered_for_the_model():
    from aigm.world.render import render_plot

    w = world()
    request = PlotRequest(
        "medium", "A vale.", "Dusk at Ashby.", 2, [("Wren", "A ranger.")], "The miller lies.",
        list(w.entities.values()), list(w.facts.values()), (1,), (5, 6), ("medium", "small"), ["bad cycle"],
    )  # fmt: skip
    text = render_plot(request)
    for needle in ("medium: 5 to 6 required quests per chapter", "Dusk at Ashby.", "### Wren", "The miller lies.",
                   "Ashby (location", "[known] The Vale lies along a slow river.", "chapter(s)\n1.", "- bad cycle"):  # fmt: skip
        assert needle in text, needle


async def test_the_plotter_is_shown_the_whole_world_so_far():
    curator = Fixing(lambda out: None)
    await plot("short", curator)
    request = curator.requests[0]
    assert [e.name for e in request.entities] == ["The Vale", "Ashby"]
    assert [f.text for f in request.facts] == ["The Vale lies along a slow river."]


async def test_a_person_the_plotter_places_inside_a_location_is_kept():
    class Villain(ScriptedCurator):
        async def plot(self, request):
            out = await super().plot(request)
            out.entities.append(EntityProposal("Captain Vane", "npc", parent="The Sunken Seal"))
            out.facts.append(FactProposal("Captain Vane was bound to the Seal long ago.", ["Captain Vane", "The Sunken Seal"]))
            return out

    w = world()
    result = await plot("short", Villain(), w)
    from aigm.world.ops import apply_ops

    apply_ops(w, result.ops)
    vane = w.find("Captain Vane")
    assert vane is not None and vane.parent is None and w.facts_about(vane.id)
