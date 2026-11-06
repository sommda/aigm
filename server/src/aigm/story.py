"""The story plan of a structured campaign, and the rules that move it along (docs/STORY.md).

Everything here is pure: no clock, no network, no model. The plan is data (`Story`); the functions read it and return
what should happen next. The tools, the briefing and the curator built on top of it come later."""

from dataclasses import dataclass, field
from typing import Any

from aigm.errors import CorruptSave
from aigm.world import World, WorldTime

ENDLESS = "endless"
SCALES = ("small", "medium", "large")
STATUSES = ("pending", "active", "done", "skipped", "failed")
SETTLED = frozenset({"done", "skipped"})  # a milestone in either state no longer blocks anything
CHAPTERS = (1, 2, 3)
CONCLUDED = 4  # the chapter number once an ending has been reached
MIN_ENDINGS, MAX_ENDINGS = 2, 4
MAX_CHOICES = 40  # the choices log keeps this many recent entries
PLAN_SLACK = 1  # how far a chapter's quest count may stray from the length's range before the plan is refused

LEVEL_GRACE_TURNS = 40  # turns into a chapter after which a party below its target level no longer holds it up
NUDGE_TURNS = 12  # player turns without progress before the GM is asked for a hook (docs/STORY.md 6.3)


@dataclass(frozen=True)
class Length:
    """What a game of one length looks like (docs/STORY.md 6.1). These numbers are the plotter's targets."""

    quests: tuple[int, int]  # required milestones per chapter, lowest and highest
    scales: frozenset[str]  # the sizes of quest that fit this length


LENGTHS: dict[str, Length] = {
    "short": Length((2, 3), frozenset({"small"})),
    "medium": Length((5, 6), frozenset({"small", "medium"})),
    "long": Length((10, 12), frozenset({"medium", "large"})),
}
STRUCTURES = (ENDLESS, *LENGTHS)


# ---- failure (docs/STAKES.md) -------------------------------------------------------------

COST_KINDS = ("time", "resource", "ally", "knowledge", "position")
SMALL_COST_KINDS = ("time", "resource")  # chapter 1 costs are small
MAX_COSTS = 40  # the costs log keeps this many recent entries
MAX_COST_TEXT = 300
MAX_COST_HOURS = {1: 24, 2: 72, 3: 72}  # the longest a time cost may be, by chapter
COSTS_SHOWN = 3  # the briefing lists this many recent costs
STALL_TURNS = 40  # player turns a failed required quest may wait for its repair before it is given up (STORY.md 8.2)
MOVE_HOURS = 24  # a chapter 1 deadline that passes slides this far past the moment it was missed
MAX_BACKUPS = 2  # a repair adds one or two quests


@dataclass(frozen=True)
class FailureResponse:
    """What happens when something fails in one chapter (docs/STAKES.md 3). Held as data beside `LENGTHS`."""

    quest: str  # a failed required quest: "repair" (the plan is mended) or "end" (the game ends)
    deadline: str  # a passed quest deadline: "move" (the deadline slides), "repair" or "end"
    doom: str  # a doom: "none" (not used) or "end"
    cost_required: bool  # a `failed` report needs a cost
    cost_kinds: tuple[str, ...]
    backup_quest: bool  # the repair must add a backup quest inside the existing world


RESPONSES: dict[int, FailureResponse] = {
    1: FailureResponse("repair", "move", "none", True, SMALL_COST_KINDS, False),
    2: FailureResponse("repair", "repair", "end", True, COST_KINDS, True),
    3: FailureResponse("end", "end", "end", False, COST_KINDS, False),
}


def failure_response(story: "Story", chapter: int | None = None) -> FailureResponse:
    """What failure does in a chapter (the story's current one by default). An endless or concluded story has none:
    a failed quest there only means the reward is not earned."""
    chapter = story.chapter if chapter is None else chapter
    if story.length == ENDLESS or story.concluded or chapter not in RESPONSES:
        return FailureResponse("none", "none", "none", False, (), False)
    return RESPONSES[chapter]


def record_cost(
    story: "Story", turn: int, milestone: str, kind: str, text: str, hours: int = 0, *, clock: bool = True
) -> str | None:
    """Write a cost into the story's log (docs/STAKES.md 6). Returns what is wrong with it, or None when it was kept.
    A `time` cost carries the hours the clock must move; the caller moves it. With `clock` false the cost only notes
    the lost time (a plotter's account of a failure whose hours were not reported)."""
    allowed = failure_response(story).cost_kinds
    text = " ".join(text.split())[:MAX_COST_TEXT] if isinstance(text, str) else ""
    if not allowed:
        return "this game has no costs"
    if kind not in allowed:
        return f"a cost here is one of: {', '.join(allowed)}"
    if not text:
        return "say in one sentence what the failure cost the party"
    entry: dict[str, Any] = {"turn": turn, "chapter": story.chapter, "milestone": milestone, "kind": kind, "text": text}
    if kind == "time" and clock:
        limit = MAX_COST_HOURS[story.chapter]
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= limit:
            return f"a time cost needs `cost_hours`, a whole number from 1 to {limit}"
        entry["hours"] = hours
    story.costs = [*story.costs, entry][-MAX_COSTS:]
    return None


# ---- the plan -----------------------------------------------------------------------------


@dataclass
class Chapter:
    title: str
    purpose: str  # one line for the GM
    target_level: int | None = None  # the party level to aim for by the end of the chapter (docs/STORY.md 7)

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "purpose": self.purpose, "target_level": self.target_level}


@dataclass
class Deadline:
    """A moment on the in-world clock by which a quest or doom must be settled (docs/STAKES.md 2)."""

    at: WorldTime
    cue: str = ""  # the sign in the world that shows how near it is
    fixed: bool = False  # nothing in the story can move it (a conjunction, a tide)
    start: WorldTime | None = None  # when the clock began to run on it, to tell how much of the time is gone

    def to_dict(self) -> dict[str, Any]:
        return {"at": self.at.to_dict(), "cue": self.cue, "fixed": self.fixed,
                "start": self.start.to_dict() if self.start else None}  # fmt: skip

    def used(self, now: WorldTime) -> float | None:
        """The share of the time that has gone, from 0 to 1 (None while the start is not known)."""
        if self.start is None or self.at <= self.start:
            return None
        return min(1.0, max(0.0, (now.total_minutes - self.start.total_minutes) / (self.at.total_minutes - self.start.total_minutes)))


