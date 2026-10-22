"""What the GM sees and does in a story game (docs/STORY.md 8, 9, 10): prompts, tools, the briefing."""

import pytest
from fastapi.testclient import TestClient

from aigm import story as st
from aigm.app import create_app
from aigm.config import Settings
from aigm.game import Game
from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch, tool_schemas
from aigm.world import World
from tests.conftest import chat
from tests.test_story import short_story


def state_with_story(**kw):
    world = World()
    vale = world.add_entity("The Vale", "location")
    town = world.add_entity("Ashby", "location", parent=vale.id)
    world.set_scene(town.id, [])
    story = short_story(**kw)
    if story.milestone("m1"):
        story.milestone("m1").entities = [town.id]
    state = GameState(Phase.ADVENTURE, {"setting": "x"}, world, structure="short", story=story, turn=10)
    return state


def names(tools):
    return [t["name"] for t in tools]


def props(tools, name):
    return next(t for t in tools if t["name"] == name)["input_schema"]["properties"]


# ---- offered only to story games --------------------------------------------------------


def test_endless_games_see_no_story_tools_or_fields():
    tools = tool_schemas(phase=Phase.ADVENTURE)
    assert names(tools) == ["roll_dice", "recall", "establish", "set_scene", "award"]
    assert "story" not in props(tools, "set_scene")
    assert "report its progress" not in next(t for t in tools if t["name"] == "set_scene")["description"]


def test_story_games_get_end_story_and_the_story_field():
    tools = tool_schemas(phase=Phase.ADVENTURE, structured=True)
    assert names(tools) == ["roll_dice", "recall", "establish", "set_scene", "award", "end_story"]
    assert "story" in props(tools, "set_scene") and "goal_revealed" in str(props(tools, "set_scene")["story"])
    description = next(t for t in tools if t["name"] == "set_scene")["description"]
    assert description.startswith("Tell the world notes") and "report its progress" in description
    assert "story" not in [t["name"] for t in tool_schemas(phase=Phase.SESSION_ZERO, structured=True)]


def test_the_game_picks_tools_and_prompt_by_the_state():
    game = Game()
    endless = GameState(Phase.ADVENTURE, {"setting": "x"})
    story = state_with_story()
    assert "end_story" not in names(game.tools(endless)) and "end_story" in names(game.tools(story))
    assert "This game is a story" not in game.system(endless)
    assert game.system(story).endswith(PromptLibrary().system_parts(Phase.ADVENTURE, "dnd55e", True)[-1].text)
    assert "This game is a story" in game.system(story)
    unplanned = GameState(Phase.ADVENTURE, {"setting": "x"}, structure="short")
    assert game.system(unplanned) == game.system(endless)  # no plan yet: nothing to steer by


def test_the_story_prompt_is_kept_secret_in_its_own_words():
    text = PromptLibrary().system_prompt(Phase.ADVENTURE, structured=True)
    assert "Never quote it" in text and "end_story" in text and "never by refusing the player" in text


# ---- the briefing -----------------------------------------------------------------------


def block(state, turn=None, nudge=12):
    return st.briefing_block(state.story, state.world, state.turn if turn is None else turn, nudge)


def test_the_briefing_has_the_chapter_goal_and_active_quests():
    state = state_with_story()
    text = block(state)
    assert text.startswith("## Story (private)\nChapter 1 of 3, \"Ashby\": Learn the vale")
    assert "the player does NOT know yet: The Crown" in text and "report goal_revealed" in text
    assert "Level 5" in text and "[m1] Quest m1 (small; at/with Ashby): Do m1." in text
    assert "[side]" in text and "[m2]" not in text  # only what is open
    assert "Aim for party level" not in text  # the sample plan sets none


def test_it_is_part_of_the_world_notes_above_them():
    state = state_with_story()
    notes = Game().briefing(state, "hello", "")
    assert notes.startswith("<world_notes>\n## Story (private)") and "Time:" in notes and "Ashby" in notes
    assert "## Story" not in Game().briefing(GameState(Phase.ADVENTURE, {"setting": "x"}, state.world), "hi", "")


