import json

from aigm.game import Game
from aigm.llm.base import Completed, LLMError, TextChunk
from aigm.llm.loop import run_turn
from aigm.models import ErrorEvent, MessageEnd, PhaseChange
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.tools import dispatch, tool_schemas
from tests.conftest import chat, names, reply_text

SETTING = "The Misty Fens: a gritty, haunted marshland of drowned villages, smugglers and bog-witches. " * 4
BACKGROUND = "A fen-born smuggler who knows the Drowned Lantern inn and the marsh roads, and is wary of the baron."
APPEARANCE = "A slight elf in her twenties with cropped black hair, a pale scar through the left eyebrow and a dark hooded coat."
SHEET = "Elf rogue, Criminal background, level 3. STR 8 DEX 17 CON 12 INT 13 WIS 14 CHA 12. HP 21, AC 15. Shortbow, rapier, thieves' tools. Wry and watchful, and always the first to spot a trap or a lie."
GOOD = {
    "confirmed": True,
    "setting": SETTING,
    "opening": "The party arrives at the Drowned Lantern inn at dusk, just as a terrible scream comes from the cellar below.",
    "level": 3,
    "party": [{"name": "Ann", "sheet": SHEET, "background": BACKGROUND, "appearance": APPEARANCE}],
}


def state_of(client):
    body = client.get("/chat/history").json()
    return body["phase"], body["campaign"]


# ---- the phase over the API --------------------------------------------------------------


def test_new_session_starts_in_session_zero(client):
    assert state_of(client) == ("session_zero", None)
    events = chat(client, "hello")
    assert events[0][1]["phase"] == "session_zero"
    assert events[-1][1]["phase"] == "session_zero"
    assert "Session 0" in reply_text(events)


def test_begin_switches_to_adventure_within_the_turn(client):
    events = chat(client, "begin")
    calls = [d["name"] for n, d in events if n == "tool_call"]
    assert calls == ["set_structure", "begin_adventure"]  # the script picks an endless game when none was chosen
    change = next(d for n, d in events if n == "phase_change")
    assert change == {"previous": "session_zero", "phase": "adventure"}
    order = names(events)
    assert order.index("tool_call") < order.index("text", order.index("tool_call")) < order.index("phase_change")
    assert order[-2:] == ["phase_change", "message_end"]  # announced once the turn has committed
    assert "The adventure begins" in reply_text(events)  # the opening scene, in the same turn
    assert events[-1][0] == "message_end" and events[-1][1]["phase"] == "adventure"
    phase, campaign = state_of(client)
    assert phase == "adventure" and campaign["level"] == 1 and campaign["gm_notes"]
    # Session 0 is replaced by one GM entry (the campaign record), then the opening scene
    msgs = client.get("/chat/history").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"][0]["text"].startswith("[System: Session 0 is complete")
    record = msgs[1]["content"][0]["text"]
    assert "Test Marches" in record and "Test Hero" in record and "Rusty Flagon" in record
    assert "spy" not in record  # private notes stay out of the visible history
    assert not any(b["type"] in ("tool_use", "tool_result") for m in msgs for b in m["content"])
    assert msgs[2]["content"][0]["text"].startswith("[System: The adventure begins")
    assert "The adventure begins" in msgs[3]["content"][0]["text"]


def test_after_begin_the_game_stays_in_adventure(client):
    chat(client, "begin")
    assert "Adventure" in reply_text(chat(client, "hello"))
    events = chat(client, "begin")  # no way back, and begin_adventure is no longer offered
    assert "already begun" in reply_text(events)
    assert "phase_change" not in names(events)
    assert state_of(client)[0] == "adventure"


def test_new_game_returns_to_session_zero(client):
    chat(client, "begin")
    body = client.post("/chat/new").json()
    assert body["phase"] == "session_zero"
    assert state_of(client) == ("session_zero", None)


# ---- save / restore carry the state ------------------------------------------------------


def test_save_in_session_zero_and_restore(client):
    chat(client, "echo planning")
    saved = client.put("/history/s0/save").json()
    assert saved["phase"] == "session_zero"
    chat(client, "begin")
    assert state_of(client)[0] == "adventure"
    restored = client.post("/history/s0/restore").json()
    assert restored["phase"] == "session_zero"
    assert state_of(client) == ("session_zero", None)
    assert "Session 0" in reply_text(chat(client, "hello"))  # and play continues there


def test_save_after_begin_keeps_the_campaign(client, settings):
    chat(client, "begin")
    client.put("/history/adv/save")
    chat(client, "echo more")
    client.post("/chat/new")
    assert state_of(client)[0] == "session_zero"
    info = client.get("/history/adv").json()
    assert info["phase"] == "adventure"
    assert [h["phase"] for h in client.get("/history").json()["histories"]] == ["adventure"]
    client.post("/history/adv/restore")
    phase, campaign = state_of(client)
    assert phase == "adventure" and len(campaign["party"]) == 1 and "Rusty Flagon" in campaign["opening"]
    assert json.loads((settings.save_dir / "adv.json").read_text())["version"] == 10


def test_old_saves_without_state_load_as_adventure(client, settings):
    settings.save_dir.mkdir(parents=True)
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
    ]
    (settings.save_dir / "old.json").write_text(
        json.dumps({"version": 1, "name": "old", "saved_at": "2026-01-01T00:00:00Z", "messages": messages})
    )
    assert client.get("/history/old").json()["phase"] == "adventure"
    assert client.post("/history/old/restore").json()["phase"] == "adventure"
    assert state_of(client) == ("adventure", None)
    assert "Adventure" in reply_text(chat(client, "hello"))


