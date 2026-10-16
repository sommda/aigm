"""Optional smoke test against the real Anthropic API. Costs a little money, so it only runs
when explicitly enabled:  AIGM_LIVE_TESTS=1 ANTHROPIC_API_KEY=... uv run pytest tests/test_live.py -s"""

import os

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from tests.conftest import chat, names, reply_text

pytestmark = pytest.mark.skipif(
    os.environ.get("AIGM_LIVE_TESTS") != "1", reason="set AIGM_LIVE_TESTS=1 (and ANTHROPIC_API_KEY) to run"
)


def test_live_turn_with_dice(tmp_path):
    client = TestClient(create_app(Settings(test_mode=False, save_dir=tmp_path)))
    events = chat(client, "Start a quick game. I'm a human fighter. As my first action, I attack a nearby rat: roll my attack now.")
    print(reply_text(events))
    assert names(events)[-1] == "message_end"
    assert "dice_roll" in names(events)
    assert len(client.get("/chat/history").json()["messages"]) >= 4
