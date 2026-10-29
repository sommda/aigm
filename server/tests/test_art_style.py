"""Choosing the portrait style in Session 0 (docs/PORTRAITS.md 5.2)."""

from fastapi.testclient import TestClient

from aigm import art
from aigm.app import create_app
from aigm.config import Settings
from aigm.game import Game
from aigm.images import FakeImages
from aigm.session.state import GameState, Phase
from aigm.status import build
from aigm.tools import dispatch, tool_schemas
from tests.conftest import chat


def zero(**kw) -> GameState:
    return GameState(Phase.SESSION_ZERO, **kw)


def pick(state, style):
    return dispatch("set_art_style", "t1", {"style": style}, state)


def test_choosing_a_style_sets_it_and_says_what_it_is():
    state = zero()
    out = pick(state, "anime")
    assert not out.is_error and state.art_style == "anime" and "Anime" in out.content
    assert pick(state, "none").content == "The game will have no character portraits." and state.art_style == "none"
    out = pick(state, "default")
    assert state.art_style is None and art.resolve_style(None, state.ruleset).name in out.content
    assert "default for" in out.content


def test_an_unknown_style_is_refused_and_changes_nothing():
    state = zero(art_style="ink")
    out = pick(state, "oil-by-a-famous-painter")
    assert out.is_error and state.art_style == "ink" and "anime" in out.content


def test_the_style_cannot_change_once_the_adventure_has_begun():
    state = GameState(Phase.ADVENTURE, {"party": []})
    assert dispatch("set_art_style", "t1", {"style": "anime"}, state).is_error and state.art_style is None


def test_the_tool_is_offered_in_session_zero_only_and_only_when_portraits_are_on():
    def names(**kw):
        return [t["name"] for t in tool_schemas(None, **kw)]

    assert "set_art_style" in names(phase=Phase.SESSION_ZERO, art_styles=True)
    assert "set_art_style" not in names(phase=Phase.SESSION_ZERO)
    assert "set_art_style" not in names(phase=Phase.ADVENTURE, art_styles=True)
    on = [t for t in tool_schemas(None, Phase.SESSION_ZERO, False, True) if t["name"] == "set_art_style"][0]
    assert set(on["input_schema"]["properties"]["style"]["enum"]) == {*art.BY_ID, "none", "default"}
    assert "portraits" in on["description"].lower()


def test_session_zero_mentions_styles_for_the_chosen_ruleset_when_portraits_are_on():
    on, off = Game(art_styles=True), Game()
    for ruleset, default in (("adnd1e", "Pen and ink"), ("pf2e", "Clean stylized")):
        text = on.system(zero(ruleset=ruleset))
        assert "## Portraits" in text and f"**{default}**" in text and "`anime`" in text and "`none`" in text
    assert "## Portraits" not in off.system(zero())
    assert "## Portraits" not in on.system(GameState(Phase.ADVENTURE, {"party": []}))  # not once play has begun


def test_the_status_page_names_the_style_in_use():
    state = GameState(Phase.ADVENTURE, {"party": []}, ruleset="adnd2e")
    assert build(state)["art_style"] == "moody"
    state.art_style = "anime"
    assert build(state)["art_style"] == "anime"
    state.art_style = art.NO_PORTRAITS
    assert build(state)["art_style"] is None


def test_without_portraits_the_server_offers_no_style():
    client = TestClient(create_app(Settings(test_mode=True, images=False, _env_file=None)))
    assert not client.app.state.game.art_styles
    assert "set_art_style" not in [t["name"] for t in client.app.state.game.tools(zero())]


def test_over_http_a_chosen_style_governs_the_portraits_that_are_made(tmp_path):
    settings = Settings(test_mode=True, test_delay=0, save_dir=tmp_path, _env_file=None)
    client = TestClient(create_app(settings, images=FakeImages()))
    session = client.app.state.sessions.get("default")
    session.state.art_style = "sketch"  # as set_art_style would have
    chat(client, "begin")
    chat(client, "look around")
    assert session.state.portraits["Test Hero"].style == "sketch"
    assert client.get("/status").json()["art_style"] == "sketch"
