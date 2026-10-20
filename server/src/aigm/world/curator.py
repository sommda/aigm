"""What the curator is asked and what it answers.

The curator is the model-facing half of the world pipeline. `Curator` is the interface; the
server-side rules around it (precedence, caps, connectivity, the frontier) live in `passes.py`,
so a scripted curator and the real one are held to the same rules."""

from dataclasses import dataclass, field
from typing import Protocol

from aigm.world.model import Entity, Fact, WorldTime


@dataclass
class EntityProposal:
    name: str
    kind: str
    aliases: list[str] = field(default_factory=list)
    parent: str | None = None  # name


@dataclass
class FactProposal:
    text: str
    about: list[str]  # entity names; the first is the subject
    aspect: str | None = None
    disclosure: str = "hidden"
    evidence: str = ""  # a short quote, for debugging; never stored
    replaces: str | None = None  # expansion only: id of a hidden fact this one corrects


@dataclass
class Extraction:
    """What the narration established (extract) or what was invented to flesh something out (expand)."""

    entities: list[EntityProposal] = field(default_factory=list)
    facts: list[FactProposal] = field(default_factory=list)
    reveals: list[str] = field(default_factory=list)  # ids of hidden facts the narration just made known
    location: str | None = None  # where the party now is (name)
    present: list[str] | None = None  # who is with them (names); None: not mentioned
    elapsed_hours: int = 0  # in-world time the narration covered
    start_hour: int | None = None  # bootstrap only: the hour of day (0-23) the opening situation implies


class CuratorError(Exception):
    """The curator's answer was unusable. The pass fails harmlessly and is retried later."""


@dataclass
class BootstrapRequest:
    """The campaign record, from which the first entities and facts are written."""

    setting: str
    opening: str
    level: int
    party: list[tuple[str, str]]  # (name, character sheet)
    gm_notes: str  # private notes: they become hidden facts


@dataclass
class ExtractRequest:
    transcript: str  # the unprocessed conversation, as plain text
    setting: str
    time: WorldTime
    scene_location: str | None
    present: list[str]
    entity_names: list[str]  # canonical names already in the world
    hidden_facts: list[Fact] = field(default_factory=list)  # GM-only facts near the scene, so reveals can name them


@dataclass
class ReconcileItem:
    index: int
    proposal: FactProposal
    neighbors: list[Fact]  # existing facts about the same entities or with similar words


@dataclass
class EntityQuestion:
    """A proposed entity that matches no name but resembles existing ones: the same thing?"""

    proposal: EntityProposal
    candidates: list[Entity]


@dataclass
class ReconcileRequest:
    items: list[ReconcileItem]
    questions: list[EntityQuestion]


@dataclass
class Label:
    index: int
    label: str  # new | duplicate | refines | contradicts
    existing_id: str | None = None  # duplicate / contradicts: the existing fact
    with_proposal: int | None = None  # contradicts: an earlier proposal in this same pass


@dataclass
class ReconcileResult:
    labels: list[Label] = field(default_factory=list)
    same_as: dict[str, str] = field(default_factory=dict)  # proposed entity name -> existing entity id


@dataclass
class ExpandRequest:
    entity: Entity
    tier: str  # full | most | sketch (how deep to go)
    missing: list[str]  # aspects with no fact yet
    facts: list[Fact]  # what is already recorded about the entity
    parents: list[Entity]
    neighbor_facts: list[Fact]
    review: list[Fact]  # hidden facts that may no longer fit after a correction
    setting: str
    time: WorldTime
    known_names: list[str] = field(default_factory=list)  # every entity name in the world, so new ones are fresh
    feedback: list[str] = field(default_factory=list)  # why a first attempt was rejected, on the retry


@dataclass
class DigestTurn:
    number: int  # the turn's number in the whole adventure
    text: str  # the turn as plain text (see passes.transcript)


@dataclass
class DigestRequest:
    turns: list[DigestTurn]
    setting: str = ""


@dataclass
class QuestProposal:
    key: str  # the plotter's own label; the server numbers the milestones itself
    chapter: int
    title: str
    brief: str
    scale: str = "small"
    gives: str = ""
    requires: list[str] = field(default_factory=list)  # keys
    required: bool = True
    entities: list[str] = field(default_factory=list)  # names


@dataclass
class ChapterProposal:
    title: str
    purpose: str = ""
    target_level: int | None = None


@dataclass
class EndingProposal:
    title: str
    when: str


@dataclass
class PlotProposal:
    """A story plan (docs/STORY.md 5), plus the entities and hidden facts that put its goal into the world."""

    goal_title: str
    goal_summary: str
    min_strength: str = ""
    goal_entities: list[str] = field(default_factory=list)  # names
    chapters: list[ChapterProposal] = field(default_factory=list)
    quests: list[QuestProposal] = field(default_factory=list)
    endings: list[EndingProposal] = field(default_factory=list)
    entities: list[EntityProposal] = field(default_factory=list)
    facts: list[FactProposal] = field(default_factory=list)


@dataclass
class PlotRequest:
    length: str  # short | medium | long
    setting: str
    opening: str
    level: int
    party: list[tuple[str, str]]  # (name, sheet)
    gm_notes: str
    entities: list[Entity]  # the world so far
    facts: list[Fact]
    chapters: tuple[int, ...]  # the chapters whose quests are to be written now
    quests: tuple[int, int]  # required quests per chapter, lowest and highest
    scales: tuple[str, ...]  # quest sizes that fit this length
    feedback: list[str] = field(default_factory=list)  # why a first attempt was rejected, on the retry


class Curator(Protocol):
    async def extract(self, request: ExtractRequest) -> Extraction: ...

    async def reconcile(self, request: ReconcileRequest) -> ReconcileResult: ...

    async def expand(self, request: ExpandRequest) -> Extraction: ...

    async def bootstrap(self, request: BootstrapRequest) -> Extraction: ...

    # Optional: `async def digest(self, request: DigestRequest) -> list[str]` returns one short account per turn,
    # in order; an empty string means "no digest for this turn".

    # Optional: `async def plot(self, request: PlotRequest) -> PlotProposal` writes a story plan; only structured games
    # need it (docs/STORY.md 5).

    # Optional: `async def judge_independence(self, texts: list[str]) -> list[int]` returns the
    # indexes of generated facts that depend on the party or the player's actions.
