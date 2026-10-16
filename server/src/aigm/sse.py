import json

from aigm.models import SSEEvent

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def encode(event: SSEEvent) -> str:
    """Render one event as SSE. The JSON is single-line (newlines inside strings are escaped)."""
    data = json.dumps(event.payload(), separators=(",", ":"), ensure_ascii=False)
    return f"event: {event.event}\ndata: {data}\n\n"
