"""What the curator is asked and what it answers.

The curator is the model-facing half of the world pipeline. `Curator` is the interface; the
server-side rules around it (precedence, caps, connectivity, the frontier) live in `passes.py`,
so a scripted curator and the real one are held to the same rules."""

from dataclasses import dataclass, field
from typing import Protocol

from aigm.looks import Look

from aigm.world.model import Entity, Fact, Motive, WorldTime


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
    via: list[str] = field(default_factory=list)  # familiarity only: the party members who know it


@dataclass
class MotiveProposal:
    """A lasting motive for a person, written by expansion (docs/ROLEPLAY.md 7.3)."""

    owner: str  # the person's name
    text: str
    kind: str = "want"
    strength: str = "leaning"
    moved_by: list[str] = field(default_factory=list)
    resists: list[str] = field(default_factory=list)
    tells: list[str] = field(default_factory=list)


@dataclass
class MotiveReport:
    """What the narration showed happening to a motive that is already recorded (extraction)."""

    motive: str  # its id, from the request
    action: str  # shift | resolve | hint
    text: str | None = None  # shift: what it has become
    strength: str | None = None  # shift: leaning | driven
    outcome: str | None = None  # resolve: satisfied | frustrated


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
    quest_reports: list[tuple[str, str, str]] = field(default_factory=list)  # (quest id, status, outcome) seen in play
    goal_revealed: bool = False  # the narration told the player what the final goal is
    motives: list[MotiveProposal] = field(default_factory=list)  # expansion: lasting motives for people
    motive_reports: list[MotiveReport] = field(default_factory=list)  # extraction: changes to recorded motives


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
    characters: list[tuple[str, str]] = field(default_factory=list)  # key people already recorded: (name, role fact)


@dataclass
class FamiliarityRequest:
    """What the party's characters already know of the world (docs/OPENING.md 5)."""

    setting: str
    opening: str
    level: int
    party: list[tuple[str, str, str]]  # (name, sheet, background)
    entities: list[Entity]  # the world so far
    facts: list[Fact]
    gm_notes: str
    only: list[str] = field(default_factory=list)  # a retry: write for these characters alone
    feedback: list[str] = field(default_factory=list)  # why a first attempt was rejected


@dataclass
class SheetRequest:
    """One character's free-text sheet, to be written out as sections (docs/STATUS.md 3.2)."""

    ruleset: str  # the ruleset's name, e.g. "AD&D 1e"
    level: int
    name: str
    text: str


@dataclass
class LookSubject:
    """One character to describe (docs/LOOKS.md 5.2)."""

    name: str
    party: bool  # a player character (else an NPC)
    aliases: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)  # recorded facts about them, as "[disclosure] text"
    sheet: str = ""  # party members
    background: str = ""  # party members
    given: list[str] = field(default_factory=list)  # appearance already decided: it must be kept
    given_by: str = ""  # who decided it: "the player in Session 0", "the narration", "the GM's notes"
    narration: list[str] = field(default_factory=list)  # sentences of the story that name them (docs/LOOKS.md 4.3)


@dataclass
class LookRequest:
    """A batch of characters to describe. The answer is a Look for each, by the subject's index."""

    subjects: list[LookSubject]
    setting: str
    ruleset: str  # the ruleset's name, for mapping its species to an ancestry
    existing: list[str] = field(default_factory=list)  # "Name: summary" of the looks already in the game
    feedback: dict[int, list[str]] = field(default_factory=dict)  # a retry: subject index -> why it was rejected


@dataclass
class PlaceSubject:
    """One place to describe (docs/PLACES.md 5). Everything here is known to the player: nothing hidden is ever put in."""

    name: str
    aliases: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)  # known facts about the place, as "[aspect] text"
    context: list[str] = field(default_factory=list)  # the places that contain it, outermost first, with what is known
    narration: list[str] = field(default_factory=list)  # sentences of the story that name it


@dataclass
class PlaceLookRequest:
    """A batch of places to describe. The answer is a Look for each, by the subject's index."""

    subjects: list[PlaceSubject]
    setting: str
    ruleset: str  # the ruleset's name, for the feel of its era
    existing: list[str] = field(default_factory=list)  # "Name: summary" of the places already described
    feedback: dict[int, list[str]] = field(default_factory=dict)  # a retry: subject index -> why it was rejected


