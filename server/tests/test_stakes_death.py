"""Stakes, step 5 (docs/STAKES.md 7.2 to 7.4): a character's fate, the fallen block, revival costs."""

from aigm import characters
from aigm import story as st
from aigm.game import Game
from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.sheets import clean
from aigm.tools import dispatch
from aigm.world import World, WorldTime
from tests.test_story_gm import state_with_story

SHEET = {
    "headline": "Rogue 3", "hp": 12, "max_hp": 12, "conditions": [],
    "sections": [{"title": "Stats", "lines": ["STR 10"]}],
}  # fmt: skip


def party(*names, story=True, chapter=1):
    state = state_with_story() if story else GameState(Phase.ADVENTURE, {"setting": "x"}, World(), turn=10)
    state.heroes = {}
    state.campaign = {"party": [{"name": n} for n in names]}
    state.sheets = {n: clean(SHEET) for n in names}
    if story:
        state.story.chapter = chapter
        st.settle_ready(state.story)
    return state


def upd(state, name, **kw):
    return dispatch("update_character", "t", {"name": name} | kw, state)


def test_a_character_dies_and_it_is_recorded():
    state = party("Ana", "Bo")
    state.world.time = WorldTime(2, 9)
    out = upd(state, "Ana", fate="dead")
    sheet = state.sheets["Ana"]
    assert not out.is_error and "Put the choice" in out.content
    assert (sheet.fate, sheet.remains, sheet.died_turn, sheet.hp) == ("dead", None, 10, 0)
    assert sheet.died_at["day"] == 2 and any("Ana fell" in c["note"] for c in state.story.choices)


def test_a_dead_character_cannot_die_again_or_be_changed():
    state = party("Ana", "Bo")
    upd(state, "Ana", fate="dead")
    assert "already dead" in upd(state, "Ana", fate="dead").content
    assert "is dead" in upd(state, "Ana", hp=5).content


def test_the_last_living_member_cannot_die_in_chapters_one_and_two():
    for chapter in (1, 2):
        state = party("Ana", "Bo", chapter=chapter)
        upd(state, "Ana", fate="dead")
        out = upd(state, "Bo", fate="dead")
        assert out.is_error and "defeat" in out.content and state.sheets["Bo"].fate is None


def test_the_last_death_is_refused_without_a_story_too():
    state = party("Ana", story=False)
    assert upd(state, "Ana", fate="dead").is_error


def test_the_last_death_in_chapter_three_loses_the_game():
    state = party("Ana", "Bo", chapter=3)
    upd(state, "Ana", fate="dead")
    out = upd(state, "Bo", fate="dead")
    assert not out.is_error and "story is lost" in out.content and state.story.fall is not None


def test_remains_are_the_players_choice_recorded_later():
    state = party("Ana", "Bo")
    upd(state, "Ana", fate="dead")
    assert upd(state, "Ana", remains="buried").content.startswith("Ana:")
    assert state.sheets["Ana"].remains == "buried"
    assert upd(state, "Bo", remains="left").is_error  # the living have no remains
    assert upd(state, "Ana", remains="eaten").is_error


def test_revival_needs_a_cost_and_a_body():
    state = party("Ana", "Bo")
    upd(state, "Ana", fate="dead", remains="lost")
    assert "lost" in upd(state, "Ana", fate="revived", cost="x", cost_kind="resource").content
    state = party("Ana", "Bo")
    upd(state, "Ana", fate="dead", remains="carried")
    free = upd(state, "Ana", fate="revived")
    assert free.is_error and "never free" in free.content and state.sheets["Ana"].fate == "dead"
    assert "never free" in upd(state, "Bo", fate="revived").content or "not dead" in upd(state, "Bo", fate="revived").content


def test_a_revival_is_recorded_as_a_cost():
    state = party("Ana", "Bo")
    upd(state, "Ana", fate="dead", remains="carried")
    out = upd(state, "Ana", fate="revived", cost="A priest's rite took the party's gold.", cost_kind="resource", hp=3)
    assert not out.is_error and state.sheets["Ana"].fate is None and state.sheets["Ana"].died_at is None
    assert state.sheets["Ana"].hp == 3 and state.story.costs[-1]["kind"] == "resource"
    assert any("brought back" in c["note"] for c in state.story.choices)


