"""Action types and their retry policies (docs/ATTEMPTS.md 3). Plain data, tuned after play tests.

A failed attempt of a `costly` type is open: it may be tried again, and each try costs. A failed attempt of a `once`
type is closed until something changes. The ruleset prompts adjust these, and the GM may override one attempt."""

from dataclasses import dataclass

COSTLY, ONCE = "costly", "once"
POLICIES = (COSTLY, ONCE)

# The attempt's status: `open` may be tried again, `closed` may not until reopened, `resolved` was done in the end.
OPEN, CLOSED, RESOLVED = "open", "closed", "resolved"
STATUSES = (OPEN, CLOSED, RESOLVED)
SCOPES = ("character", "anyone")  # a closure applies to the one character, or to everyone


@dataclass(frozen=True)
class ActionType:
    kind: str
    policy: str
    minutes: int  # the time of a try when the roll gives none
    reopens_if: str  # what the GM may take as a real change, when it gave none of its own
    examples: str


_NEW_WAY = "A new approach, a different character, new information, an ally's help, or time passing."

TYPES: dict[str, ActionType] = {
    t.kind: t
    for t in (
        ActionType("lock", COSTLY, 10, "Better tools, a locksmith's help, or the key.", "picking a lock, a puzzle box"),
        ActionType("trap", COSTLY, 10, "Better tools, another character's eye, or knowing how it works.", "finding or disarming a trap"),
        ActionType("force", COSTLY, 5, "A better tool, more hands, or a weaker spot.", "breaking a door, lifting a portcullis"),
        ActionType("climb", COSTLY, 15, "Rope or tools, another route, or help from above.", "climbing, swimming, a ledge, a hard jump"),
        ActionType("repair", COSTLY, 60, "Better materials or tools, a craftsman's help, or time to rest.", "mending, building, forging"),
        ActionType("treat", COSTLY, 10, "Better supplies, a healer's help, or time to rest.", "first aid, a poultice, tending poison"),
        ActionType("search", ONCE, 30, "A new method (a tool, light, another pair of eyes), or a change in the place.", "searching a room or area"),
        ActionType("lore", ONCE, 5, "New information, a book or a person who knows, or a different character.", "recalling, identifying"),
        ActionType("appraise", ONCE, 10, "A better look, a better tool, or an expert's opinion.", "valuing, authenticating"),
        ActionType("sneak", ONCE, 10, "A different route or means, a distraction, or time for the watch to change.", "passing unseen, shadowing"),
        ActionType("social", ONCE, 10, "A new approach, a different character, new information, an ally's word, or time passing.", "persuading, deceiving, intimidating"),
        ActionType("inquire", ONCE, 60, "A new source, a new way of asking, or time for word to spread.", "asking around, research"),
        ActionType("other", ONCE, 10, _NEW_WAY, "anything else the GM records"),
    )
}  # fmt: skip
KINDS = tuple(TYPES)


def type_of(kind: str) -> ActionType | None:
    return TYPES.get(kind)


# ---- the difficulty of a roll (docs/ATTEMPTS.md 6.1) ---------------------------------------------------------------

OVER, UNDER = "over", "under"
DC_MODES = (OVER, UNDER)
MAX_DC = 100


def read_dc(tool_input: dict) -> tuple[int | None, str, str | None]:
    """The `dc` and `dc_mode` of a roll: (dc, mode, problem). No `dc` means no verdict; a mode needs a dc."""
    dc, mode = tool_input.get("dc"), tool_input.get("dc_mode", OVER)
    if dc is None:
        if tool_input.get("dc_mode") is not None:
            return None, OVER, "`dc_mode` needs a `dc`"
        return None, OVER, None
    if isinstance(dc, bool) or not isinstance(dc, int) or not 1 <= dc <= MAX_DC:
        return None, OVER, f"`dc` must be a whole number from 1 to {MAX_DC}"
    if mode not in DC_MODES:
        return None, OVER, f"`dc_mode` must be one of {', '.join(DC_MODES)}"
    return dc, mode, None


def margin(total: float, dc: int, mode: str = OVER) -> float:
    """How far a total is past the line: zero or more is a success, below zero a failure by that much."""
    return dc - total if mode == UNDER else total - dc


def verdict_text(total: float, dc: int, mode: str = OVER) -> str:
    """For the GM only: "Success by 3 (DC 18)." or "Failure by 5 (DC 18)." The number is never shown to the player."""
    m = margin(total, dc, mode)
    shown = f"{abs(m):g}"
    under = " (roll under)" if mode == UNDER else ""
    if m >= 0:
        return f"Success{f' by {shown}' if m else ' (exactly the DC)'} (DC {dc}{under})."
    return f"Failure by {shown} (DC {dc}{under})."


# ---- rolls that look like tasks (docs/ATTEMPTS.md 13) -------------------------------------------------------------
# A roll with a `dc` whose label names one of these skills is a task, and a task needs its `attempt`: a failure the
# server does not hear of leaves no record and no closed door. Fights and saves are never tasks.

import re

_NOT_TASKS = re.compile(r"\b(attack|save|saving|damage|initiative|grapple|shove|hit points?|hp|death|concentration)\b", re.I)
_TASK_WORDS: tuple[tuple[str, str], ...] = (
    (r"lock|thieves'? tools|pick(?:ing)?\b|sleight", "lock"),
    (r"disarm|disable|trap|device", "trap"),
    (r"climb|swim|jump|athletics|acrobatics", "climb"),
    (r"force|break|smash|bend bars", "force"),
    (r"search|perception|investigat|spot|listen|seek|notice", "search"),
    (r"repair|craft|mend|forge|build|cook", "repair"),
    (r"medicine|first aid|heal|treat|survival", "treat"),
    (r"stealth|sneak|hide|shadow", "sneak"),
    (r"appraise|appraisal", "appraise"),
    (r"lore|history|arcana|religion|nature|knowledge|recall|remember", "lore"),
    (r"gather information|streetwise|ask around|research", "inquire"),
)


def task_kind(label: str | None) -> str | None:
    """The attempt kind a roll's `# label` suggests, or None when it is not a task (or says nothing)."""
    if not label or _NOT_TASKS.search(label):
        return None
    for pattern, kind in _TASK_WORDS:
        if re.search(rf"\b(?:{pattern})", label, re.I):
            return kind
    return None