def test_corrupt_state_in_a_save_is_rejected(client, settings):
    settings.save_dir.mkdir(parents=True)
    base = {"version": 2, "name": "x", "saved_at": "2026-01-01T00:00:00Z", "messages": []}
    for bad in ({"phase": "nope"}, {"phase": "session_zero", "campaign": {"a": 1}}, {"phase": "adventure", "campaign": 5}):
        (settings.save_dir / "x.json").write_text(json.dumps({**base, **bad}))
        assert client.post("/history/x/restore").status_code == 422
    assert state_of(client) == ("session_zero", None)  # failed restores change nothing


# ---- the tool ------------------------------------------------------------------------------


def test_tools_offered_depend_on_phase():
    zero = [t["name"] for t in tool_schemas(phase=Phase.SESSION_ZERO)]
    adventure = [t["name"] for t in tool_schemas(phase=Phase.ADVENTURE)]
    assert zero == ["roll_dice", "set_ruleset", "set_structure", "begin_adventure"]
    assert adventure == ["roll_dice", "recall", "establish", "set_scene", "update_character", "set_combat", "set_motive", "social_check", "award"]


def test_begin_adventure_sets_state():
    state = GameState(structure="endless")
    out = dispatch("begin_adventure", "t", dict(GOOD, gm_notes="  secret  "), state)
    assert not out.is_error
    assert state.phase is Phase.ADVENTURE
    assert state.campaign == {
        "setting": SETTING.strip(), "opening": GOOD["opening"], "level": 3, "gm_notes": "secret",
        "party": [{"name": "Ann", "sheet": SHEET, "background": BACKGROUND, "appearance": APPEARANCE}],
    }


def member(**kw):
    return {"name": "Bo", "sheet": SHEET, "background": BACKGROUND, "appearance": APPEARANCE, **kw}


def test_begin_adventure_rejects_thin_or_bad_input_without_changing_state():
    bad = {
        "unconfirmed": {**GOOD, "confirmed": False},
        "no confirmed": {k: v for k, v in GOOD.items() if k != "confirmed"},
        "blank setting": {**GOOD, "setting": "  "},
        "thin setting": {**GOOD, "setting": "A fantasy world."},
        "thin opening": {**GOOD, "opening": "An inn."},
        "no opening": {k: v for k, v in GOOD.items() if k != "opening"},
        "level 0": {**GOOD, "level": 0},
        "level 21": {**GOOD, "level": 21},
        "bool level": {**GOOD, "level": True},
        "party string": {**GOOD, "party": "Ann the rogue"},
        "empty party": {**GOOD, "party": []},
        "7 members": {**GOOD, "party": [member(name=f"P{i}") for i in range(7)]},
        "thin sheet": {**GOOD, "party": [member(sheet="A rogue.")]},
        "no name": {**GOOD, "party": [member(name=" ")]},
        "duplicate names": {**GOOD, "party": [member(), member(name="BO")]},
        "member not object": {**GOOD, "party": ["Ann"]},
        "bad notes": {**GOOD, "gm_notes": 5},
        "too long": {**GOOD, "setting": "x" * 31_000},
    }
    for label, tool_input in bad.items():
        state = GameState(structure="endless")
        out = dispatch("begin_adventure", "t", tool_input, state)
        assert out.is_error, label
        assert state == GameState(structure="endless"), label


def test_rejection_lists_every_problem_so_the_model_can_fix_them_in_one_go():
    out = dispatch("begin_adventure", "t", {**GOOD, "setting": "Short.", "opening": "Short.", "level": 99}, GameState(structure="endless"))
    assert out.is_error
    for needle in ("'setting' is too thin", "'opening' is too thin", "'level' must be"):
        assert needle in out.content


