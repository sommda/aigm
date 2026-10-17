from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings


def test_health():
    client = TestClient(create_app(Settings(model="test-model")))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "model": "test-model", "debug": False}
