"""What clients and the debug tools are told about the story (docs/STORY.md 11)."""

import json

import pytest
from fastapi.testclient import TestClient

from aigm import story as st
from aigm.app import create_app
from aigm.config import Settings
from aigm.metrics import TurnMetrics
from tests.conftest import chat
from tests.test_story import short_story


def make(tmp_path, **kw):
    settings = Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None, **kw)
    app = create_app(settings)
    return app, TestClient(app)


def start(client, mode="short"):
    chat(client, f"structure {mode}")
    return chat(client, "begin")


def end_event(events):
    return next(d for n, d in events if n == "message_end")


SPOILERS = ("Crown", "Sunken Seal", "m01", "end1", "Quest c1q1", "binding")


def test_the_public_summary_has_no_plan_in_it():
    s = short_story()
    summary = st.public_summary(s)
    assert summary == {"length": "short", "chapter": 1, "chapter_title": "Ashby", "ended": False}
    st.conclude(s, "e1", "Done.")
    assert st.public_summary(s) == {"length": "short", "chapter": 4, "chapter_title": "The end", "ended": True,
                                    "ending": "Freed"}  # fmt: skip
    assert st.public_summary(None) is None and st.public_summary(st.Story("short")) is None


def test_history_and_message_end_carry_the_summary(tmp_path):
    app, client = make(tmp_path)
    assert client.get("/chat/history").json()["story"] is None
    events = start(client)
    summary = end_event(events)["story"]
    assert summary["length"] == "short" and summary["chapter"] == 1 and summary["ended"] is False
    assert summary["chapter_title"]
    assert client.get("/chat/history").json()["story"] == summary
    assert end_event(chat(client, "echo hi"))["story"] == summary


def test_an_endless_game_says_nothing_about_a_story(tmp_path):
    _, client = make(tmp_path)
    events = start(client, "endless")
    assert end_event(events)["story"] is None and client.get("/chat/history").json()["story"] is None


def test_public_responses_never_contain_the_plan(tmp_path):
    app, client = make(tmp_path)
    events = start(client)
    client.put("/history/g/save")
    texts = [json.dumps(d) for n, d in events if n in ("message_end", "status", "phase_change")]
    texts += [json.dumps(client.get("/chat/history").json()["story"]), client.get("/history/g").text,
              client.get("/history").text, client.post("/history/g/restore").text]  # fmt: skip
    for text in texts:
        assert not any(s in text for s in SPOILERS), text


def test_saved_game_listings_show_the_kind_and_chapter(tmp_path):
    _, client = make(tmp_path)
    start(client, "medium")
    client.put("/history/g/save")
    info = client.get("/history/g").json()
    assert info["structure"] == "medium" and info["story"]["length"] == "medium" and info["story"]["chapter"] == 1
    assert client.get("/history").json()["histories"][0]["story"]["chapter"] == 1
    assert client.post("/history/g/restore").json()["story"]["length"] == "medium"
    start_endless = TestClient(create_app(Settings(test_mode=True, save_dir=tmp_path / "other", _env_file=None)))
    start(start_endless, "endless")
    start_endless.put("/history/e/save")
    assert start_endless.get("/history/e").json()["structure"] == "endless"
    assert start_endless.get("/history/e").json()["story"] is None


def live(app):
    return app.state.sessions.get("default").state


def finish_chapter_one(client):
    """The scripted GM reports every required quest of chapter 1 and then that the goal is known."""
    events = []
    for quest in ("m01", "m02"):
        events += chat(client, f"quest {quest} done")
    events += chat(client, "quest goal")
    return events


def test_a_chapter_event_is_sent_when_the_story_moves_on(tmp_path):
    app, client = make(tmp_path)
    start(client)
    first = chat(client, "quest m01 done")
    assert not [d for n, d in first if n == "chapter"]
    chat(client, "quest m02 done")
    events = chat(client, "quest goal")
    chapter = [d for n, d in events if n == "chapter"]
    assert chapter == [{"previous": 1, "chapter": 2, "title": chapter[0]["title"]}] and chapter[0]["title"]
    names = [n for n, _ in events]
    assert names.index("chapter") < names.index("message_end")
    assert end_event(events)["story"]["chapter"] == 2
    assert live(app).story.chapter == 2


def test_the_chapter_is_announced_once(tmp_path):
    app, client = make(tmp_path)
    start(client)
    chat(client, "quest m01 done")
    chat(client, "quest m02 done")
    events = chat(client, "quest goal")
    assert live(app).story.chapter == 2
    again = chat(client, "echo nothing changes")
    assert not [1 for n, _ in again if n == "chapter"]


def test_the_ending_is_announced_as_chapter_four(tmp_path):
    app, client = make(tmp_path)
    start(client)
    state = live(app)
    state.story.chapter = 3
    state.story.goal.revealed = True
    for m in state.story.milestones:
        m.status = "done"
    from aigm.session.state import GameState  # noqa: F401

    session = app.state.sessions.get("default")
    from aigm.tools import dispatch

    out = dispatch("end_story", "t", {"ending": "end1", "epilogue": "Done."}, session.state)
    assert not out.is_error
    summary = st.public_summary(session.state.story)
    assert summary["chapter"] == 4 and summary["ended"] and summary["ending"]
    assert end_event(chat(client, "echo epilogue"))["story"]["ended"] is True


def test_turn_metrics_name_the_chapter_of_story_games_only(tmp_path):
    assert "chapter" not in TurnMetrics(turn=1, phase="adventure").to_dict()
    assert TurnMetrics(turn=1, phase="adventure", chapter=2).to_dict()["chapter"] == 2
    app, client = make(tmp_path)
    start(client)
    assert end_event(chat(client, "echo hi"))["metrics"]["chapter"] == 1
    _, plain = make(tmp_path / "plain")
    start(plain, "endless")
    assert "chapter" not in end_event(chat(plain, "echo hi"))["metrics"]


# ---- debug ----------------------------------------------------------------------------------


def test_the_debug_story_route_shows_everything_and_exists_only_in_debug(tmp_path):
    app, client = make(tmp_path, debug=True)
    assert client.get("/debug/story").json()["story"] is None
    start(client)
    body = client.get("/debug/story").json()
    assert body["structure"] == "short" and body["story"]["goal"]["title"] and "Goal:" in body["text"]
    assert body["waiting_for_plan"] is None and len(body["story"]["milestones"]) == 6
    _, plain = make(tmp_path / "x")
    assert plain.get("/debug/story").status_code == 404