def test_chapter_two_forbids_major_additions_and_knows_the_goal():
    state = state_with_story(chapter=2)
    state.story.goal.revealed = True
    st.settle_ready(state.story)
    text = block(state)
    assert "The goal, which the player knows" in text and "No new regions, settlements, factions" in text
    assert "NOT know" not in text


def test_chapter_three_lists_the_endings_and_the_choices():
    state = state_with_story(chapter=3)
    state.story.goal.revealed = True
    state.story.choices = [{"turn": 4, "milestone": "m1", "note": "Spared the captain."}]
    text = block(state)
    assert "- e1: Freed. The goal is destroyed." in text and "Choices that matter for the ending: Spared" in text


def test_the_pace_line_follows_the_idle_turns():
    state = state_with_story()
    state.story.last_progress_turn = 10
    assert "Pace" not in block(state, turn=15)
    assert "5 turns" not in block(state, turn=15)
    assert "Pace: 12 turns without progress. Offer a concrete hook" in block(state, turn=22)
    assert "Bring a concrete consequence" in block(state, turn=34)


def test_chapter_one_nudges_toward_the_goal_as_it_nears_its_end():
    state = state_with_story()
    assert "learning the goal" not in block(state)
    st.report(state.story, "m1", "done", "x", 11)
    assert "make the clues plainer" not in block(state)  # one of two required quests is done
    state.story.milestones.append(st.Milestone("x", 1, "Extra", "Do x.", status="done"))
    assert "make the clues plainer" in block(state)  # two of three
    st.report(state.story, "m2", "done", "y", 12)
    assert "Only the goal's revelation is left" in block(state)


def test_an_unplanned_chapter_and_a_finished_story():
    state = state_with_story(chapter=2, milestones=[])
    state.story.goal.revealed = True
    assert "not planned yet" in block(state)
    done = state_with_story()
    st.conclude(done.story, "e1", "It is over.")
    assert "The story has ended (Freed)" in block(done) and "Chapter" not in block(done)
    assert st.briefing_block(st.Story("short"), World(), 1) == ""


# ---- reporting progress -----------------------------------------------------------------


def scene(state, **fields):
    return dispatch("set_scene", "t", fields, state)


def test_a_finished_quest_is_reported_through_set_scene():
    state = state_with_story()
    out = scene(state, story={"quests": [{"id": "m1", "status": "done", "outcome": " Found the miller. "}]})
    assert not out.is_error and "m1 is now done" in out.content and "Now active: m2" in out.content
    assert state.story.milestone("m1").outcome == "Found the miller." and state.story.last_progress_turn == 10
    assert state.world.scene.location is not None  # the scene itself is untouched


def test_the_goal_being_learned_can_end_chapter_one():
    state = state_with_story()
    scene(state, story={"quests": [{"id": "m1", "status": "done", "outcome": "a"}]})
    out = scene(state, story={"quests": [{"id": "m2", "status": "done", "outcome": "b"}]})
    assert state.story.chapter == 1 and "Chapter 2" not in out.content  # the goal is still unknown
    out = scene(state, story={"goal_revealed": True})
    assert state.story.chapter == 2 and state.story.goal.revealed
    assert 'Chapter 2 begins ("The road")' in out.content and "The player now knows the goal" in out.content


def test_finishing_the_last_quest_with_the_goal_known_advances_in_one_call():
    state = state_with_story()
    out = scene(
        state,
        story={
            "goal_revealed": True,
            "quests": [{"id": "m1", "status": "done", "outcome": "a"}, ],
        },
    )
    assert state.story.chapter == 1  # m2 is still open
    out = scene(state, story={"quests": [{"id": "m2", "status": "done", "outcome": "b"}]})
    assert state.story.chapter == 2 and 'Chapter 2 begins' in out.content and "m3" in out.content


