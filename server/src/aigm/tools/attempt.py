"""The `attempt` object of a roll (docs/ATTEMPTS.md 6): what the roll is for, checked before the dice, and what is
recorded after them. `roll_dice` calls it; there is no tool of its own."""

from dataclasses import dataclass
from typing import Any

from aigm import attempts
from aigm.session.state import GameState, Phase
from aigm.world import Attempt, WorldError, WorldTime
from aigm.world.model import MAX_FACT_WORDS, Entity, Route
from aigm.world.text import normalize_text, word_count

MIN_TASK_WORDS, MAX_TASK_WORDS = 2, 12
MAX_FAILURE_WORDS = 25
MAX_TEXT_CHARS = 200
_TIMES = {1: "once", 2: "twice"}


@dataclass
class AttemptPlan:
    """A checked `attempt`: who, what, on what, and what to do when it fails."""

    who: str
    kind: str
    task: str
    about: Entity
    failure: str
    closes: bool | None
    reopens_if: str
    after_minutes: int | None
    scope: str
    changed: str
    opens: Route | None
    minutes: int  # the time of the try


def _text(raw: dict[str, Any], key: str, problems: list[str], *, required: bool = False) -> str:
    value = raw.get(key)
    if value is None:
        if required:
            problems.append(f"`{key}` is required")
        return ""
    if not isinstance(value, str):
        problems.append(f"`{key}` must be text")
        return ""
    text = " ".join(value.split())
    if required and not text:
        problems.append(f"`{key}` is required")
    if len(text) > MAX_TEXT_CHARS:
        problems.append(f"`{key}` is longer than {MAX_TEXT_CHARS} characters")
    return text


def _words(text: str, key: str, low: int, high: int, problems: list[str]) -> None:
    if text and not low <= word_count(text) <= high:
        problems.append(f"`{key}` must be {low} to {high} words, not {word_count(text)}")


def _route(state: GameState, raw: Any, problems: list[str]) -> Route | None:
    """The blocked way an attempt is meant to open: `{from, to}` places, or the `how` of a way from the party's place."""
    world = state.world
    if isinstance(raw, dict):
        a, b = (world.resolve(str(raw.get(k, ""))) for k in ("from", "to"))
        route = None
        if a and b:
            ways = [r for r in world.routes_of(a.id) if r.other(a.id) == b.id]
            route = next((r for r in ways if r.block), ways[0] if ways else None)
    elif isinstance(raw, str) and raw.strip() and world.scene.location:
        wanted = normalize_text(raw)
        ways = [r for r in world.routes_of(world.scene.location) if wanted and wanted in normalize_text(r.how)]
        route = next((r for r in ways if r.block), ways[0] if ways else None)
    else:
        problems.append("`opens` is `{from, to}` places, or the words of a way out of here")
        return None
    if route is None:
        problems.append("`opens` names no recorded way; record it with `establish` first")
    elif route.block is None:
        problems.append("`opens` names a way that is not blocked")
    return route


def read_attempt(
    raw: Any, state: GameState, minutes: int | None, *, social: bool = False
) -> tuple[AttemptPlan | None, list[str]]:
    """Check the `attempt` of a roll. `minutes` is the roll's own, or None when it gave none. `social` is a
    `social_check`'s implied attempt, whose kind is `social`."""
    if not isinstance(raw, dict):
        return None, ["`attempt` must be an object"]
    world = state.world
    problems: list[str] = []
    who = state.find_hero(str(raw.get("who", "")))
    if who is None:
        problems.append(f"`who` must be a party member ({', '.join(state.party_names) or 'none'})")
    kind = raw.get("kind")
    if kind not in attempts.KINDS:
        problems.append(f"`kind` must be one of {', '.join(attempts.KINDS)}")
    elif kind == "social" and not social:
        problems.append("a social attempt is made with `social_check`, not with a die roll")
    task = _text(raw, "task", problems, required=True)
    _words(task, "task", MIN_TASK_WORDS, MAX_TASK_WORDS, problems)
    failure = _text(raw, "failure", problems, required=True)
    _words(failure, "failure", 1, MAX_FAILURE_WORDS, problems)
    reopens_if, changed = _text(raw, "reopens_if", problems), _text(raw, "changed", problems)
    scope = raw.get("scope", "character")
    if scope not in attempts.SCOPES:
        problems.append(f"`scope` must be one of {', '.join(attempts.SCOPES)}")
    closes = raw.get("closes")
    if closes is not None and not isinstance(closes, bool):
        problems.append("`closes` must be true or false")
    after = raw.get("after_minutes")
    if after is not None and (isinstance(after, bool) or not isinstance(after, int) or not 1 <= after <= 525600):
        problems.append("`after_minutes` must be a whole number of minutes, 1 or more")
    opens = _route(state, raw["opens"], problems) if raw.get("opens") is not None else None
    about_ref = raw.get("about")
    if about_ref is None:
        about = world.entity(opens.b if opens and opens.a == world.scene.location else opens.a) if opens else (
            world.entity(world.scene.location) if world.scene.location else None
        )
        if about is None:
            problems.append("`about` is required when the party's place is not recorded")
    else:
        about = world.resolve(str(about_ref))
        if about is None:
            problems.append(f"`about` {about_ref!r} is not recorded; record it with `establish` first")
    if problems or who is None or about is None or kind not in attempts.KINDS:
        return None, problems
    effort = max(1, minutes) if minutes is not None else attempts.TYPES[kind].minutes
    return AttemptPlan(
        who, kind, task, about, failure, closes, reopens_if, after, scope, changed, opens, effort
    ), []  # fmt: skip


