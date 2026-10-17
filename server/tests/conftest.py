import json

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name, data = None, None
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        assert name is not None and data is not None, block
        events.append((name, data))
    return events


def chat(client, message, session_id="default"):
    resp = client.post("/chat", json={"message": message, "session_id": session_id})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    return parse_sse(resp.text)


def names(events):
    return [n for n, _ in events]


def reply_text(events):
    return "".join(d["delta"] for n, d in events if n == "text")
