import httpx
import pytest

from aigm_client import events as ev
from aigm_client.api import ApiClient, ApiError
from tests.fake_server import FakeServer, sse


async def collect(api, msg="hi"):
    return [e async for e in api.stream_chat(msg)]


async def test_stream_chat_parses_events_across_chunk_boundaries():
    fake = FakeServer(
        [
            ("message_start", {"message_id": "m", "session_id": "default"}),
            ("thinking", {"status": "start"}),
            ("thinking", {"status": "end", "duration_ms": 3}),
            ("text", {"delta": "Hel"}),
            ("text", {"delta": "lo"}),
            ("future_event", {"x": 1}),
            ("message_end", {"message_id": "m", "stop_reason": "end_turn", "usage": {}}),
        ]
    )
    fake.split_chunks = True
    api = ApiClient(transport=fake.transport())
    events = await collect(api)
    assert [type(e).__name__ for e in events] == [
        "MessageStart", "Thinking", "Thinking", "Text", "Text", "Unknown", "MessageEnd",
    ]
    assert fake.calls[-1][2]["message"] == "hi"


async def test_stream_without_terminal_event_yields_error():
    fake = FakeServer([("text", {"delta": "cut off"})])
    events = await collect(ApiClient(transport=fake.transport()))
    assert isinstance(events[-1], ev.ErrorEvent) and events[-1].code == "connection_closed"


async def test_error_event_ends_stream():
    fake = FakeServer([("text", {"delta": "a"}), ("error", {"code": "upstream_error", "message": "boom"})])
    events = await collect(ApiClient(transport=fake.transport()))
    assert isinstance(events[-1], ev.ErrorEvent) and events[-1].message == "boom"


async def test_http_error_raises_apierror():
    def handler(req):
        return httpx.Response(409, json={"error": {"code": "conflict", "message": "in flight"}})

    api = ApiClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ApiError) as exc:
        await collect(api)
    assert exc.value.status == 409 and exc.value.code == "conflict"


async def test_validation_error_shape():
    api = ApiClient(transport=httpx.MockTransport(lambda r: httpx.Response(422, json={"detail": "bad"})))
    with pytest.raises(ApiError) as exc:
        await api.chat_history()
    assert exc.value.code == "validation_error"


async def test_connection_error_is_apierror_or_error_event():
    def boom(req):
        raise httpx.ConnectError("refused")

    api = ApiClient(transport=httpx.MockTransport(boom))
    with pytest.raises(ApiError) as exc:
        await api.health()
    assert exc.value.code == "connection_error"
    events = await collect(api)
    assert isinstance(events[0], ev.ErrorEvent) and events[0].code == "connection_error"


async def test_save_restore_endpoints():
    fake = FakeServer()
    api = ApiClient(transport=fake.transport())
    await api.save("a")
    with pytest.raises(ApiError) as exc:
        await api.save("a")
    assert exc.value.code == "already_exists"
    assert (await api.save("a", overwrite=True))["overwritten"] is True
    assert [h["name"] for h in await api.list_histories()] == ["a"]
    await api.restore("a")
    await api.delete("a")
    assert await api.list_histories() == []