def closed_result(attempt: Attempt, narration: str) -> str:
    """The reply when a closed attempt is rolled again with nothing changed: no roll, no time (docs/ATTEMPTS.md 6.2)."""
    why = attempt.failure or "it failed"
    return (
        f"No roll. {attempt.who}'s attempt to {attempt.task} is closed ({why}). Narrate the refusal in a line, in the "
        f"story, and let the player choose something different. Only a real change reopens it (GM only: "
        f"{(attempt.reopens_if or attempts.TYPES[attempt.kind].reopens_if).rstrip('.')}). Do not say that it is closed by rule."
    )


def _ordinal(n: int) -> str:
    return {2: "second", 3: "third", 4: "fourth", 5: "fifth"}.get(n, f"{n}th")


def _ordinal_times(n: int) -> str:
    return _TIMES.get(n, f"{n} times")


def _fit(prefix: str, tail: str) -> str:
    """`prefix` and `tail` as one sentence of at most MAX_FACT_WORDS words, cutting the tail if it must be."""
    room = MAX_FACT_WORDS - word_count(prefix)
    words = tail.split()
    return f"{prefix} {' '.join(words[: max(room, 0)])}".rstrip(" ;,") + ("" if len(words) <= room else ".")


def failure_fact(attempt: Attempt) -> str:
    when = "" if attempt.tries == 1 else f" {_ordinal_times(attempt.tries)}"
    return _fit(f"{attempt.who} tried to {attempt.task}{when} and failed;", attempt.failure or "it was beyond them")


def success_fact(attempt: Attempt) -> str:
    return f"{attempt.who} managed to {attempt.task} on the {_ordinal(attempt.tries + 1)} try."


def _write_fact(state: GameState, attempt: Attempt, text: str) -> str:
    """Write or replace the fact about the attempt. Returns a note for the GM when it could not be written."""
    world = state.world
    try:
        old = world.facts.get(attempt.fact) if attempt.fact else None
        if old is not None and old.active:
            fact = world.supersede(
                old.id, text, aspect="attempts", disclosure="known", source="play", turn=state.turn, allow_known=True
            )
        else:
            fact = world.add_fact(text, [attempt.about], aspect="attempts", disclosure="known", source="play", turn=state.turn)
        attempt.fact = fact.id
    except WorldError as exc:
        return f" (The record in the compendium could not be written: {exc}.)"
    return ""


def start_try(state: GameState, plan: AttemptPlan) -> tuple[Attempt | None, bool]:
    """Look up the record before the dice: (the earlier attempt or None, whether it is closed and stays closed)."""
    earlier = state.world.find_attempt(plan.who, plan.kind, plan.about.id)
    if earlier is not None and earlier.status == attempts.CLOSED:
        if not plan.changed:
            return earlier, True
        state.world.set_attempt_status(earlier.id, attempts.OPEN)  # something real has changed
    return earlier, False


def settle(state: GameState, plan: AttemptPlan, earlier: Attempt | None, margin: float) -> str:
    """After the dice: record a failure, or close a chain on success. Returns what the GM is told."""
    world = state.world
    kind = attempts.TYPES[plan.kind]
    if margin >= 0:
        lines = []
        if plan.opens is not None:
            route = plan.opens
            world.set_route(route.a, route.b, route.minutes, route.how, block=None)
            lines.append(f"The way is open now ({route.how or 'the way'} is no longer blocked): let the party through.")
        if earlier is not None:
            note = _write_fact(state, earlier, success_fact(earlier))
            world.set_attempt_status(earlier.id, attempts.RESOLVED)
            lines.append(f"{plan.who} did it on the {_ordinal(earlier.tries + 1)} try: the earlier failures are now one line of record.{note}")
        return " ".join(lines)
    closing = plan.closes if plan.closes is not None else kind.policy == attempts.ONCE
    status = attempts.CLOSED if closing else attempts.OPEN
    reopens_if = plan.reopens_if or (kind.reopens_if if closing else "")
    reopens_at = None
    if closing and plan.after_minutes:
        reopens_at = WorldTime.from_minutes(world.time.total_minutes + plan.after_minutes)
    if earlier is not None:
        attempt = world.retry_attempt(earlier.id, failure=plan.failure, turn=state.turn)
        world.set_attempt_status(attempt.id, status, reopens_if=reopens_if if closing else attempt.reopens_if, reopens_at=reopens_at)
    else:
        attempt = world.add_attempt(
            plan.who, plan.kind, plan.task, plan.about.id, status=status, scope=plan.scope if closing else "character",
            failure=plan.failure, reopens_if=reopens_if, reopens_at=reopens_at, turn=state.turn,
        )  # fmt: skip
    if closing and plan.scope == "anyone":
        attempt.scope = "anyone"
    note = _write_fact(state, attempt, failure_fact(attempt))
    if closing:
        return (
            f"Failed, and the attempt is closed ({attempt.tries} {'try' if attempt.tries == 1 else 'tries'}). Narrate "
            f"the failure with its cost ({plan.failure}) and say in the story that this way is shut to {plan.who}; the "
            f"player may try something different. It reopens only if: {attempt.reopens_if.rstrip('.')}. Make the matching record "
            f"for the cost in this same turn (a fact or a motive).{note}"
        )
    return (
        f"Failed, but it can be tried again ({attempt.tries} {'try' if attempt.tries == 1 else 'tries'}). Narrate the "
        f"failure with its cost ({plan.failure}) and what another try would risk. Each retry costs "
        f"{attempts.TYPES[plan.kind].minutes} minutes or more. Make the matching record for the cost in this same turn "
        f"(a fact or a motive).{note}"
    )


def attempts_active(state: GameState | None) -> bool:
    return state is not None and state.phase is Phase.ADVENTURE
