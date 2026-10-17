"""The request description: one object from which the real request is built, so a viewer cannot drift from it."""

import pytest

from aigm.game import Game
from aigm.llm.base import Completed, TextChunk
from aigm.llm.loop import run_turn
from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.world import World

CAMPAIGN = {"setting": "x", "gm_notes": "The mist lies."}
USER = {"role": "user", "content": [{"type": "text", "text": "I enter the mine."}]}


@pytest.fixture
def world():
    w = World()
    mine = w.add_entity("Harrow Mine", "location")
    w.add_fact("The Harrow Mine was abandoned forty years ago.", [mine.id], aspect="history", disclosure="known")
    w.set_scene(mine.id, [])
    return w


class RecordingLLM:
    """Records exactly what the loop hands the model client."""

    def __init__(self):
        self.calls = []

    async def stream(self, *, system, messages, tools):
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        yield TextChunk("ok")
        yield Completed(content=[{"type": "text", "text": "ok"}], stop_reason="end_turn")


def test_system_prompt_is_the_parts_joined_in_order():
    lib = PromptLibrary()
    for phase in Phase:
        parts = lib.system_parts(phase)
        assert "\n\n".join(p.text for p in parts) == lib.system_prompt(phase)
    sources = [p.source for p in lib.system_parts(Phase.ADVENTURE)]
    assert sources[0] == "system/common/01_role.md"
    assert sources.index("system/common/04_formatting.md") < sources.index("system/adventure/01_role.md")
    assert all(s.endswith(".md") and s.startswith("system/") for s in sources)


def test_override_files_keep_their_place_and_source(tmp_path):
    (tmp_path / "system" / "adventure").mkdir(parents=True)
    (tmp_path / "system" / "adventure" / "05_extra.md").write_text("Extra rule.\n<!-- note -->")
    (tmp_path / "system" / "common").mkdir()
    (tmp_path / "system" / "common" / "01_role.md").write_text("You are a PIRATE GM.")
    parts = PromptLibrary(tmp_path).system_parts(Phase.ADVENTURE)
    assert parts[0].source == "system/common/01_role.md" and parts[0].text == "You are a PIRATE GM."
    assert parts[-1].source == "system/adventure/05_extra.md" and parts[-1].text == "Extra rule."


def test_gm_notes_are_a_part_only_when_the_world_is_empty(world):
    game = Game()
    fallback = game.system_parts(GameState(Phase.ADVENTURE, CAMPAIGN))
    assert fallback[-1].source == "templates/gm_notes.md" and "The mist lies." in fallback[-1].text
    assert game.system_parts(GameState(Phase.ADVENTURE, CAMPAIGN, world)) == game.system_parts(GameState(Phase.ADVENTURE))
    assert game.system(GameState(Phase.ADVENTURE, CAMPAIGN)).endswith(fallback[-1].text)


def test_description_flattens_to_the_request_pieces(world):
    game = Game()
    state = GameState(Phase.ADVENTURE, CAMPAIGN, world)
    description = game.describe(state, [USER], "I enter the mine.")
    assert description.system == game.system(state)
    assert description.tools == game.tools(state)
    assert description.history == [USER]
    assert description.briefing.startswith("<world_notes>")
    assert description.messages == game.request_messages(state, [USER], "I enter the mine.")
    assert description.messages[-1]["content"][-1]["text"] == description.briefing
    assert USER["content"] == [{"type": "text", "text": "I enter the mine."}]  # the stored message is untouched


def test_no_briefing_means_the_stored_messages_are_sent_as_they_are():
    description = Game().describe(GameState(Phase.SESSION_ZERO), [USER], "hi")
    assert description.briefing == "" and description.messages is description.history


@pytest.mark.parametrize("phase", [Phase.SESSION_ZERO, Phase.ADVENTURE])
@pytest.mark.parametrize("with_world", [False, True])
async def test_the_loop_sends_exactly_what_the_description_says(phase, with_world, world):
    game = Game()
    state = GameState(phase, CAMPAIGN if phase is Phase.ADVENTURE else None, world if with_world else World())
    session = Session("s")
    session.state = state
    llm = RecordingLLM()
    async for _ in run_turn(session=session, user_text="I enter the mine.", llm=llm, game=game, max_iters=4):
        pass
    [sent] = llm.calls
    staged = [{"role": "user", "content": [{"type": "text", "text": "I enter the mine."}]}]
    expected = game.describe(state, staged, "I enter the mine.")
    assert sent["system"] == expected.system
    assert sent["tools"] == expected.tools
    assert sent["messages"] == expected.messages
    assert ("<world_notes>" in str(sent["messages"])) == (phase is Phase.ADVENTURE and with_world)