def test_a_chapter_two_revival_is_more_than_time_alone():
    state = party("Ana", "Bo", chapter=2)
    upd(state, "Ana", fate="dead", remains="carried")
    out = upd(state, "Ana", fate="revived", cost="A day of rites.", cost_kind="time", cost_hours=24)
    assert out.is_error and state.sheets["Ana"].fate == "dead"
    assert not upd(state, "Ana", fate="revived", cost="A favour owed to the temple.", cost_kind="ally").is_error


def test_a_time_cost_for_a_chapter_one_revival_moves_the_clock():
    state = party("Ana", "Bo")
    upd(state, "Ana", fate="dead", remains="carried")
    start = state.world.time
    upd(state, "Ana", fate="revived", cost="A night of rites.", cost_kind="time", cost_hours=8)
    assert state.world.time == start.plus(8)


def test_revival_cannot_undo_a_lost_story():
    state = party("Ana", "Bo", chapter=3)
    upd(state, "Ana", fate="dead", remains="carried")
    st.lose(state.story, 10, "the vault burned")
    out = upd(state, "Ana", fate="revived", cost="Everything.", cost_kind="ally")
    assert out.is_error and "does not undo" in out.content


def test_an_endless_game_revives_without_a_cost():
    state = party("Ana", "Bo", story=False)
    upd(state, "Ana", fate="dead", remains="carried")
    assert not upd(state, "Ana", fate="revived").is_error


# ---- what is shown -----------------------------------------------------------------------


def test_the_fallen_block_tells_the_gm_what_to_ask():
    state = party("Ana", "Bo")
    state.world.time = WorldTime(1, 8)
    upd(state, "Ana", fate="dead")
    state.world.time = WorldTime(4, 8)
    text = characters.fallen_notes(state)
    assert "Ana, died 3 days ago: the body's fate is not decided" in text and "Put the choice" in text
    upd(state, "Ana", remains="buried")
    text = characters.fallen_notes(state)
    assert "laid to rest" in text and "Put the choice" not in text
    assert characters.fallen_notes(party("Ana")) == ""


def test_the_briefing_carries_the_fallen_and_marks_them_in_the_party_line():
    state = party("Ana", "Bo")
    upd(state, "Ana", fate="dead")
    text = Game(PromptLibrary()).briefing(state, "hello", "")
    assert "Fallen (they are out" in text and "Ana level 1 (dead)" in text and "Bo level 1;" in text.replace("Bo level 1.", "Bo level 1;")


def test_the_roster_and_the_status_put_the_dead_last():
    from aigm import status

    state = party("Ana", "Bo")
    upd(state, "Ana", fate="dead")
    rows = characters.roster(state)
    assert [r["name"] for r in rows] == ["Bo", "Ana"] and rows[1]["fate"] == "dead" and rows[1]["conditions"][0] == "dead"
    assert "fate" not in rows[0]
    table = status.build(state)["table"]["rows"]
    assert [r[0] for r in table][:2] == ["Bo", "Ana"] and table[1][3].startswith("Fallen")
    assert characters.detail(state, "Ana")["fate"] == "dead" and characters.detail(state, "Bo")["fate"] is None


def test_an_unsettled_death_becomes_left_behind_in_time():
    state = party("Ana", "Bo")
    upd(state, "Ana", fate="dead")
    state.turn = 10 + characters.LEAVE_TURNS - 1
    assert characters.settle_remains(state) == []
    state.turn += 1
    assert characters.settle_remains(state) == ["Ana"] and state.sheets["Ana"].remains == "left"
    assert characters.settle_remains(state) == []


def test_a_fate_survives_a_save():
    state = party("Ana", "Bo")
    upd(state, "Ana", fate="dead", remains="buried")
    again = GameState.from_dict(state.to_dict())
    assert again.sheets["Ana"].fate == "dead" and again.sheets["Ana"].remains == "buried"