@dataclass
class Milestone:
    id: str
    chapter: int
    title: str
    brief: str  # for the GM: what must happen, and the ways it can
    scale: str = "small"
    gives: str = ""  # what finishing it builds: a level, an ally, an item, knowledge (docs/STORY.md 7)
    requires: list[str] = field(default_factory=list)  # milestones that must be settled first
    required: bool = True  # counts toward ending its chapter
    entities: list[str] = field(default_factory=list)  # world entity ids it lives in
    status: str = "pending"
    done_turn: int | None = None
    outcome: str | None = None
    # Key items (docs/KEY_ITEMS.md 6): the item this quest is about finding, and the items the party must have had in
    # hand before the quest is offered. Entity ids.
    finds: str | None = None
    needs: list[str] = field(default_factory=list)
    # Failure (docs/STAKES.md 2): the ways the quest is lost, a time limit, and the ending that follows a failure.
    fails_if: list[str] = field(default_factory=list)
    deadline: Deadline | None = None
    ending: str | None = None
    escape: bool = False  # the quest that gets a captured party out (docs/STAKES.md 7.5)
    backup_for: str | None = None  # a repair quest: the id of the failed quest it replaces (docs/STAKES.md 5)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "chapter": self.chapter, "title": self.title, "brief": self.brief, "scale": self.scale,
            "gives": self.gives, "requires": list(self.requires), "required": self.required,
            "entities": list(self.entities), "status": self.status, "done_turn": self.done_turn,
            "outcome": self.outcome, "finds": self.finds, "needs": list(self.needs),
            "fails_if": list(self.fails_if), "deadline": self.deadline.to_dict() if self.deadline else None,
            "ending": self.ending, "backup_for": self.backup_for, "escape": self.escape,
        }  # fmt: skip


@dataclass
class Goal:
    title: str
    summary: str  # hidden from the player until it is revealed
    entities: list[str] = field(default_factory=list)
    revealed: bool = False
    min_strength: str = ""  # in plain words: what the party needs to have (docs/STORY.md 7)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "summary": self.summary, "entities": list(self.entities),
            "revealed": self.revealed, "min_strength": self.min_strength,
        }  # fmt: skip


@dataclass
class Ending:
    id: str
    title: str
    when: str  # the situation that produces it

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "when": self.when}


@dataclass
class Doom:
    """A way to lose that belongs to no one quest (docs/STAKES.md 2.1)."""

    id: str
    when: str  # the situation, for the GM only
    chapters: list[int] = field(default_factory=list)  # the chapters it applies in (never 1)
    deadline: Deadline | None = None
    ending: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "when": self.when, "chapters": list(self.chapters),
            "deadline": self.deadline.to_dict() if self.deadline else None, "ending": self.ending,
        }  # fmt: skip


@dataclass
class Story:
    length: str
    goal: Goal | None = None  # None until the plotter has written the plan
    chapters: list[Chapter] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)
    endings: list[Ending] = field(default_factory=list)
    choices: list[dict[str, Any]] = field(default_factory=list)  # {"turn", "milestone", "note"}
    chapter: int = 1
    chapter_started_turn: int = 1
    last_progress_turn: int = 1
    ending: str | None = None  # the id of the ending reached
    epilogue: str | None = None
    party_level: float = 1.0  # the party's average level, kept current by the `award` tool (docs/PROGRESSION.md)
    dooms: list[Doom] = field(default_factory=list)
    costs: list[dict[str, Any]] = field(default_factory=list)  # {"turn", "chapter", "milestone", "kind", "text"}
    wipes: int = 0  # chapter 2 total party defeats so far (docs/STAKES.md 7.5)
    # A captured party's way out is waiting to be written: {"turn", "held" (where and by whom), "hours" (the time they
    # have, or None when it does not matter)} (docs/STAKES.md 7.5)
    escape: dict[str, Any] | None = None
    fall: dict[str, Any] | None = None  # the game is lost: {"turn", "ending" (id or None), "why"} (docs/STAKES.md 3)

    @property
    def planned(self) -> bool:
        return self.goal is not None

    @property
    def concluded(self) -> bool:
        return self.chapter == CONCLUDED

    def has_ending(self, ending_id: str) -> bool:
        return any(e.id == ending_id for e in self.endings)

    def milestone(self, milestone_id: str) -> Milestone | None:
        return next((m for m in self.milestones if m.id == milestone_id), None)

    def in_chapter(self, chapter: int) -> list[Milestone]:
        return [m for m in self.milestones if m.chapter == chapter]

    def copy(self) -> "Story":
        return Story.from_dict(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "length": self.length,
            "goal": self.goal.to_dict() if self.goal else None,
            "chapters": [c.to_dict() for c in self.chapters],
            "milestones": [m.to_dict() for m in self.milestones],
            "endings": [e.to_dict() for e in self.endings],
            "choices": [dict(c) for c in self.choices],
            "chapter": self.chapter,
            "chapter_started_turn": self.chapter_started_turn,
            "last_progress_turn": self.last_progress_turn,
            "ending": self.ending,
            "epilogue": self.epilogue,
            "party_level": self.party_level,
            "dooms": [d.to_dict() for d in self.dooms],
            "costs": [dict(c) for c in self.costs],
            "wipes": self.wipes,
            "fall": dict(self.fall) if self.fall else None,
            "escape": dict(self.escape) if self.escape else None,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "Story":
        """Read a saved story. Anything malformed is a corrupt save."""
        try:
            return _read_story(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptSave(f"the story is unreadable: {exc}") from None


# ---- reading a saved story ----------------------------------------------------------------


def _text(raw: dict[str, Any], key: str, *, optional: bool = False) -> str:
    value = raw.get(key)
    if value is None and optional:
        return ""
    if not isinstance(value, str) or (not optional and not value.strip()):
        raise ValueError(f"'{key}' must be a non-empty string" if not optional else f"'{key}' must be a string")
    return value


def _int(raw: dict[str, Any], key: str, minimum: int = 0) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"'{key}' must be an integer of at least {minimum}")
    return value


def _level(value: Any) -> float:
    if value is None:
        return 1.0
    if isinstance(value, bool) or not isinstance(value, int | float) or not 1 <= value <= 20:
        raise ValueError("'party_level' must be a number from 1 to 20")
    return float(value)


def _opt_int(raw: dict[str, Any], key: str) -> int | None:
    return None if raw.get(key) is None else _int(raw, key)


def _strings(raw: dict[str, Any], key: str) -> list[str]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"'{key}' must be a list of strings")
    return list(value)