def test_multi_member_party_is_accepted():
    party = [member(name="Ann"), member(name="Bo"), member(name="Cy")]
    state = GameState(structure="endless")
    assert not dispatch("begin_adventure", "t", {**GOOD, "party": party}, state).is_error
    assert [m["name"] for m in state.campaign["party"]] == ["Ann", "Bo", "Cy"]


def test_begin_adventure_is_unknown_once_the_adventure_has_begun():
    state = GameState(Phase.ADVENTURE)
    out = dispatch("begin_adventure", "t", GOOD, state)
    assert out.is_error and "Unknown tool" in out.content


def test_double_begin_in_one_response_only_counts_once():
    state = GameState(structure="endless")
    assert not dispatch("begin_adventure", "a", GOOD, state).is_error
    second = dispatch("begin_adventure", "b", {**GOOD, "level": 9}, state)
    assert second.is_error and state.campaign["level"] == 3


# ---- prompts per phase, and rollback -------------------------------------------------------


def test_game_prompts_and_tools_follow_the_state():
    game = Game()
    zero = GameState()
    adv = GameState(Phase.ADVENTURE, {**GOOD, "gm_notes": "The mayor is a vampire."})
    assert "Current mode: Session 0" in game.system(zero)
    assert [t["name"] for t in game.tools(zero)] == ["roll_dice", "set_ruleset", "set_structure", "begin_adventure"]
    text = game.system(adv)
    assert "Current mode: Adventure" in text and "Current mode: Session 0" not in text
    assert "The mayor is a vampire." in text  # private notes are in the system prompt
    assert SETTING.strip() not in text and SHEET not in text  # the record is a history entry, not in the prompt
    assert [t["name"] for t in game.tools(adv)] == ["roll_dice", "recall", "establish", "set_scene", "update_character", "set_combat", "set_motive", "social_check", "award"]
    assert "## GM notes" not in game.system(GameState(Phase.ADVENTURE))  # old saves have none


def test_history_after_begin_is_one_gm_entry_with_everything_but_the_notes():
    game = Game()
    msgs = game.history_after_begin(GameState(Phase.ADVENTURE, {**GOOD, "gm_notes": "secret!"}))
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    record = msgs[1]["content"][0]["text"]
    assert SETTING.strip() in record and SHEET in record and GOOD["opening"] in record
    assert "Ann" in record and "level 3" in record and "secret!" not in record
    assert "{{" not in record


class BeginThenMaybeFail:
    """First request: call begin_adventure. Second request: fail or answer."""

    def __init__(self, fail: bool) -> None:
        self.fail, self.calls, self.requests = fail, [], []

    async def stream(self, *, system, messages, tools):
        self.calls.append((system, [t["name"] for t in tools]))
        self.requests.append(list(messages))
        if len(self.calls) == 1:
            block = {"type": "tool_use", "id": "toolu_1", "name": "begin_adventure", "input": GOOD}
            yield Completed([block], "tool_use")
        elif self.fail:
            raise LLMError("boom", retryable=True)
        else:
            yield TextChunk("Welcome.")
            yield Completed([{"type": "text", "text": "Welcome."}], "end_turn")


async def collect(session, llm):
    return [ev async for ev in run_turn(session=session, user_text="yes", llm=llm, game=Game(), max_iters=4)]


async def test_next_request_in_the_same_turn_uses_the_adventure_prompt_and_tools():
    session, llm = Session("s"), BeginThenMaybeFail(fail=False)
    session.state.structure = "endless"
    events = await collect(session, llm)
    assert [type(e) for e in events if isinstance(e, (PhaseChange, MessageEnd))] == [PhaseChange, MessageEnd]
    (sys1, tools1), (sys2, tools2) = llm.calls
    assert "Current mode: Session 0" in sys1 and tools1 == ["roll_dice", "set_ruleset", "set_structure", "begin_adventure"]
    assert "Current mode: Adventure" in sys2 and tools2 == ["roll_dice", "recall", "establish", "set_scene", "update_character", "set_combat", "set_motive", "social_check", "award"]
    assert session.state.phase is Phase.ADVENTURE and session.state.campaign["level"] == 3
    assert len(llm.requests[1]) == 3  # the second request saw only: note, campaign record, cue
    assert [m["role"] for m in session.messages] == ["user", "assistant", "user", "assistant"]
    assert "Session 0 is complete" in session.messages[0]["content"][0]["text"]
    assert session.messages[-1]["content"] == [{"type": "text", "text": "Welcome."}]


async def test_failed_turn_after_begin_rolls_the_phase_back():
    session, llm = Session("s"), BeginThenMaybeFail(fail=True)
    session.state.structure = "endless"
    events = await collect(session, llm)
    assert isinstance(events[-1], ErrorEvent)
    assert not any(isinstance(e, PhaseChange) for e in events)
    assert session.state == GameState(structure="endless") and session.messages == []