@dataclass
class ItemSubject:
    """One key item to describe (docs/KEY_ITEMS.md 7). The party has it, and everything here is known to the player."""

    name: str
    aliases: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)  # known facts about the item, as "[aspect] text"
    found: str = ""  # how the party came by it, if it was said ("Taken from the steward's desk.")
    narration: list[str] = field(default_factory=list)  # sentences of the story that name it


@dataclass
class ItemLookRequest:
    """A batch of key items to describe. The answer is a Look for each, by the subject's index."""

    subjects: list[ItemSubject]
    setting: str
    ruleset: str
    existing: list[str] = field(default_factory=list)  # "Name: summary" of the items already described
    feedback: dict[int, list[str]] = field(default_factory=dict)  # a retry: subject index -> why it was rejected


@dataclass
class ReviseSubject:
    """A character who already has a Look and whom the last narration described (docs/LOOKS.md 7)."""

    name: str
    party: bool
    current: Look
    narration: list[str]  # the sentences that name them and look like description
    fixed: bool  # the Look is fixed: only a lasting change may alter it


@dataclass
class ReviseRequest:
    subjects: list[ReviseSubject]
    setting: str = ""


@dataclass
class LookRevision:
    """The reviser's verdict on one character: same | adds | lasting | contradicts."""

    verdict: str
    look: Look | None = None  # adds and lasting: the whole Look with the change worked in
    note: str = ""  # contradicts: what the Look says and what the narration said instead


@dataclass
class ExtractRequest:
    transcript: str  # the unprocessed conversation, as plain text
    setting: str
    time: WorldTime
    scene_location: str | None
    present: list[str]
    entity_names: list[str]  # canonical names already in the world
    hidden_facts: list[Fact] = field(default_factory=list)  # GM-only facts near the scene, so reveals can name them
    quests: list[tuple[str, str, str]] = field(default_factory=list)  # story games: active (id, title, brief)
    goal: str = ""  # story games: the goal while the player may not know it yet, else ""
    feedback: list[str] = field(default_factory=list)  # why a first attempt was rejected, on the retry
    motives: list[tuple[str, Motive]] = field(default_factory=list)  # (owner name, motive) of people present, changeable


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
    motives: list[Motive] = field(default_factory=list)  # the entity's recorded motives (a person), not to be repeated


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
    finds: str = ""  # the name of the key item the quest is about finding (docs/KEY_ITEMS.md 6.1)
    needs: list[str] = field(default_factory=list)  # names of key items the party must have had before it is offered


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
    story_so_far: str = ""  # a later chapter is being planned: the plan and what happened (docs/STORY.md 5)


class Curator(Protocol):
    async def extract(self, request: ExtractRequest) -> Extraction: ...

    async def familiarity(self, request: FamiliarityRequest) -> Extraction: ...

    async def reconcile(self, request: ReconcileRequest) -> ReconcileResult: ...

    async def expand(self, request: ExpandRequest) -> Extraction: ...

    async def bootstrap(self, request: BootstrapRequest) -> Extraction: ...

    # Optional: `async def sheet(self, request: SheetRequest) -> Sheet` writes a character's sheet as sections.

    # Optional: `async def look(self, request: LookRequest) -> dict[int, Look]` describes characters
    # (docs/LOOKS.md 5); the keys are indexes into `request.subjects`, and a missing one means "no answer".

    # Optional: `async def place_look(self, request: PlaceLookRequest) -> dict[int, Look]` describes places
    # (docs/PLACES.md); the keys are indexes into `request.subjects`, and a missing one means "no answer".

    # Optional: `async def item_look(self, request: ItemLookRequest) -> dict[int, Look]` describes key items
    # (docs/KEY_ITEMS.md 7); the keys are indexes into `request.subjects`, and a missing one means "no answer".

    # Optional: `async def revise_looks(self, request: ReviseRequest) -> dict[int, LookRevision]` checks the narration
    # against existing Looks (docs/LOOKS.md 7); the keys are indexes into `request.subjects`.

    # Optional: `async def digest(self, request: DigestRequest) -> list[str]` returns one short account per turn,
    # in order; an empty string means "no digest for this turn".

    # Optional: `async def plot(self, request: PlotRequest) -> PlotProposal` writes a story plan; only structured games
    # need it (docs/STORY.md 5).

    # Optional: `async def judge_independence(self, texts: list[str]) -> list[int]` returns the
    # indexes of generated facts that depend on the party or the player's actions.