def _objects(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise ValueError(f"'{key}' must be a list of objects")
    return value


def _read_deadline(raw: Any) -> Deadline | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("'deadline' must be an object or null")
    fixed = raw.get("fixed", False)
    if not isinstance(fixed, bool):
        raise ValueError("'fixed' must be true or false")
    try:
        at = WorldTime.from_dict(raw.get("at"))
    except ValueError as exc:  # WorldError is a ValueError
        raise ValueError(f"the deadline's time is invalid: {exc}") from None
    start = WorldTime.from_dict(raw["start"]) if raw.get("start") is not None else None
    return Deadline(at, _text(raw, "cue", optional=True), fixed, start)


def _read_doom(raw: dict[str, Any]) -> Doom:
    chapters = raw.get("chapters", [])
    if not isinstance(chapters, list) or not all(c in (2, 3) and not isinstance(c, bool) for c in chapters):
        raise ValueError("a doom's 'chapters' must be a list of 2 and 3")
    ending = raw.get("ending")
    if ending is not None and not isinstance(ending, str):
        raise ValueError("'ending' must be a string or null")
    return Doom(_text(raw, "id"), _text(raw, "when"), list(chapters), _read_deadline(raw.get("deadline")), ending)


def _read_fall(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("'fall' must be an object or null")
    ending = raw.get("ending")
    if ending is not None and not isinstance(ending, str):
        raise ValueError("'ending' must be a string or null")
    return {"turn": _int(raw, "turn"), "ending": ending, "why": _text(raw, "why")}


def _read_escape(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("'escape' must be an object or null")
    return {"turn": _int(raw, "turn"), "held": _text(raw, "held"), "hours": _opt_int(raw, "hours")}


def _read_cost(raw: dict[str, Any]) -> dict[str, Any]:
    kind = raw.get("kind")
    if kind not in COST_KINDS:
        raise ValueError(f"unknown cost kind {kind!r}")
    return {
        "turn": _int(raw, "turn"), "chapter": _int(raw, "chapter", 1),
        "milestone": _text(raw, "milestone", optional=True), "kind": kind, "text": _text(raw, "text"),
        **({"hours": _int(raw, "hours", 1)} if raw.get("hours") is not None else {}),
    }  # fmt: skip


def _read_milestone(raw: dict[str, Any]) -> Milestone:
    scale, status = raw.get("scale", "small"), raw.get("status", "pending")
    if scale not in SCALES:
        raise ValueError(f"unknown quest scale {scale!r}")
    if status not in STATUSES:
        raise ValueError(f"unknown milestone status {status!r}")
    chapter = _int(raw, "chapter", 1)
    if chapter not in CHAPTERS:
        raise ValueError(f"milestone chapter must be 1, 2 or 3, not {chapter}")
    required = raw.get("required", True)
    if not isinstance(required, bool):
        raise ValueError("'required' must be true or false")
    outcome = raw.get("outcome")
    if outcome is not None and not isinstance(outcome, str):
        raise ValueError("'outcome' must be a string or null")
    finds = raw.get("finds")
    if finds is not None and not isinstance(finds, str):
        raise ValueError("'finds' must be a string or null")
    ending, backup_for = raw.get("ending"), raw.get("backup_for")
    for name, value in (("ending", ending), ("backup_for", backup_for)):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"'{name}' must be a string or null")
    return Milestone(
        id=_text(raw, "id"), chapter=chapter, title=_text(raw, "title"), brief=_text(raw, "brief"), scale=scale,
        gives=_text(raw, "gives", optional=True), requires=_strings(raw, "requires"), required=required,
        entities=_strings(raw, "entities"), status=status, done_turn=_opt_int(raw, "done_turn"), outcome=outcome,
        finds=finds, needs=_strings(raw, "needs"), fails_if=_strings(raw, "fails_if"),
        deadline=_read_deadline(raw.get("deadline")), ending=ending, backup_for=backup_for,
        escape=raw.get("escape") is True,
    )  # fmt: skip


def _read_story(raw: Any) -> Story:
    if not isinstance(raw, dict):
        raise ValueError("it must be an object")
    length = raw.get("length")
    if length not in LENGTHS:
        raise ValueError(f"unknown length {length!r}")
    goal = None
    if raw.get("goal") is not None:
        g = raw["goal"]
        if not isinstance(g, dict):
            raise ValueError("'goal' must be an object or null")
        revealed = g.get("revealed", False)
        if not isinstance(revealed, bool):
            raise ValueError("'revealed' must be true or false")
        goal = Goal(
            _text(g, "title"), _text(g, "summary"), _strings(g, "entities"), revealed,
            _text(g, "min_strength", optional=True),
        )  # fmt: skip
    chapters = []
    for c in _objects(raw, "chapters"):
        level = _opt_int(c, "target_level")
        chapters.append(Chapter(_text(c, "title"), _text(c, "purpose", optional=True), level))
    milestones = [_read_milestone(m) for m in _objects(raw, "milestones")]
    ids = [m.id for m in milestones]
    if len(set(ids)) != len(ids):
        raise ValueError("milestone ids must be unique")
    for m in milestones:
        unknown = [r for r in m.requires if r not in ids]
        if unknown:
            raise ValueError(f"milestone {m.id} requires unknown {unknown[0]}")
    endings = [Ending(_text(e, "id"), _text(e, "title"), _text(e, "when")) for e in _objects(raw, "endings")]
    if len({e.id for e in endings}) != len(endings):
        raise ValueError("ending ids must be unique")
    choices = []
    for c in _objects(raw, "choices"):
        choices.append({"turn": _int(c, "turn"), "milestone": _text(c, "milestone", optional=True), "note": _text(c, "note")})
    dooms = [_read_doom(d) for d in _objects(raw, "dooms")]
    if len({d.id for d in dooms}) != len(dooms):
        raise ValueError("doom ids must be unique")
    costs = [_read_cost(c) for c in _objects(raw, "costs")]
    chapter = _int(raw, "chapter", 1)
    if chapter > CONCLUDED:
        raise ValueError(f"chapter must be 1 to {CONCLUDED}")
    ending, epilogue = raw.get("ending"), raw.get("epilogue")
    for name, value in (("ending", ending), ("epilogue", epilogue)):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"'{name}' must be a string or null")
    return Story(
        length=length, goal=goal, chapters=chapters, milestones=milestones, endings=endings, choices=choices,
        chapter=chapter, chapter_started_turn=_int(raw, "chapter_started_turn"),
        last_progress_turn=_int(raw, "last_progress_turn"), ending=ending, epilogue=epilogue,
        party_level=_level(raw.get("party_level")), dooms=dooms, costs=costs, wipes=_int(raw, "wipes") if "wipes" in raw else 0,
        fall=_read_fall(raw.get("fall")), escape=_read_escape(raw.get("escape")),
    )  # fmt: skip


# ---- checking a plan ----------------------------------------------------------------------


def validate_plan(story: Story, world: World | None = None) -> list[str]:
    """What is wrong with a plan the plotter wrote, as plain sentences (empty: it is acceptable).

    Only the chapters that have milestones are checked, because a long game plans its later chapters when it reaches
    them. With a `world`, the entities the plan names must exist in it."""
    problems: list[str] = []
    if story.goal is None:
        problems.append("the plan has no goal")
    if not MIN_ENDINGS <= len(story.endings) <= MAX_ENDINGS:
        problems.append(f"the plan needs {MIN_ENDINGS} to {MAX_ENDINGS} endings, not {len(story.endings)}")
    length = LENGTHS[story.length]
    low, high = length.quests
    for chapter in CHAPTERS:
        group = story.in_chapter(chapter)
        if not group:
            continue
        required = sum(m.required for m in group)
        if not max(1, low - PLAN_SLACK) <= required <= high + PLAN_SLACK:
            problems.append(
                f"chapter {chapter} has {required} required quests; a {story.length} game wants {low} to {high}"
            )
    for m in story.milestones:
        if m.scale not in length.scales:
            problems.append(f"{m.id} is a {m.scale} quest, which does not fit a {story.length} game")
        if m.id in m.requires:
            problems.append(f"{m.id} requires itself")
    problems += _graph_problems(story)
    problems += _strength_problems(story)
    problems += _item_problems(story, world)
    if world is not None:
        named = [(story.goal.title if story.goal else "the goal", story.goal.entities if story.goal else [])]
        named += [(m.id, m.entities) for m in story.milestones]
        for label, ids in named:
            for entity_id in ids:
                if world.entity(entity_id) is None:
                    problems.append(f"{label} names {entity_id}, which is not in the world")
    return problems


def stakes_problems(story: Story, chapters: tuple[int, ...], now: WorldTime | None = None) -> list[str]:
    """What is wrong with the failure side of a plan the plotter wrote (docs/STAKES.md 2.2): how many ways each quest can
    fail, the endings of chapter 3, the dooms, and deadlines that are not in the future. Only the `chapters` just
    written are checked."""
    problems: list[str] = []
    for chapter in chapters:
        required = [m for m in story.in_chapter(chapter) if m.required]
        for m in required:
            n = len(m.fails_if)
            if chapter == 1 and n > 1:
                problems.append(f"{m.id}: chapter 1 quests have at most one way to fail, not {n}")
            if chapter == 2 and n > 2:
                problems.append(f"{m.id}: chapter 2 quests have one or two ways to fail, not {n}")
            if chapter == 3:
                want = 5 if m is required[-1] else 3
                if n < want:
                    problems.append(
                        f"{m.id}: chapter 3 is a gauntlet: give it at least {want} different ways to fail "
                        f"(a person, an object, a place, a rival, a clock, a choice), not {n}"
                    )
                if not m.ending:
                    problems.append(f"{m.id}: every chapter 3 quest needs an `ending` that follows its failure")
        if chapter == 2 and required and not any(m.fails_if for m in required):
            problems.append("chapter 2 needs some quests with ways to fail: give about half of them one or two")
        low, high = {2: (1, 3), 3: (3, 6)}.get(chapter, (0, 0))
        n = sum(chapter in d.chapters for d in story.dooms)
        if chapter > 1 and not low <= n <= high:
            problems.append(f"chapter {chapter} needs {low} to {high} dooms (ways the whole game is lost), not {n}")
    for d in story.dooms:
        if not d.ending:
            problems.append(f"doom {d.id} needs an `ending` that follows it")
    if now is not None:
        for title, dl in [(m.id, m.deadline) for m in story.milestones if m.deadline] + [
            (d.id, d.deadline) for d in story.dooms if d.deadline
        ]:
            if dl.at <= now:
                problems.append(f"{title}: its deadline ({dl.at}) is not after the time now ({now})")
            if not dl.cue.strip():
                problems.append(f"{title}: a deadline needs a `cue`, the sign in the world of how near it is")
    return problems


def _item_problems(story: Story, world: World | None) -> list[str]:
    """The key items a plan names (docs/KEY_ITEMS.md 6.2): they must be key items of the world, a quest cannot both find
    and need the same item, and an item a quest needs must be one the party can get: some quest finds it, or the world
    says where it is. Whether the quests that find and need an item can be reached in order is `_graph_problems`."""
    problems: list[str] = []
    found_by = {m.finds for m in story.milestones if m.finds}
    for m in story.milestones:
        if m.finds and m.finds in m.needs:
            problems.append(f"{m.id} both finds and needs the same item")
        if world is None:
            continue
        for item_id in [*([m.finds] if m.finds else []), *m.needs]:
            ent = world.entity(item_id)
            if ent is None or ent.kind != "item":
                problems.append(f"{m.id} names {item_id}, which is not a key item of the world")
        for item_id in m.needs:
            ent = world.entity(item_id)
            if ent is None or ent.kind != "item" or item_id in found_by:
                continue
            if not any(f.subject == item_id and f.aspect == "whereabouts" for f in world.facts_about(item_id)):
                problems.append(f"{m.id} needs {ent.name}, but no quest finds it and the world does not say where it is")
    return problems


def _strength_problems(story: Story) -> list[str]:
    """The goal must be out of the party's reach at first, and the quests must build the way there (section 7).

    The server cannot measure strength, so this checks the plan: the goal says what it needs, and the last quest of
    the last planned chapter depends on at least one quest that gives the party something. A short game is exempt."""
    if story.length == "short" or story.goal is None:
        return []
    problems = []
    if not story.goal.min_strength.strip():
        problems.append("the goal does not say what strength the party needs (min_strength)")
    last = max((m.chapter for m in story.milestones), default=0)
    if last == CHAPTERS[-1]:
        by_id = {m.id: m for m in story.milestones}
        needed = {r for m in story.milestones for r in m.requires}
        finals = [m for m in story.in_chapter(last) if m.required and m.id not in needed]
        for final in finals:
            seen: set[str] = set()
            stack = list(final.requires)
            while stack:
                m = by_id[stack.pop()]
                if m.id not in seen:
                    seen.add(m.id)
                    stack += m.requires
            if not any(by_id[i].gives.strip() for i in seen):
                problems.append(f"{final.id} does not depend on any quest that builds up the party (gives)")
    return problems


def _graph_problems(story: Story) -> list[str]:
    """Cycles, quests that wait on a later chapter, and required quests that nothing can ever open."""
    problems: list[str] = []
    by_id = {m.id: m for m in story.milestones}
    for m in story.milestones:
        for r in m.requires:
            if by_id[r].chapter > m.chapter:
                problems.append(f"{m.id} (chapter {m.chapter}) requires {r}, which is in chapter {by_id[r].chapter}")
    # A quest that needs an item can be offered once the quest that finds the item can be reached (it is a link too).
    finders = {m.finds: m for m in story.milestones if m.finds}
    waits: dict[str, list[str]] = {}
    for m in story.milestones:
        waits[m.id] = list(m.requires)
        for item in m.needs:
            finder = finders.get(item)
            if finder is not None and finder.id != m.id:
                waits[m.id].append(finder.id)
                if finder.chapter > m.chapter:
                    problems.append(
                        f"{m.id} (chapter {m.chapter}) needs an item that {finder.id}, in chapter {finder.chapter}, finds"
                    )
    # A milestone can be reached when everything it requires can be reached: peel off the ones with no open needs.
    reached: set[str] = set()
    progress = True
    while progress:
        progress = False
        for m in story.milestones:
            if m.id not in reached and all(r in reached for r in waits[m.id]):
                reached.add(m.id)
                progress = True
    for m in story.milestones:
        if m.id not in reached:
            problems.append(f"{m.id} can never become available (a cycle, or it waits on one)")
    return problems


# ---- moving through the story -------------------------------------------------------------


def items_in_hand(world: World | None, item_ids: list[str]) -> bool:
    """Has the party had every one of these key items in hand at some time? (Used or lost ones count: a quest an
    item opens is not taken away when the item is spent.) Without a world, only an empty list is satisfied."""
    if not item_ids:
        return True
    if world is None:
        return False
    return all((e := world.entity(i)) is not None and e.holding is not None and e.holding.acquired for i in item_ids)


def settle_ready(story: Story, world: World | None = None) -> list[str]:
    """Make the milestones of the current chapter whose requirements are settled, and whose key items the party has
    had, active. Returns the ids opened. A quest that needs an item stays pending without a `world` to check it in."""
    opened = []
    for m in story.in_chapter(story.chapter):
        if m.status == "pending" and items_in_hand(world, m.needs) and all(
            (r := story.milestone(req)) is not None and r.status in SETTLED for req in m.requires
        ):
            m.status = "active"
            opened.append(m.id)
    if world is not None:
        stamp_deadlines(story, world)
    return opened


def stamp_deadlines(story: Story, world: World) -> None:
    """Start the clock on every live deadline that has none (an active quest's, a current doom's), so the briefing can
    say how much of the time is gone."""
    for _title, dl in _live_deadlines(story):
        if dl.start is None:
            dl.start = world.time


def active(story: Story) -> list[Milestone]:
    return [m for m in story.in_chapter(story.chapter) if m.status == "active"]


@dataclass(frozen=True)
class Due:
    """Something that has failed on the clock (docs/STAKES.md 10). `kind` is "quest" or "doom"."""

    kind: str
    id: str
    text: str  # the quest's title or the doom's situation
    ending: str | None
    action: str  # what the chapter does about it: "move", "repair" or "end"
    fixed: bool
    deadline: Deadline


def due_failures(story: Story, world: World) -> list[Due]:
    """Every active quest and every doom of the current chapter whose deadline the clock has passed. Pure: the caller
    decides what to do about each. A quest already settled, and a story without stakes, report nothing."""
    response = failure_response(story)
    if response.deadline == "none" and response.doom == "none":
        return []
    out: list[Due] = []
    if response.deadline != "none":
        for m in active(story):
            if m.deadline is not None and m.deadline.at <= world.time:
                out.append(Due("quest", m.id, m.title, m.ending, response.deadline, m.deadline.fixed, m.deadline))
    if response.doom != "none":
        for d in story.dooms:
            if story.chapter in d.chapters and d.deadline is not None and d.deadline.at <= world.time:
                out.append(Due("doom", d.id, d.when, d.ending, response.doom, d.deadline.fixed, d.deadline))
    return out


# ---- losing the game (docs/STAKES.md 3, 5, 10) -----------------------------------------------


def lose(story: Story, turn: int, why: str, ending: str | None = None) -> bool:
    """The game is lost: the GM must play out the ending and call `end_story`. Only the first loss counts, and only
    where failure ends the game; returns whether this call set it."""
    if story.fall is not None or story.concluded or not story.planned:
        return False
    story.fall = {"turn": turn, "ending": ending if ending and story.has_ending(ending) else None, "why": why.strip()}
    return True


def doom_ending(story: Story, ending_id: str) -> Doom | None:
    """The doom of this chapter whose ending this is, if any (the GM may end a chapter 2 game with one)."""
    return next((d for d in story.dooms if story.chapter in d.chapters and d.ending == ending_id), None)


def forced_ending(story: Story, turn: int, stall: int = STALL_TURNS) -> "Progress | None":
    """A lost game whose GM never called `end_story` is ended by the server after `stall` player turns."""
    if story.fall is None or story.concluded or turn - story.fall["turn"] < stall:
        return None
    return conclude(story, story.fall["ending"] or "end_custom", f"The story ended in failure: {story.fall['why']}")


# ---- defeat of the whole party (docs/STAKES.md 7.5) --------------------------------------

DEFEAT_HOWS = ("taken", "left", "routed")
WIPE_HOURS = (24, 72, 120)  # the least a chapter 2 wipe takes, by the number of wipes so far; then 24 more each time
WIPE_PRICES = (
    "gear taken, or a day or two lost",
    "a companion lost or captured, or a key item put out of reach",
    "a major ally or item gone for good, the enemy well ahead",
)
MAX_DEFEAT_HOURS = {1: 24, 2: 240}
CAPTURE_RESERVE_SHARE = 1 / 3  # of the time left when the party was taken, kept for the escape and the way back
CAPTURE_RESERVE_MIN = 12  # hours


def wipe_minimum(wipes: int) -> int:
    """The least hours a chapter 2 defeat takes, given how many wipes there have been including this one."""
    return WIPE_HOURS[wipes - 1] if wipes <= len(WIPE_HOURS) else WIPE_HOURS[-1] + 24 * (wipes - len(WIPE_HOURS))


def _live_deadlines(story: Story) -> list[tuple[str, Deadline]]:
    found = [(m.title, m.deadline) for m in active(story) if m.deadline is not None]
    found += [(d.when, d.deadline) for d in story.dooms if story.chapter in d.chapters and d.deadline is not None]
    return found


def protect_capture(story: Story, world: World, turn: int, hours: int) -> tuple[int, list[str], int | None]:
    """A capture never costs the party the game (docs/STAKES.md 7.5.2). A deadline people set is pushed back by the
    captivity; a fixed one cannot move, so the captivity is shortened to leave a reserve before it. Changes the story's
    deadlines and costs. Returns the hours the captivity may last, notes for the GM, and the hours the party will have
    left for the escape (None: no fixed deadline limits it)."""
    notes: list[str] = []
    cap = hours
    fixed = []  # the hours left before each fixed deadline, now
    for _title, dl in _live_deadlines(story):
        remaining = (dl.at.total_minutes - world.time.total_minutes) // 60
        if remaining <= 0 or not dl.fixed:
            continue
        reserve = max(CAPTURE_RESERVE_MIN, int(remaining * CAPTURE_RESERVE_SHARE))
        cap = min(cap, max(0, remaining - reserve))
        fixed.append(remaining)
    left = [r - cap for r in fixed]
    shift = cap
    for title, dl in _live_deadlines(story):
        if dl.fixed or dl.at.total_minutes <= world.time.total_minutes:
            continue
        dl.at = dl.at.plus(shift)
        text = f"The enemy's plan for {title} was held up while the party was held, so its time slid {shift} hours too."
        story.costs = [*story.costs, {"turn": turn, "chapter": story.chapter, "milestone": "", "kind": "time",
                                      "text": text}][-MAX_COSTS:]  # fmt: skip
        notes.append(f"{title}: its time limit slid {shift} hours; show in the fiction why the enemy was held up too.")
    if cap < hours:
        notes.append(f"The captivity was cut to {cap} hours so a fixed deadline still leaves the party time.")
    return cap, notes, (min(left) if left else None)


# ---- repairing a plan (docs/STORY.md 8.2, docs/STAKES.md 4, 5) ---------------------------


def needs_repair(story: Story) -> Milestone | None:
    """A required quest of the current chapter that failed and has not been mended: the chapter cannot end while it
    stands, so the plotter is asked for a way round. A repaired quest stops being required (the backup takes its
    place in the chapter's count)."""
    if story.concluded or not story.planned or failure_response(story).quest != "repair":
        return None
    return next((m for m in story.in_chapter(story.chapter) if m.required and m.status == "failed"), None)


def repair_depth(story: Story, quest: Milestone) -> int:
    """How many times this line of the story has failed, the quest itself included (1 for a first failure)."""
    depth, seen = 1, {quest.id}
    while quest.backup_for and quest.backup_for not in seen and (earlier := story.milestone(quest.backup_for)):
        seen.add(earlier.id)
        quest, depth = earlier, depth + 1
    return depth


def apply_repair(story: Story, failed_id: str, backups: list[Milestone], world: World | None = None) -> list[str]:
    """Put the backup quests in the failed one's place. They inherit what it required; whatever required it requires
    them instead (the ones nothing else among them waits on). The failed quest stays in the log, no longer counted.
    Returns the ids that became active."""
    failed = story.milestone(failed_id)
    if failed is None or not backups:
        return []
    inside = {b.id for b in backups}
    for b in backups:
        b.backup_for, b.required, b.chapter = failed.id, True, failed.chapter
        if not any(r in inside for r in b.requires):
            b.requires = list(dict.fromkeys([*failed.requires, *b.requires]))
    leaves = [b.id for b in backups if not any(b.id in o.requires for o in backups)]
    for m in story.milestones:
        if failed.id in m.requires:
            m.requires = list(dict.fromkeys(x for r in m.requires for x in (leaves if r == failed.id else [r])))
    failed.required = False
    story.milestones += backups
    story.last_progress_turn = max(story.last_progress_turn, failed.done_turn or 0)
    return settle_ready(story, world)


def expire_failed(story: Story, turn: int, stall: int = STALL_TURNS) -> list[str]:
    """A failed required quest that no repair has mended for `stall` player turns is given up as skipped, so a game can
    never stick for good. Returns the ids given up."""
    gone = []
    for m in story.in_chapter(story.chapter):
        if m.required and m.status == "failed" and m.done_turn is not None and turn - m.done_turn >= stall:
            m.status = "skipped"
            m.outcome = f"{m.outcome or 'It failed.'} (No way round was found; the story moved on.)"
            gone.append(m.id)
    if gone:
        settle_ready(story)
        if chapter_complete(story, turn):
            advance_chapter(story, turn)
            settle_ready(story)
    return gone


def settle_due(story: Story, world: World, turn: int) -> list[str]:
    """Act on the clock after a turn (docs/STAKES.md 3): a deadline whose passing ends the game (any in chapter 3, a
    doom's in chapter 2) loses it; in chapter 1 a deadline that has passed slides a day past the
    moment it was missed and the delay is written down; in chapter 2 a quest whose time ran out fails, at a cost, and
    waits for its repair. Returns notes for the log."""
    notes = []
    for due in due_failures(story, world):
        if due.action == "end":
            why = f"the time for {due.text} ran out" if due.kind == "quest" else f"{due.text}: the time is up"
            if lose(story, turn, why, due.ending):
                notes.append(why)
            continue
        if due.kind != "quest":
            continue
        quest = story.milestone(due.id)
        if quest is None:
            continue
        if due.action == "move":
            assert quest.deadline is not None
            quest.deadline = Deadline(world.time.plus(MOVE_HOURS), quest.deadline.cue, quest.deadline.fixed)
            text = f"The time for {quest.title} ran out, but the world was delayed too: its limit slid a day."
            story.costs = [*story.costs, {"turn": turn, "chapter": story.chapter, "milestone": quest.id,
                                          "kind": "time", "text": text}][-MAX_COSTS:]  # fmt: skip
            notes.append(text)
        elif due.action == "repair":
            quest.status, quest.done_turn, quest.deadline = "failed", turn, None
            quest.outcome = f"The time for {quest.title} ran out."
            story.last_progress_turn = turn
            record_cost(story, turn, quest.id, "position", f"The time for {quest.title} ran out and the enemy gained ground.")
            notes.append(quest.outcome)
    return notes


def level_short(story: Story, turn: int | None = None) -> bool:
    """Is the party's average level below what this chapter aims for? Only chapters 1 and 2 are held up by it, and
    only for `LEVEL_GRACE_TURNS` turns (when the turn is known): the story must not stall on a party that cannot earn it."""
    if story.chapter not in (1, 2) or story.chapter > len(story.chapters):
        return False
    target = story.chapters[story.chapter - 1].target_level
    if not target or story.party_level + 1e-9 >= target:
        return False
    return turn is None or turn - story.chapter_started_turn < LEVEL_GRACE_TURNS


def chapter_complete(story: Story, turn: int | None = None) -> bool:
    """Every required quest of the chapter is settled, in chapter 1 the goal is known, and the party's average level
    has reached the chapter's target (docs/STORY.md 6.2, docs/PROGRESSION.md)."""
    if story.concluded:
        return False
    group = story.in_chapter(story.chapter)
    if not group or any(m.required and m.status not in SETTLED for m in group):
        return False
    if story.chapter == 1 and not (story.goal and story.goal.revealed):
        return False
    return not level_short(story, turn)


@dataclass
class Progress:
    ok: bool
    message: str
    opened: list[str] = field(default_factory=list)  # milestones that became active
    advanced_to: int | None = None  # the chapter the story moved into, if it did


def report(
    story: Story, milestone_id: str, status: str, outcome: str, turn: int, world: World | None = None
) -> Progress:
    """The GM says a milestone is `done`, `skipped` or `failed`. Changes the story only when the report is valid."""
    if story.concluded:
        return Progress(False, "the story has ended")
    if status not in ("done", "skipped", "failed"):
        return Progress(False, f"status must be done, skipped or failed, not {status!r}")
    milestone = story.milestone(milestone_id)
    if milestone is None:
        return Progress(False, f"there is no milestone {milestone_id!r}")
    if milestone.status != "active":
        return Progress(False, f"{milestone_id} is {milestone.status}, not active")
    if not outcome.strip():
        return Progress(False, "an outcome is required: say in a sentence what happened")
    if story.fall is not None and status != "failed":
        return Progress(False, "the story is ending in failure, and no quest can be finished now")
    milestone.status, milestone.outcome, milestone.done_turn = status, outcome.strip(), turn
    story.last_progress_turn = turn
    if status == "done" and outcome.strip():
        story.choices = [*story.choices, {"turn": turn, "milestone": milestone_id, "note": outcome.strip()}][
            -MAX_CHOICES:
        ]
    if status == "failed" and milestone.required and failure_response(story, milestone.chapter).quest == "end":
        lose(story, turn, f"{milestone.title} failed: {milestone.outcome}", milestone.ending)
        return Progress(True, f"{milestone_id} is now failed")
    opened = settle_ready(story, world)
    advanced = None
    if chapter_complete(story, turn):
        advanced = advance_chapter(story, turn)
        opened += settle_ready(story, world)
    return Progress(True, f"{milestone_id} is now {status}", opened, advanced)


def advance_chapter(story: Story, turn: int) -> int:
    """Move to the next chapter (chapter 3 is the last; an ending concludes the story, not this)."""
    story.chapter = min(story.chapter + 1, CHAPTERS[-1])
    story.chapter_started_turn = story.last_progress_turn = turn
    return story.chapter


def conclude(story: Story, ending_id: str, epilogue: str) -> Progress:
    """An ending was reached. A listed ending id, or `end_custom` for one the plan did not foresee."""
    if story.concluded:
        return Progress(False, "the story has already ended")
    if ending_id != "end_custom" and all(e.id != ending_id for e in story.endings):
        return Progress(False, f"there is no ending {ending_id!r}")
    story.ending, story.epilogue, story.chapter = ending_id, epilogue.strip(), CONCLUDED
    return Progress(True, "the story has ended")


def pace(story: Story, turn: int, nudge_turns: int = NUDGE_TURNS) -> int:
    """How hard the GM should steer: 0 none, 1 offer a hook, 2 bring a concrete consequence (docs/STORY.md 6.3)."""
    if story.concluded or not story.planned or nudge_turns < 1:
        return 0
    idle = turn - story.last_progress_turn
    return 2 if idle >= 2 * nudge_turns else 1 if idle >= nudge_turns else 0


def needs_plan(story: Story) -> int | None:
    """The chapter whose quests have not been written yet, when the story has reached it (docs/STORY.md 5)."""
    if story.concluded or not story.planned or story.chapter == 1:
        return None
    return None if story.in_chapter(story.chapter) else story.chapter


def summary_so_far(story: Story) -> str:
    """The story up to now as plain text, for the plotter that writes the next chapter."""
    goal = story.goal
    lines = []
    if goal:
        lines.append(f"Goal: {goal.title}. {goal.summary} Needs: {goal.min_strength or 'not stated'}.")
    for i, chapter in enumerate(story.chapters, 1):
        lines.append(f'Chapter {i}: "{chapter.title}" ({chapter.purpose}); aim for level {chapter.target_level or "?"}.')
    for m in story.milestones:
        done = f"{m.status}" + (f": {m.outcome}" if m.outcome else "")
        lines.append(f"- {m.id} (chapter {m.chapter}, {m.scale}) {m.title} [{done}]. Gave: {m.gives or 'nothing'}.")
    for e in story.endings:
        lines.append(f"Ending {e.id}: {e.title}. {e.when}")
    for d in story.dooms:
        lines.append(f"Doom {d.id} (chapters {', '.join(map(str, d.chapters))}): {d.when} -> {d.ending or 'no ending'}.")
    return "\n".join(lines)


def public_summary(story: Story | None) -> dict[str, Any] | None:
    """What a client may be told about the story: no goal, quests or endings (docs/STORY.md 11)."""
    if story is None or not story.planned:
        return None
    out: dict[str, Any] = {
        "length": story.length,
        "chapter": story.chapter,
        "chapter_title": chapter_label(story),
        "ended": story.concluded,
    }
    if story.concluded:
        out["ending"] = next((e.title for e in story.endings if e.id == story.ending), "")
    return out


def chapter_label(story: Story) -> str:
    """The chapter's title for status lines and the public summary ("" while the plan is unwritten)."""
    if story.concluded:
        return "The end"
    if 1 <= story.chapter <= len(story.chapters):
        return story.chapters[story.chapter - 1].title
    return ""


# ---- what may be added to the world -------------------------------------------------------


def addition_allowed(story: Story | None, world: World, kind: str, parent: str | None) -> tuple[bool, str]:
    """May a new entity of this kind be added now? Chapters 2 and 3 take no major additions (docs/STORY.md 6.4):
    no new factions or concepts, and no new region or settlement; a room, cave or stall inside a place, and any
    person, are details and stay allowed. `parent` is an entity id or name."""
    if story is None or story.chapter == 1 or story.concluded:
        return True, ""
    if kind in ("npc", "item"):  # a person or a key item is a detail, not a major addition
        return True, ""
    if kind != "location":
        return False, f"a new {kind} is a major addition, and this chapter takes only details"
    parent_entity = world.resolve(parent) if parent else None
    if parent_entity is None or parent_entity.parent is None:
        return False, "a new region or settlement is a major addition; place it inside an existing place instead"
    return True, ""



# ---- what the GM is told each turn --------------------------------------------------------

MAX_ACTIVE_SHOWN = 3
CHOICES_SHOWN = 5
REVEAL_NUDGE_SHARE = 2 / 3  # of chapter 1's required quests settled: clues about the goal should get plainer


def _names(world: World, ids: list[str]) -> str:
    return ", ".join(e.name for i in ids if (e := world.entity(i)) is not None)


def _item_note(world: World, m: Milestone) -> str:
    """For an active quest, the key item it is about, and where the party stands with it (docs/KEY_ITEMS.md 6.1)."""
    item = world.entity(m.finds) if m.finds else None
    if item is None or item.holding is None:
        return ""
    stand = {
        "unfound": "the party has not heard of it yet: let them hear of it this chapter, then call key_item `learned`",
        "known": "the party knows of it and is looking for it",
        "held": "the party has it",
        "used": "the party had it and used it up",
        "lost": "the party had it and lost it",
    }[item.holding.status]
    return f" Finding: {item.name} ({stand})."


def _fall_block(story: Story, turn: int) -> str:
    fall = story.fall
    assert fall is not None
    ending = next((e for e in story.endings if e.id == fall["ending"]), None)
    play = (
        f'the ending "{ending.title}" ({ending.id}): {ending.when}'
        if ending
        else "the failure ending that fits best (the ones listed below), or `end_custom` if none does"
    )
    left = max(0, STALL_TURNS - (turn - fall["turn"]))
    lines = [
        f"THE STORY IS LOST: {fall['why']}",
        f"Finish the scene the party is in, then play out {play} and call `end_story` with it. Do not soften the result, "
        "choose a kinder ending or let the party undo it. No quest can be finished now.",
    ]
    if not ending:
        lines += [f"- {e.id}: {e.title}. {e.when}" for e in story.endings]
    lines.append(f"If you do not end it within {left} turns, the server will.")
    return "\n".join(lines)


STAKES_LINES = {
    1: "Stakes are low. A failure costs something small (time, coin, supplies) and never blocks the story; if a loss "
    "would, bend the narrative around it. The party cannot lose the game in this chapter.",
    2: "Stakes are real. A failed quest costs something real and the story finds another way; the whole game is lost "
    "only through neglect or an extremely foolish act, never through an honest attempt that goes badly.",
    3: "Stakes are final. Failure now ends the story, and there are many ways to fail. A party that notices them and "
    "chooses well wins; one that does not, loses.",
}
HINT_RULE = (
    "Hint at danger through the world (an omen, a changed guard, a frightened ally, a burned bridge). Never state the "
    "stakes, never say what would end the game or that something would be a failure."
)


def _deadline_lines(story: Story, world: World) -> list[str]:
    """What the GM must do about the clock this turn (docs/STAKES.md 8). A hard deadline is one whose passing ends the
    game; the player must be reminded of it in every scene, through its cue."""
    out = []
    rows = [(m.title, m.deadline, False) for m in active(story) if m.deadline is not None]
    rows += [(d.when, d.deadline, True) for d in story.dooms if story.chapter in d.chapters and d.deadline is not None]
    for title, dl, is_doom in rows:
        if dl.at <= world.time:
            continue
        used = dl.used(world.time)
        pct = f" About {round(used * 100)}% of the time is gone." if used is not None else ""
        cue = dl.cue or "the sign you invent for it"
        if is_doom or story.chapter == 3:
            if used is None or used < 0.34:
                how = "a passing detail"
            elif used < 0.67:
                how = "a remark from a companion"
            elif used < 0.9:
                how = "an urgent line"
            else:
                how = "a plain statement of how little time is left"
            out.append(
                f"Hard deadline ({title}): the player must never lose track of it. Work its cue into this turn's "
                f"narration: {cue}.{pct} Use {how}. Never say what happens when time runs out."
            )
        elif used is not None and used >= 0.5:
            how = "say it plainly" if used >= 0.75 else "give one hint"
            out.append(f"Time limit on {title} (cue: {cue}).{pct} When it fits, {how}.")
    return out


def briefing_block(story: Story, world: World, turn: int, nudge_turns: int = NUDGE_TURNS) -> str:
    """The private story section of the world notes (docs/STORY.md 10), or "" before the plan is written."""
    if not story.planned or story.goal is None:
        return ""
    goal = story.goal
    if story.concluded:
        title = next((e.title for e in story.endings if e.id == story.ending), story.ending or "")
        return (
            "## Story (private)\n"
            f"The story has ended ({title}). The game goes on as an endless one if the player wants: no more "
            "chapters, quests or limits on what you add to the world."
        )
    n = story.chapter
    info = story.chapters[n - 1] if n <= len(story.chapters) else Chapter("", "")
    lines = ["## Story (private)", f'Chapter {n} of 3, "{info.title}": {info.purpose}'.rstrip(": ")]
    if story.fall is not None:
        return "\n".join(lines + [_fall_block(story, turn)])
    if story.length != ENDLESS and n in STAKES_LINES:
        lines.append(f"{STAKES_LINES[n]} {HINT_RULE}")
    group = story.in_chapter(n)
    if n == 1 and not goal.revealed:
        lines.append(
            f"The final goal, which the player does NOT know yet: {goal.title}. {goal.summary} Foreshadow it and let "
            "clues come out through the quests; a player who works it out or asks the right person may learn it. "
            "Chapter 1 cannot end until the party learns it: when they do, report goal_revealed."
        )
    else:
        lines.append(f"The goal, which the player knows: {goal.title}. {goal.summary}")
    if goal.min_strength:
        lines.append(f"What the party needs before it can win: {goal.min_strength}")
    if n >= 2:
        lines.append("No new regions, settlements, factions or concepts now: add detail to what already exists.")
    level = info.target_level
    if level:
        lines.append(
            f"The party's average level is {story.party_level:.1f}; this chapter ends only once it reaches {level}."
        )
    shown = active(story)[:MAX_ACTIVE_SHOWN]
    if shown:
        lines.append("Active quests:")
        for m in shown:
            where = _names(world, m.entities)
            tail = f"; {m.scale}" + (f"; at/with {where}" if where else "")
            gives = f" Finishing it builds: {m.gives}." if m.gives else ""
            lines.append(f"- [{m.id}] {m.title} ({tail[2:]}): {m.brief}{gives}{_item_note(world, m)}")
            if m.fails_if:
                lines.append("  It is lost if: " + "; ".join(f.rstrip(". ") for f in m.fails_if) + ". Report it failed when one happens.")
    elif not group:
        lines.append("The quests for this chapter are not planned yet: keep the story moving with ordinary play.")
    waiting = [
        m for m in group
        if m.status == "pending" and m.needs and not items_in_hand(world, m.needs)
        and all((r := story.milestone(q)) is not None and r.status in SETTLED for q in m.requires)
    ][:MAX_ACTIVE_SHOWN]  # fmt: skip
    for m in waiting:
        wanted = _names(world, [i for i in m.needs if not items_in_hand(world, [i])])
        lines.append(
            f"- [{m.id}] {m.title} is not offered until the party has {wanted}. Let them come by it through play, "
            "and say nothing of why; when they do it opens."
        )
    if n == 3 and story.endings:
        lines.append("Possible endings (steer toward the one the party's choices earn; do not announce it):")
        lines += [f"- {e.id}: {e.title}. {e.when}" for e in story.endings]
    if story.choices and n >= 2:
        lines.append("Choices that matter for the ending: " + " ".join(c["note"] for c in story.choices[-CHOICES_SHOWN:]))
    if story.escape is not None:
        lines.append(
            f"The party is held: {story.escape['held']} The quest that gets them out is being written. Until it "
            "appears, narrate the captivity and let the party act and look for a way; do not free them yourself."
        )
    broken = needs_repair(story)
    if broken is not None:
        lines.append(
            f"[{broken.id}] {broken.title} has failed and a way round is being written. Until it appears, keep the "
            "story moving with ordinary play and the consequences of the failure; do not invent the new quest yourself."
        )
    if n == 1 and shown and any(m.entities for m in shown):
        lines.append(
            "Drift: if the party tries to leave the area before the quests are done, bend the narrative back (a storm "
            "closes the pass, a stranger's plea arrives, the road loops to the same fork). Never say they cannot go; "
            "the world just does not let them get far."
        )
    lines += _deadline_lines(story, world)
    dooms = [d for d in story.dooms if n in d.chapters]
    if dooms:
        lines.append(
            "Ways the whole game is lost (for you alone: hint at them as the party draws near, never read them out; "
            "when one comes to pass, finish the scene and call `end_story` with its ending):"
        )
        lines += [f"- {d.id}: {d.when}" + (f" (ending {d.ending})" if d.ending else "") for d in dooms]
    if story.costs:
        lines.append(
            "What failure has cost the party so far (keep it alive in the scenes that follow; the people involved "
            "react to it): " + " ".join(f"({c['kind']}) {c['text']}" for c in story.costs[-COSTS_SHOWN:])
        )
    required = [m for m in group if m.required]
    left = [m for m in required if m.status not in SETTLED]
    if n == 1 and not goal.revealed and required:
        if not left:
            lines.append("Only the goal's revelation is left: deliver it in the next scenes.")
        elif (len(required) - len(left)) / len(required) >= REVEAL_NUDGE_SHARE:
            lines.append("The party should be close to learning the goal: make the clues plainer.")
    if level_short(story, turn) and required and not left and (n != 1 or goal.revealed):
        lines.append(
            "The quests are done but the party is below the level this chapter needs: give them more to earn "
            "(encounters, discoveries, side trouble) and award XP so every character can advance."
        )
    level_of_pace = pace(story, turn, nudge_turns)
    idle = turn - story.last_progress_turn
    if level_of_pace == 1:
        lines.append(f"Pace: {idle} turns without progress. Offer a concrete hook toward an active quest in this scene.")
    elif level_of_pace == 2:
        lines.append(f"Pace: {idle} turns without progress. Bring a concrete consequence or opportunity to the player now.")
    return "\n".join(lines)
