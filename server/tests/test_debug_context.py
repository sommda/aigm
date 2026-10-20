"""Debug mode and GET /debug/context (docs/CONTEXT.md)."""

import pytest
from fastapi.testclient import TestClient

from aigm import cli
from aigm.app import create_app
from aigm.config import Settings
from aigm.session.state import GameState, Phase
from aigm.world import World
from aigm.world.ops import AddFact

CAMPAIGN = {"setting": "x", "gm_notes": "The mist lies."}
PLACEHOLDER = "«your next message goes here»"


def make(tmp_path, **kw):
    settings = Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None, **kw)
    app = create_app(settings)
    return app, TestClient(app)


@pytest.fixture
def debug(tmp_path):
    return make(tmp_path, debug=True)


def adventure(app, session_id="default"):
    world = World()
    mine = world.add_entity("Harrow Mine", "location")
    world.add_fact("The Harrow Mine was abandoned forty years ago.", [mine.id], aspect="history", disclosure="known")
    world.add_fact("The mine's lower gallery joins the cellar.", [mine.id], aspect="secret")
    world.set_scene(mine.id, [])
    session = app.state.sessions.get(session_id)
    session.state = GameState(Phase.ADVENTURE, CAMPAIGN, world)
    session.messages = [
        {"role": "user", "content": [{"type": "text", "text": "[System: begin]"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "You stand before the mine.\nIt is cold."}]},
        {"role": "user", "content": [{"type": "text", "text": "I roll to search."}]},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "Needs a check.", "signature": "SIG"},
                {"type": "tool_use", "id": "t1", "name": "roll_dice", "input": {"expression": "1d20+2"}},
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "1d20 (9) + 2 = 11"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "You find a rusted lantern."}]},
    ]
    return session


def find(nodes, id):
    for n in nodes:
        if n["id"] == id:
            return n
        hit = find(n.get("children", []), id)
        if hit:
            return hit
    return None


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(n.get("children", []))


# ---- debug mode is off unless asked -----------------------------------------------------------------------


def test_health_reports_debug(tmp_path):
    assert make(tmp_path)[1].get("/health").json()["debug"] is False
    assert make(tmp_path, debug=True)[1].get("/health").json()["debug"] is True


def test_without_debug_the_path_does_not_exist(tmp_path):
    app, client = make(tmp_path)
    adventure(app)
    missing = client.get("/debug/nothing-here")
    response = client.get("/debug/context")
    assert response.status_code == 404 and response.json() == missing.json()
    assert not any(path.startswith("/debug") for path in client.get("/openapi.json").json()["paths"])


def test_debug_false_from_the_environment_is_off(tmp_path, monkeypatch):
    monkeypatch.setenv("AIGM_DEBUG", "false")
    app = create_app(Settings(test_mode=True, save_dir=tmp_path / "saves", _env_file=None))
    assert TestClient(app).get("/debug/context").status_code == 404


def test_a_second_app_without_the_flag_stays_closed(tmp_path):
    make(tmp_path, debug=True)
    assert make(tmp_path)[1].get("/debug/context").status_code == 404


@pytest.fixture
def clean_env(monkeypatch):
    """cli.main writes to os.environ; set the variables first so that they are removed again afterwards."""
    for name in ("AIGM_DEBUG", "AIGM_TEST_MODE"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


def test_cli_flag_sets_debug_and_prints_the_notice(monkeypatch, capsys, clean_env):
    ran = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: ran.append(k))
    cli.main(["--test", "--debug", "--host", "0.0.0.0"])
    out = capsys.readouterr().out
    assert Settings(_env_file=None).debug is True
    assert "debug mode" in out and "WARNING" in out and ran
    monkeypatch.delenv("AIGM_DEBUG")
    cli.main(["--test"])
    assert "debug mode" not in capsys.readouterr().out and Settings(_env_file=None).debug is False


