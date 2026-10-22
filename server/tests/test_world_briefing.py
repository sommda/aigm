import pytest

from aigm.game import BRIEFING_CLOSE, BRIEFING_OPEN, Game
from aigm.llm.base import Completed, TextChunk
from aigm.llm.anthropic_client import AnthropicLLM
from aigm.llm.loop import run_turn
from aigm.models import MessageEnd
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.world import World, WorldTime
from aigm.world.briefing import build_briefing, time_of_day


@pytest.fixture
def w():
    world = World()
    region = world.add_entity("Thornwood", "location")
    town = world.add_entity("Ashby", "location", parent=region.id)
    mine = world.add_entity("Harrow Mine", "location", aliases=["the old mine"], parent=region.id)
    cellar = world.add_entity("Smugglers' Cellar", "location", parent=town.id)
    wren = world.add_entity("Wren", "npc", aliases=["the barmaid"])
    guild = world.add_entity("Thorn Guild", "faction")
    far = world.add_entity("Karth", "location")
    world.add_fact("The Harrow Mine was abandoned forty years ago.", [mine.id], aspect="history", disclosure="known")
    world.add_fact("The mine's lower gallery joins the cellar under Ashby.", [mine.id, cellar.id], aspect="secret")
    world.add_fact("Miners say lights move in the shaft at night.", [mine.id], disclosure="hinted")
    world.add_fact("Ashby lies a half-day's walk west of the Harrow Mine.", [town.id, mine.id], aspect="approach")
    world.add_fact("Wren secretly sells information to the Thorn Guild.", [wren.id, guild.id], aspect="motivation")
    world.add_fact("Wren pours drinks at the Rusty Flagon.", [wren.id], aspect="role", disclosure="known")
    world.add_fact("The Thorn Guild controls the toll road to Karth.", [guild.id, far.id])
    world.add_fact("Karth is a walled port city far to the south.", [far.id], disclosure="known")
    world.set_scene(mine.id, [wren.id])
    world.set_time(WorldTime(3, 14))
    return world


def test_empty_world_gives_no_briefing():
    assert build_briefing(World()) == ""


def test_time_of_day():
    assert [time_of_day(h) for h in (0, 5, 8, 12, 17, 21, 23)] == [
        "night", "dawn", "morning", "afternoon", "evening", "night", "night",
    ]  # fmt: skip


def test_briefing_has_clock_location_present_and_nearby(w):
    text = build_briefing(w)
    lines = text.splitlines()
    assert lines[0] == "Time: Day 3, 14:00 (afternoon)"
    assert lines[1] == "Location: Harrow Mine (in Thornwood)"
    assert "- [known] The Harrow Mine was abandoned forty years ago." in lines
    assert "- [GM only, not yet known to the player] The mine's lower gallery joins the cellar under Ashby." in lines
    assert "- [GM only: the player has heard only hints of this] Miners say lights move in the shaft at night." in lines
    assert "Present:" in lines and "Wren (npc, also called the barmaid)" in lines
    assert "- [GM only, not yet known to the player] Wren secretly sells information to the Thorn Guild." in lines
    assert "Nearby:" in lines
    # known facts come before hinted before hidden
    loc = [i for i, l in enumerate(lines) if l.startswith("- [") and "mine" in l.lower()][:3]
    assert "[known]" in lines[loc[0]] and "hints" in lines[loc[1]] and "not yet known" in lines[loc[2]]


def test_each_fact_is_shown_once_and_nearby_uses_one_liners(w):
    text = build_briefing(w)
    assert text.count("lower gallery joins the cellar") == 1  # also about the cellar, a nearby place
    nearby = text.split("Nearby:\n")[1].split("\nAlso relevant:")[0]
    assert "- Ashby: [known]" not in nearby
    assert "- Ashby" in nearby.splitlines()  # its only fact was already shown under the location
    assert "- Smugglers' Cellar" in nearby.splitlines() and "Karth" not in nearby and "Thornwood" not in nearby.split("\n")[0]


def test_a_nearby_place_with_its_own_facts_shows_the_best_one(w):
    w.add_fact("Ashby is reached by the old toll road through the Thornwood.", ["e002"], aspect="connections")
    w.add_fact("Ashby has about four hundred residents.", ["e002"], disclosure="known", aspect="layout")
    nearby = build_briefing(w).split("Nearby:\n")[1]
    assert "- Ashby: [GM only, not yet known to the player] Ashby is reached by the old toll road" in nearby


def test_relevant_facts_follow_the_conversation_but_never_leak_hidden_ones(w):
    assert "Karth" not in build_briefing(w)
    text = build_briefing(w, user_text="Tell me about Karth and the guild")
    assert "Also relevant:" in text
    assert "- [known] Karth is a walled port city far to the south." in text
    assert "controls the toll road" not in text  # hidden, outside the scene
    assert "Thorn Guild controls" not in text
    assert "Karth" in build_briefing(w, gm_text="The road leads on to Karth.")


