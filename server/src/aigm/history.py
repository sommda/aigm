"""The history the model is shown: the stored messages, reduced (docs/HISTORY.md).

The stored messages are the transcript and are never changed. `reduce_history` derives the view that is
sent, with two steps that only touch old turns:

- **Trim** (older than `trim_keep` turns): thinking blocks are dropped. Tool calls and results stay as they are.
- **Digest** (older than `digest_keep` turns): a turn is replaced by its digest, a line or two written by the
  curator. The digests go into one `<story_so_far>` block at the start of the oldest turn still shown in full.

Both cuts move in steps (`*_step` turns) and depend only on the number of turns, so the beginning of the
request stays identical from one turn to the next and the prompt cache keeps hitting. Each cut moves once per
step and rewrites the cache once. The first turn (the campaign record) is always shown in full."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from aigm.world.digest import Digest

STORY_OPEN = "<story_so_far>"
STORY_CLOSE = "</story_so_far>"
STORY_INTRO = (
    "The earlier turns of this adventure, condensed. Their full text is no longer shown; treat what is "
    "written here as having happened."
)


@dataclass(frozen=True)
class HistoryPolicy:
    trim: bool = True
    trim_keep: int = 4  # the newest turns that are never trimmed
    trim_step: int = 6  # the trim cut moves this many turns at a time
    digest: bool = True
    digest_keep: int = 12
    digest_step: int = 12

    @property
    def active(self) -> bool:
        return self.trim or self.digest


@dataclass(frozen=True)
class Turn:
    start: int  # index of the player's message
    end: int  # one past the last message of the turn (the next turn starts here)
    number: int  # 1 for the first player message


@dataclass(frozen=True)
class Reduction:
    """What was done to the history, for the context viewer and the metrics."""

    turns: int = 0
    digested_turns: int = 0
    trimmed_turns: int = 0
    digest_cut: int = 0  # turns before this index (0-based, the first turn excluded) are shown as digests
    trim_cut: int = 0
    turn_of: tuple[int, ...] = ()  # for each message sent, the number of the turn it belongs to (0: the digests)
    trimmed: frozenset[int] = field(default_factory=frozenset)  # numbers of the turns that were trimmed


@dataclass(frozen=True)
class Reduced:
    messages: list[dict[str, Any]]
    info: Reduction


def is_player_message(msg: dict[str, Any]) -> bool:
    return msg.get("role") == "user" and any(b.get("type") == "text" for b in msg.get("content", []))


def turns(messages: list[dict[str, Any]]) -> list[Turn]:
    """Split the history at each player message. Anything before the first one joins the first turn."""
    starts = [i for i, m in enumerate(messages) if is_player_message(m)]
    if not starts:
        return []
    starts[0] = 0
    ends = [*starts[1:], len(messages)]
    return [Turn(s, e, n) for n, (s, e) in enumerate(zip(starts, ends), start=1)]


def cut(total_turns: int, keep: int, step: int) -> int:
    """How many turns from the start have aged out. It only changes every `step` turns, and at least
    `keep` turns are always newer than the cut."""
    return max(0, (total_turns - max(1, keep)) // max(1, step) * max(1, step))


def block_chars(block: dict[str, Any]) -> int:
    """Size of a content block for estimates. A thinking block's signature is opaque data, far larger than the
    thinking itself (five times in a real save), so it is left out like the context viewer leaves it out."""
    return len(json.dumps({k: v for k, v in block.items() if k != "signature"}, ensure_ascii=False))


def message_chars(messages: list[dict[str, Any]]) -> int:
    return sum(block_chars(b) for m in messages for b in m.get("content", []))


def turn_chars(messages: list[dict[str, Any]], turn: Turn) -> int:
    """Characters of text the player and GM wrote in a turn (what a digest condenses)."""
    return sum(
        len(b.get("text", ""))
        for m in messages[turn.start : turn.end]
        for b in m.get("content", [])
        if b.get("type") == "text"
    )


def digest_for(turn: Turn, digests: Mapping[int, Digest]) -> Digest | None:
    digest = digests.get(turn.start)
    return digest if digest is not None and digest.end == turn.end else None


def story_block(digests: list[Digest]) -> str:
    lines = [f"[Turn {d.turn}] {d.text}" for d in digests]
    return "\n".join([STORY_OPEN, STORY_INTRO, "", *lines, STORY_CLOSE])


def reduce_history(
    messages: list[dict[str, Any]], digests: Mapping[int, Digest], policy: HistoryPolicy
) -> Reduced:
    """The messages as the model should see them. With nothing to reduce, `messages` itself is returned."""
    ts = turns(messages)
    total = len(ts)
    numbers = tuple(t.number for t in ts for _ in range(t.end - t.start))
    plain = Reduced(messages, Reduction(turns=total, turn_of=numbers))
    if not policy.active or total < 2:
        return plain

    digest_cut = 1  # index into `ts` of the first turn kept in full; the first turn always is
    if policy.digest:
        wanted = cut(total, policy.digest_keep, policy.digest_step)
        while digest_cut < wanted and digest_for(ts[digest_cut], digests):
            digest_cut += 1  # a turn without a digest stops the cut: it can only move over finished work
    trim_cut = max(digest_cut, cut(total, policy.trim_keep, policy.trim_step)) if policy.trim else digest_cut
    if digest_cut == 1 and trim_cut <= 1:
        return plain

    out: list[dict[str, Any]] = list(messages[: ts[1].start])  # the first turn
    turn_of: list[int] = list(numbers[: ts[1].start])
    if digest_cut > 1:
        story = story_block([digest_for(t, digests) for t in ts[1:digest_cut]])  # type: ignore[misc]
    else:
        story = ""

    trimmed: set[int] = set()
    for index in range(digest_cut, total):
        turn = ts[index]
        chunk = messages[turn.start : turn.end]
        if index < trim_cut:
            chunk = trim_turn(chunk)
            trimmed.add(turn.number)
        if story and index == digest_cut:
            first = chunk[0]
            chunk = [{**first, "content": [{"type": "text", "text": story}, *first["content"]]}, *chunk[1:]]
        out.extend(chunk)
        turn_of.extend([turn.number] * len(chunk))
    info = Reduction(
        turns=total,
        digested_turns=digest_cut - 1,
        trimmed_turns=len(trimmed),
        digest_cut=digest_cut,
        trim_cut=trim_cut,
        turn_of=tuple(turn_of),
        trimmed=frozenset(trimmed),
    )
    return Reduced(out, info)


# ---- trimming one turn --------------------------------------------------------------------


def trim_turn(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the thinking blocks. Tool calls and their results are kept exactly as stored: when they were folded
    into text notes ("(Rolled 1d20+5: ...)") the model began writing such notes itself instead of rolling.

    A message that holds nothing but thinking is kept as it is, because an empty message is not valid."""
    out: list[dict[str, Any]] = []
    for msg in msgs:
        if msg["role"] != "assistant":
            out.append(msg)
            continue
        blocks = [b for b in msg["content"] if b.get("type") not in ("thinking", "redacted_thinking")]
        out.append({**msg, "content": blocks} if blocks else msg)
    return out
