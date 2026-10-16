import json

import pytest

from aigm.session.persistence import last_assistant_preview, validate_messages
from aigm.errors import CorruptSave
from tests.conftest import chat


def save(client, name, **params):
    return client.put(f"/history/{name}/save", params=params)


def test_list_is_empty_initially(client):
    assert client.get("/history").json() == {"histories": []}


def test_save_list_info_restore_roundtrip(client):
    chat(client, "echo first")
    resp = save(client, "game-1")
    body = resp.json()
    assert resp.status_code == 200
    assert body["name"] == "game-1" and body["message_count"] == 2 and body["overwritten"] is False
    assert body["session_id"] == "default" and body["saved_at"].endswith("Z")

    listing = client.get("/history").json()["histories"]
    assert [h["name"] for h in listing] == ["game-1"] and listing[0]["model"] == "scripted-test"

    info = client.get("/history/game-1").json()
    assert info["message_count"] == 2 and info["last_message_preview"] == "first"
    assert "messages" not in info
    assert len(client.get("/history/game-1", params={"include_messages": "true"}).json()["messages"]) == 2

    chat(client, "echo second")
    assert len(client.get("/chat/history").json()["messages"]) == 4
    restored = client.post("/history/game-1/restore").json()
    assert restored["message_count"] == 2 and restored["replaced_message_count"] == 4
    msgs = client.get("/chat/history").json()["messages"]
    assert [m["content"][0]["text"] for m in msgs] == ["echo first", "first"]


def test_save_refuses_to_overwrite_without_flag(client):
    chat(client, "echo one")
    save(client, "g")
    chat(client, "echo two")
    resp = save(client, "g")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "already_exists"
    assert client.get("/history/g").json()["message_count"] == 2  # existing save untouched
    resp = save(client, "g", overwrite="true")
    assert resp.status_code == 200 and resp.json()["overwritten"] is True
    assert client.get("/history/g").json()["message_count"] == 4


def test_saved_history_with_tool_calls_restores(client):
    chat(client, "multiroll")
    save(client, "rolls")
    client.post("/chat/new")
    assert client.post("/history/rolls/restore").status_code == 200
    msgs = client.get("/chat/history").json()["messages"]
    assert msgs[1]["content"][1]["type"] == "tool_use"
    # and the restored conversation can be continued
    assert chat(client, "echo more")[-1][0] == "message_end"


@pytest.mark.parametrize("name", ["bad name", "a.b", "x" * 65, "..%2Fetc"])
def test_invalid_names_rejected(client, name):
    resp = client.put(f"/history/{name}/save")
    assert resp.status_code in (400, 404)  # 404 when the router can't even match the path


def test_invalid_name_is_400(client):
    resp = save(client, "bad.name")
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "bad_request"
    assert client.get("/history/bad.name").status_code == 400


def test_missing_history_is_404(client):
    for resp in (client.get("/history/nope"), client.post("/history/nope/restore"), client.delete("/history/nope")):
        assert resp.status_code == 404 and resp.json()["error"]["code"] == "not_found"


def test_delete_one_leaves_others(client):
    save(client, "a")
    save(client, "b")
    assert client.delete("/history/a").json() == {"name": "a", "deleted": True}
    assert [h["name"] for h in client.get("/history").json()["histories"]] == ["b"]


def test_save_and_restore_conflict_while_busy(app, client):
    save(client, "g")
    app.state.sessions.get("default").busy = True
    assert save(client, "h").status_code == 409
    assert client.post("/history/g/restore").status_code == 409
    assert client.get("/history/g").status_code == 200  # reads are fine


def test_failed_restore_leaves_live_history_unchanged(client, settings):
    chat(client, "echo keep me")
    bad = settings.save_dir / "broken.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(json.dumps({"version": 1, "name": "broken", "messages": [{"role": "assistant", "content": []}]}))
    resp = client.post("/history/broken/restore")
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_error"
    assert len(client.get("/chat/history").json()["messages"]) == 2


def test_garbage_files_do_not_break_listing(client, settings):
    save(client, "good")
    (settings.save_dir / "junk.json").write_text("{not json")
    (settings.save_dir / "not a name.json").write_text("{}")
    assert [h["name"] for h in client.get("/history").json()["histories"]] == ["good"]
    assert client.get("/history/junk").status_code == 422


def test_session_id_selects_which_history_is_saved(client):
    chat(client, "echo a", session_id="s1")
    save(client, "from-s1", session_id="s1")
    assert client.get("/history/from-s1").json()["message_count"] == 2
    save(client, "empty")  # the default session is empty
    assert client.get("/history/empty").json()["message_count"] == 0


def test_validate_messages_rules():
    user = {"role": "user", "content": [{"type": "text", "text": "x"}]}
    asst = {"role": "assistant", "content": [{"type": "text", "text": "y"}]}
    use = {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "roll_dice", "input": {}}]}
    res = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "r"}]}
    validate_messages([])
    validate_messages([user, asst])
    validate_messages([user, use, res, asst])
    for bad in ([asst], [user, user], [user, use], [user, use, user], [user, asst, res], "nope", [{"role": "x"}]):
        with pytest.raises(CorruptSave):
            validate_messages(bad)


def test_preview_helper():
    assert last_assistant_preview([]) is None
    msgs = [{"role": "assistant", "content": [{"type": "text", "text": "a" * 300}]}]
    assert len(last_assistant_preview(msgs)) == 200
