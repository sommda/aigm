"""Minimal Server-Sent Events line decoder (see docs/API.md, "SSE framing")."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SSEMessage:
    event: str
    data: str


class SSEDecoder:
    """Feed it one line at a time (without the line terminator); it returns a message
    when a blank line completes one. Comment lines (": ping") and unknown fields are ignored."""

    def __init__(self) -> None:
        self._event: str | None = None
        self._data: list[str] = []

    def decode(self, line: str) -> SSEMessage | None:
        line = line.rstrip("\r\n")
        if not line:
            if self._event is None and not self._data:
                return None
            msg = SSEMessage(self._event or "message", "\n".join(self._data))
            self._event, self._data = None, []
            return msg
        if line.startswith(":"):
            return None
        name, sep, value = line.partition(":")
        if sep and value.startswith(" "):
            value = value[1:]
        if name == "event":
            self._event = value
        elif name == "data":
            self._data.append(value)
        return None
