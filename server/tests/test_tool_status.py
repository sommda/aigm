"""While the model writes a tool call nothing is visible; a `status` event says what it is doing."""

from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from tests.conftest import chat, names


def client(tmp_path):
    return TestClient(create_app(Settings(test_mode=True, test_delay=0, save_dir=tmp_path, _env_file=None)))


def tool_statuses(events):
    return [d for n, d in events if n == "status" and d["stage"] == "tool"]


def test_a_roll_call_shows_a_status_that_ends_before_the_dice(tmp_path):
    events = chat(client(tmp_path), "roll")
    shown = tool_statuses(events)
    assert [(s["message"], s["done"]) for s in shown] == [("Rolling the dice...", False), ("", True)]
    order = names(events)
    first = order.index("status")
    assert first < order.index("tool_call") and order.index("status", first + 1) < order.index("tool_call")


def test_other_tool_calls_show_a_notes_status(tmp_path):
    events = chat(client(tmp_path), "begin")
    assert any(s["message"] == "The GM is making notes..." for s in tool_statuses(events))


def test_every_status_is_ended(tmp_path):
    for command in ("roll", "multiroll", "begin"):
        shown = tool_statuses(chat(client(tmp_path), command, session_id=command))
        assert [s["done"] for s in shown].count(True) == len(shown) // 2


def test_test_mode_streams_the_roll_narration_in_pieces_before_the_tool_call(tmp_path):
    events = chat(client(tmp_path), "roll")
    order = names(events)
    before = [d["delta"] for n, d in events[: order.index("tool_call")] if n == "text"]
    assert len(before) > 3 and "".join(before).strip().endswith(".")  # the narration, in pieces of a few characters
    assert order.index("tool_call") < order.index("dice_roll")
