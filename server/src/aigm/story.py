"""The story plan of a structured campaign, and the rules that move it along (docs/STORY.md).

Everything here is pure: no clock, no network, no model. The plan is data (`Story`); the functions read it and return
what should happen next. The tools, the briefing and the curator built on top of it come later."""

from dataclasses import dataclass, field
from typing import Any

from aigm.errors import CorruptSave
from aigm.world import World

ENDLESS = "endless"
SCALES = ("small", "medium", "large")
STATUSES = ("pending", "active", "done", "skipped", "failed")
SETTLED = frozenset({"done", "skipped"})  # a milestone in either state no longer blocks anything
CHAPTERS = (1, 2, 3)
CONCLUDED = 4  # the chapter number once an ending has been reached
MIN_ENDINGS, MAX_ENDINGS = 2, 4
MAX_CHOICES = 40  # the choices log keeps this many recent entries
PLAN_SLACK = 1  # how far a chapter's quest count may stray from the length's range before the plan is refused

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


# ---- the plan -----------------------------------------------------------------------------


@dataclass
class Chapter:
    title: str
    purpose: str  # one line for the GM
    target_level: int | None = None  # the party level to aim for by the end of the chapter (docs/STORY.md 7)

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "purpose": self.purpose, "target_level": self.target_level}


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "chapter": self.chapter, "title": self.title, "brief": self.brief, "scale": self.scale,
            "gives": self.gives, "requires": list(self.requires), "required": self.required,
            "entities": list(self.entities), "status": self.status, "done_turn": self.done_turn,
            "outcome": self.outcome,
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

    @property
    def planned(self) -> bool:
        return self.goal is not None

    @property
    def concluded(self) -> bool:
        return self.chapter == CONCLUDED

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
    return Milestone(
        id=_text(raw, "id"), chapter=chapter, title=_text(raw, "title"), brief=_text(raw, "brief"), scale=scale,
        gives=_text(raw, "gives", optional=True), requires=_strings(raw, "requires"), required=required,
        entities=_strings(raw, "entities"), status=status, done_turn=_opt_int(raw, "done_turn"), outcome=outcome,
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
    if world is not None:
        named = [(story.goal.title if story.goal else "the goal", story.goal.entities if story.goal else [])]
        named += [(m.id, m.entities) for m in story.milestones]
        for label, ids in named:
            for entity_id in ids:
                if world.entity(entity_id) is None:
                    problems.append(f"{label} names {entity_id}, which is not in the world")
    return problems


def _graph_problems(story: Story) -> list[str]:
    """Cycles, quests that wait on a later chapter, and required quests that nothing can ever open."""
    problems: list[str] = []
    by_id = {m.id: m for m in story.milestones}
    for m in story.milestones:
        for r in m.requires:
            if by_id[r].chapter > m.chapter:
                problems.append(f"{m.id} (chapter {m.chapter}) requires {r}, which is in chapter {by_id[r].chapter}")
    # A milestone can be reached when everything it requires can be reached: peel off the ones with no open needs.
    reached: set[str] = set()
    progress = True
    while progress:
        progress = False
        for m in story.milestones:
            if m.id not in reached and all(r in reached for r in m.requires):
                reached.add(m.id)
                progress = True
    for m in story.milestones:
        if m.id not in reached:
            problems.append(f"{m.id} can never become available (a cycle, or it waits on one)")
    return problems


# ---- moving through the story -------------------------------------------------------------


def settle_ready(story: Story) -> list[str]:
    """Make the milestones of the current chapter whose requirements are settled active. Returns the ids opened."""
    opened = []
    for m in story.in_chapter(story.chapter):
        if m.status == "pending" and all(
            (r := story.milestone(req)) is not None and r.status in SETTLED for req in m.requires
        ):
            m.status = "active"
            opened.append(m.id)
    return opened


def active(story: Story) -> list[Milestone]:
    return [m for m in story.in_chapter(story.chapter) if m.status == "active"]


def chapter_complete(story: Story) -> bool:
    """Every required quest of the chapter is settled, and in chapter 1 the goal is known (docs/STORY.md 6.2)."""
    if story.concluded:
        return False
    group = story.in_chapter(story.chapter)
    if not group or any(m.required and m.status not in SETTLED for m in group):
        return False
    if story.chapter == 1 and not (story.goal and story.goal.revealed):
        return False
    return True


@dataclass
class Progress:
    ok: bool
    message: str
    opened: list[str] = field(default_factory=list)  # milestones that became active
    advanced_to: int | None = None  # the chapter the story moved into, if it did


def report(story: Story, milestone_id: str, status: str, outcome: str, turn: int) -> Progress:
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
    milestone.status, milestone.outcome, milestone.done_turn = status, outcome.strip(), turn
    story.last_progress_turn = turn
    if status == "done" and outcome.strip():
        story.choices = [*story.choices, {"turn": turn, "milestone": milestone_id, "note": outcome.strip()}][
            -MAX_CHOICES:
        ]
    opened = settle_ready(story)
    advanced = None
    if chapter_complete(story):
        advanced = advance_chapter(story, turn)
        opened += settle_ready(story)
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
    if kind == "npc":
        return True, ""
    if kind != "location":
        return False, f"a new {kind} is a major addition, and this chapter takes only details"
    parent_entity = world.resolve(parent) if parent else None
    if parent_entity is None or parent_entity.parent is None:
        return False, "a new region or settlement is a major addition; place it inside an existing place instead"
    return True, ""