def test_no_warning_on_loopback(monkeypatch, capsys, clean_env):
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    cli.main(["--test", "--debug"])
    out = capsys.readouterr().out
    assert "debug mode" in out and "WARNING" not in out


# ---- the tree -----------------------------------------------------------------------------------------------


def test_adventure_tree_is_in_request_order(debug):
    app, client = debug
    adventure(app)
    body = client.get("/debug/context").json()
    assert body["phase"] == "adventure" and body["model"] == "scripted-test" and body["turn"] == 3
    top = body["sections"]
    assert [(s["id"], s["kind"]) for s in top] == [
        ("system", "system"), ("tools", "tools"), ("history", "history"), ("next", "user"),
    ]
    assert body["estimated_tokens"] == sum(s["tokens"] for s in top) > 0

    system = top[0]["children"]
    assert system[0]["id"] == "prompt/system/common/01_role.md" and all(c["kind"] == "prompt" for c in system)
    assert [t["title"] for t in top[1]["children"]] == ["roll_dice", "recall", "establish", "set_scene"]
    assert "Input schema:" in top[1]["children"][0]["text"]

    history = top[2]["children"]
    assert [m["kind"] for m in history] == ["user", "assistant", "user", "assistant", "user", "assistant"]
    assert history[1]["title"] == "Turn 1 · GM: You stand before the mine."
    assert history[1]["children"][0]["text"] == "You stand before the mine.\nIt is cold."
    kinds = [c["kind"] for c in history[3]["children"]]
    assert kinds == ["thinking", "tool_use"]
    assert "SIG" not in str(body)  # the signature is not shown
    assert history[3]["children"][1]["text"].startswith("roll_dice\n{")
    assert history[4]["children"][0]["kind"] == "tool_result"
    assert history[4]["children"][0]["text"] == "1d20 (9) + 2 = 11"

    placeholder, briefing = top[3]["children"]
    assert (placeholder["id"], placeholder["kind"], placeholder["text"]) == ("input", "input", PLACEHOLDER)
    assert placeholder["cache_breakpoint"] is True
    assert briefing["kind"] == "briefing" and "draft" not in briefing["note"] and briefing["note"]
    assert [c["title"] for c in briefing["children"]] == ["Clock", "Location"]
    assert "lower gallery" in briefing["children"][1]["text"]  # hidden facts are in the briefing