@pytest.mark.parametrize(
    "story, message",
    [
        ({"quests": [{"id": "zz", "status": "done", "outcome": "x"}]}, "no milestone"),
        ({"quests": [{"id": "m2", "status": "done", "outcome": "x"}]}, "pending"),
        ({"quests": [{"id": "m1", "status": "won", "outcome": "x"}]}, "status"),
        ({"quests": [{"id": "m1", "status": "done", "outcome": ""}]}, "outcome"),
        ({"quests": ["m1"]}, "object"),
        ({"quests": "m1"}, "list"),
        ({"goal_revealed": "yes"}, "true or false"),
        ("done", "object"),
    ],
)
def test_bad_reports_are_refused_and_change_nothing(story, message):
    state = state_with_story()
    before = state.story.to_dict()
    out = scene(state, story=story)
    assert out.is_error and message in out.content and state.story.to_dict() == before


def test_a_call_is_all_or_nothing():
    state = state_with_story()
    before = (state.story.to_dict(), state.world.scene.location)
    out = scene(state, location="Nowhere", story={"quests": [{"id": "m1", "status": "done", "outcome": "x"}]})
    assert out.is_error and (state.story.to_dict(), state.world.scene.location) == before
    out = scene(state, location="Ashby", story={"quests": [{"id": "m1", "status": "done", "outcome": "x"}, {"id": "no"}]})
    assert out.is_error and state.story.to_dict() == before[0]


def test_an_endless_game_has_nothing_to_report():
    state = GameState(Phase.ADVENTURE, {"setting": "x"}, state_with_story().world)
    out = scene(state, story={"goal_revealed": True})
    assert out.is_error and "no story" in out.content


# ---- ending the story -------------------------------------------------------------------


def end(state, **fields):
    return dispatch("end_story", "t", {"ending": "e1", "epilogue": "The vale is free.", **fields}, state)


def at_the_climax():
    state = state_with_story(chapter=3, milestones=[])
    state.story.goal.revealed = True
    state.story.milestones = [st.Milestone("f1", 3, "Final", "Do it.", status="done")]
    return state


def test_the_story_ends_at_the_climax():
    state = at_the_climax()
    out = end(state)
    assert not out.is_error and "offer to keep playing" in out.content
    assert state.story.concluded and state.story.ending == "e1" and state.story.epilogue == "The vale is free."
    assert end(state).is_error  # only once


def test_a_failed_final_quest_still_allows_an_ending():
    state = at_the_climax()
    state.story.milestone("f1").status = "failed"
    assert not end(state, ending="end_custom").is_error


def test_the_story_cannot_end_early_or_with_a_made_up_ending():
    early = state_with_story()
    out = end(early)
    assert out.is_error and "not at its end" in out.content and not early.story.concluded
    open_quest = at_the_climax()
    open_quest.story.milestone("f1").status = "active"
    assert end(open_quest).is_error
    wrong = at_the_climax()
    out = end(wrong, ending="end99")
    assert out.is_error and "e1, e2, end_custom" in out.content and not wrong.story.concluded
    assert end(at_the_climax(), epilogue="  ").is_error


def test_a_fallen_party_can_end_the_story_at_any_time():
    state = state_with_story()
    assert not end(state, ending="e2", party_defeated=True).is_error and state.story.concluded


def test_end_story_does_nothing_in_an_endless_game():
    out = dispatch("end_story", "t", {"ending": "e1", "epilogue": "x"}, GameState(Phase.ADVENTURE))
    assert out.is_error and "no story" in out.content


# ---- the debug context view ---------------------------------------------------------------


def test_the_context_viewer_shows_the_story_section(tmp_path):
    settings = Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "s", debug=True, _env_file=None)
    app = create_app(settings)
    client = TestClient(app)
    chat(client, "structure short")
    chat(client, "begin")
    body = client.get("/debug/context").json()

    def find(nodes, id):
        for n in nodes:
            if n["id"] == id:
                return n
            found = find(n.get("children", []), id)
            if found:
                return found

    briefing = find(body["sections"], "briefing")
    assert [c["title"] for c in briefing["children"]][:3] == ["Party", "Story", "Clock"]
    assert "This game is a story" in str(find(body["sections"], "system"))
