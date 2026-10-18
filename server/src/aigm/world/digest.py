"""Story digests: a short account of one player turn, kept next to the original messages.

The messages are never changed or dropped. A digest lets the request builder show the model a condensed
version of an old turn instead of the full text (docs/HISTORY.md), and both are saved with the game."""

from dataclasses import dataclass
from typing import Any

MAX_DIGEST_CHARS = 700


@dataclass(frozen=True)
class Digest:
    start: int  # index of the turn's first message in the history
    end: int  # one past its last message
    turn: int  # the turn's number: 1 is the first player message of the history
    text: str
    chars: int = 0  # characters of the original messages' text, to report what a digest saves

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "turn": self.turn, "text": self.text, "chars": self.chars}

    @classmethod
    def from_dict(cls, raw: Any) -> "Digest":
        """Raises ValueError for anything malformed (the caller turns that into a corrupt-save error)."""
        if not isinstance(raw, dict):
            raise ValueError("a digest must be an object")
        numbers = []
        for key in ("start", "end", "turn", "chars"):
            value = raw.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"digest {key} must be a non-negative integer")
            numbers.append(value)
        start, end, turn, chars = numbers
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("digest text must be a non-empty string")
        if end <= start:
            raise ValueError("a digest must cover at least one message")
        return cls(start, end, turn, text, chars)


def clean_digest_text(text: str) -> str:
    """One line, trimmed, and capped: a digest is a note, not a retelling."""
    one_line = " ".join(text.split())
    if len(one_line) <= MAX_DIGEST_CHARS:
        return one_line
    return one_line[: MAX_DIGEST_CHARS - 1].rstrip() + "…"