def test_parent_tokens_are_the_sum_of_their_children(debug):
    app, client = debug
    adventure(app)
    for node in walk(client.get("/debug/context").json()["sections"]):
        if "children" in node:
            assert node["tokens"] == sum(c["tokens"] for c in node["children"])
        else:
            assert node["tokens"] == -(-len(node["text"]) // 4)


def test_the_tree_is_exactly_the_request(debug):
    app, client = debug
    session = adventure(app)
    body = client.get("/debug/context", params={"draft": "I open the door"}).json()
    game = app.state.game
    system = [c["text"] for c in body["sections"][0]["children"]]
    staged = [*session.messages, {"role": "user", "content": [{"type": "text", "text": "I open the door"}]}]
    request = game.describe(session.state.copy(), staged, "I open the door")
    assert "\n\n".join(system) == request.system
    assert [t["title"] for t in body["sections"][1]["children"]] == [t["name"] for t in request.tools]
    briefing = find(body["sections"], "briefing")
    assert "\n".join(c["text"] for c in briefing["children"]) in request.briefing
    assert request.messages[-1]["content"][-1]["text"] == request.briefing


def test_session_zero_has_no_briefing(debug):
    _, client = debug
    body = client.get("/debug/context").json()
    assert body["phase"] == "session_zero" and body["turn"] == 1
    assert [c["id"] for c in body["sections"][3]["children"]] == ["input"]
    assert body["sections"][2]["title"] == "History (0 messages)"
    assert [t["title"] for t in body["sections"][1]["children"]] == ["roll_dice", "set_ruleset", "begin_adventure"]


def test_gm_notes_part_when_the_world_is_empty(debug):
    app, client = debug
    session = adventure(app)
    session.state = GameState(Phase.ADVENTURE, CAMPAIGN)
    parts = [c["id"] for c in client.get("/debug/context").json()["sections"][0]["children"]]
    assert parts[-1] == "prompt/templates/gm_notes.md"


def test_draft_replaces_the_placeholder_and_steers_the_briefing(debug):
    app, client = debug
    session = adventure(app)
    mine = session.state.world.find("Harrow Mine")
    other = session.state.world.add_entity("Karth", "location")
    session.state.world.add_fact("Karth is a walled port city.", [other.id], disclosure="known")
    plain = client.get("/debug/context").json()
    drafted = client.get("/debug/context", params={"draft": "We ride to Karth."}).json()
    assert find(drafted["sections"], "input")["text"] == "We ride to Karth."
    assert "walled port city" not in str(find(plain["sections"], "briefing"))
    assert "walled port city" in str(find(drafted["sections"], "briefing"))
    assert mine is not None


def test_ids_are_stable_between_calls(debug):
    app, client = debug
    adventure(app)
    ids = lambda: [n["id"] for n in walk(client.get("/debug/context").json()["sections"])]  # noqa: E731
    assert ids() == ids()


def test_a_queued_curator_result_is_shown_but_not_applied(debug):
    app, client = debug
    session = adventure(app)
    session.pending.append([AddFact("The mine has a second entrance.", ("Harrow Mine",), disclosure="known")])
    world_before, version = session.state.world.to_dict(), session.state.world.version
    messages_before = list(session.messages)
    body = client.get("/debug/context").json()
    assert "second entrance" in str(find(body["sections"], "briefing"))
    assert session.state.world.to_dict() == world_before and session.state.world.version == version
    assert len(session.pending) == 1 and session.messages == messages_before


def test_calling_it_changes_nothing(debug):
    app, client = debug
    session = adventure(app)
    before = (list(session.messages), session.state.to_dict(), session.state.turn, session.busy)
    for _ in range(2):
        client.get("/debug/context", params={"draft": "hello"})
    assert (list(session.messages), session.state.to_dict(), session.state.turn, session.busy) == before


def test_sessions_are_separate_and_unknown_ones_are_empty(debug):
    app, client = debug
    adventure(app, "one")
    assert client.get("/debug/context", params={"session_id": "one"}).json()["phase"] == "adventure"
    assert client.get("/debug/context", params={"session_id": "two"}).json()["phase"] == "session_zero"
    assert client.get("/debug/context", params={"session_id": "bad id!"}).status_code == 422


def test_works_while_a_turn_is_in_progress(debug):
    app, client = debug
    session = adventure(app)
    session.busy = True
    assert client.get("/debug/context").status_code == 200


# ---- GET/PUT /debug/thinking ----------------------------------------------------------------


def test_thinking_can_be_switched_off_and_on_in_debug(debug):
    _, client = debug
    assert client.get("/health").json()["thinking"] is True
    assert client.get("/debug/thinking").json() == {"thinking": True}
    assert client.put("/debug/thinking", json={"enabled": False}).json() == {"thinking": False}
    assert client.get("/debug/thinking").json() == {"thinking": False}
    assert client.get("/health").json()["thinking"] is False
    assert client.put("/debug/thinking", json={"enabled": True}).json() == {"thinking": True}


def test_thinking_needs_a_boolean(debug):
    assert debug[1].put("/debug/thinking", json={"enabled": "maybe"}).status_code == 422


def test_without_debug_thinking_cannot_be_changed(tmp_path):
    app, client = make(tmp_path)
    assert client.put("/debug/thinking", json={"enabled": False}).status_code == 404
    assert client.get("/debug/thinking").status_code == 404
    assert "thinking" not in client.get("/health").json()
    assert app.state.llm.thinking is True