def test_no_scene_still_gives_the_clock(w):
    w.scene.location, w.scene.present = None, []
    lines = build_briefing(w).splitlines()
    assert lines[:2] == ["Time: Day 3, 14:00 (afternoon)", "Location: not yet recorded"]


def test_budget_trims_low_priority_lines_but_keeps_the_header(w):
    full = build_briefing(w, budget_tokens=2000)
    small = build_briefing(w, user_text="Karth", budget_tokens=60)
    assert len(small) < len(full)
    assert small.splitlines()[:2] == full.splitlines()[:2]
    assert "Karth" not in small and "Nearby:" not in small
    tiny = build_briefing(w, budget_tokens=0)
    assert tiny.splitlines() == ["Time: Day 3, 14:00 (afternoon)", "Location: Harrow Mine (in Thornwood)"]


def test_budget_drops_everything_after_the_first_overflow(w):
    sizes = [len(build_briefing(w, budget_tokens=t)) for t in range(0, 400, 10)]
    assert sizes == sorted(sizes)


# ---- Game: injection ----------------------------------------------------------------------


def adventure_state(world):
    return GameState(Phase.ADVENTURE, {"setting": "x"}, world)


USER = {"role": "user", "content": [{"type": "text", "text": "I enter the mine."}]}


def test_request_messages_appends_notes_and_a_cache_breakpoint_without_touching_history(w):
    game = Game()
    history = [USER]
    sent = game.request_messages(adventure_state(w), history, "I enter the mine.")
    assert history == [USER] and "cache_control" not in USER["content"][0]  # nothing stored or mutated
    blocks = sent[-1]["content"]
    assert blocks[0] == {"type": "text", "text": "I enter the mine.", "cache_control": {"type": "ephemeral"}}
    assert blocks[1]["text"].startswith(BRIEFING_OPEN + "\nParty: level 1.\n\nTime:") and blocks[1]["text"].endswith(BRIEFING_CLOSE)
    assert len(blocks) == 2


def test_request_messages_after_tool_results_marks_the_last_result(w):
    results = {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "4", "is_error": False}],
    }
    asst = {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "roll_dice", "input": {}}]}
    sent = Game().request_messages(adventure_state(w), [USER, asst, results], "I enter the mine.")
    assert sent[-1]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent[-1]["content"][1]["text"].startswith(BRIEFING_OPEN)
    assert sent[:-1] == [USER, asst]


def test_no_notes_outside_the_adventure_or_with_an_empty_world(w):
    game = Game()
    assert game.request_messages(GameState(), [USER], "x") == [USER]
    assert game.request_messages(adventure_state(World()), [USER], "x") == [USER]
    state = GameState(Phase.SESSION_ZERO)
    assert game.briefing(state, "x", "") == ""


def test_briefing_budget_is_configurable(w):
    small = Game(briefing_tokens=1).briefing(adventure_state(w), "", "")
    assert "Nearby:" not in small and "Time:" in small


class Recorder:
    def __init__(self):
        self.requests = []

    async def stream(self, *, system, messages, tools):
        self.requests.append(messages)
        yield TextChunk("The shaft yawns before you.")
        yield Completed([{"type": "text", "text": "The shaft yawns before you."}], "end_turn")


async def test_the_loop_sends_notes_but_stores_only_the_conversation(w):
    session = Session("s")
    session.state = adventure_state(w)
    llm = Recorder()
    events = [e async for e in run_turn(session=session, user_text="I enter the mine.", llm=llm, game=Game(), max_iters=4)]
    assert isinstance(events[-1], MessageEnd)
    sent = llm.requests[0][-1]["content"]
    assert sent[-1]["text"].startswith(BRIEFING_OPEN) and "Harrow Mine" in sent[-1]["text"]
    assert [m["content"][0]["text"] for m in session.messages] == ["I enter the mine.", "The shaft yawns before you."]
    assert all(len(m["content"]) == 1 and "cache_control" not in m["content"][0] for m in session.messages)


async def test_the_next_turn_sees_the_previous_gm_message_when_matching(w):
    session = Session("s")
    session.state = adventure_state(w)
    llm = Recorder()
    game = Game()
    async for _ in run_turn(session=session, user_text="I look around.", llm=llm, game=game, max_iters=4):
        pass
    session.messages[-1]["content"][0]["text"] = "You could follow the road to Karth."
    async for _ in run_turn(session=session, user_text="Go on.", llm=llm, game=game, max_iters=4):
        pass
    assert "Karth is a walled port city" in llm.requests[1][-1]["content"][-1]["text"]


# ---- Anthropic request --------------------------------------------------------------------


def test_explicit_breakpoint_replaces_the_automatic_one(w):
    llm = AnthropicLLM(api_key="k", model="m", client=object())
    plain = llm.request_params("S", [USER], [])
    assert plain["cache_control"] == {"type": "ephemeral"}
    marked = Game().request_messages(adventure_state(w), [USER], "x")
    assert "cache_control" not in llm.request_params("S", marked, [])


def test_adventure_prompt_describes_the_notes_and_time_precision():
    prompt = Game().system(adventure_state(World()))
    assert "<world_notes>" in prompt and "GM only" in prompt and "say how much" in prompt
