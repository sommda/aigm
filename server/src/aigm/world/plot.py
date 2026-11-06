"""Writing a story plan (docs/STORY.md 5): ask the plotter, hold its answer to the rules, and return ops and a story.

Like the other passes this works on a snapshot of the world and changes nothing itself. The world additions it makes
(the goal and the cast around it, all hidden) come back as ops; the plan comes back as a `Story`."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from aigm.story import (
    CHAPTERS,
    COST_KINDS,
    MAX_BACKUPS,
    addition_allowed,
    apply_repair,
    failure_response,
    repair_depth,
    LENGTHS,
    Chapter,
    Deadline,
    Doom,
    Ending,
    Goal,
    Milestone,
    Story,
    settle_ready,
    stakes_problems,
    summary_so_far,
    validate_plan,
)
from aigm.world import World, WorldTime
from aigm.world.model import WorldError
from aigm.world.curator import CuratorError, Curator, DeadlineProposal, Extraction, PlotProposal, PlotRequest
from aigm.world.independence import independence_problem
from aigm.world.ops import Op, apply_ops
from aigm.world.passes import PassConfig, _plan_expansion

log = logging.getLogger(__name__)

PLOT_CONFIG = PassConfig(
    max_facts_per_call=40, max_entities_per_call=16, max_new_entities=16, max_new_facts=40, allow_items=True
)
ATTEMPTS = 2  # the plotter gets one chance to fix a plan that breaks the rules


@dataclass
class PlotResult:
    ops: list[Op] = field(default_factory=list)  # world additions, to apply to the live world
    story: Story | None = None  # a new game's whole plan
    chapter: int | None = None  # a later chapter's plan: the chapter, and its quests
    milestones: list[Milestone] = field(default_factory=list)
    dooms: list[Doom] = field(default_factory=list)
    escape: bool = False  # the quest that gets a captured party out
    repair_of: str | None = None  # a repair: the id of the failed quest these milestones replace
    cost: tuple[str, str] | None = None  # a repair's own account of the cost: (kind, text)
    names: dict[str, str] = field(default_factory=dict)  # entity id (in the snapshot planned against) -> name
    notes: list[str] = field(default_factory=list)

    def rebind(self, world: World) -> None:
        """Point the quests at the entities of `world` (the live world may have numbered new ones differently since the
        plan was written against a snapshot)."""
        def moved(entity_id: str) -> str | None:
            ent = world.find(self.names.get(entity_id, ""))
            return ent.id if ent is not None else None

        for m in self.milestones:
            m.entities = [e.id for n in m.entities if (e := world.find(self.names.get(n, ""))) is not None]
            m.finds = moved(m.finds) if m.finds else None
            m.needs = [i for n in m.needs if (i := moved(n)) is not None]


def chapters_to_plan(length: str) -> tuple[int, ...]:
    """A short game is planned whole. Longer ones plan chapter 1 now and the rest when they reach it."""
    return CHAPTERS if length == "short" else (CHAPTERS[0],)


async def run_plot(
    world: World,
    campaign: dict[str, Any],
    length: str,
    curator: Curator,
    *,
    turn: int = 0,
    config: PassConfig | None = None,
    progress: Callable[[str], None] | None = None,
) -> PlotResult:
    """Plan the story of a new game. `world` is the bootstrapped world and is not modified. Raises `CuratorError`
    if the curator cannot plot or its plan still breaks the rules after one correction."""
    plot = getattr(curator, "plot", None)
    if plot is None:
        raise CuratorError("this curator cannot plan a story")
    if length not in LENGTHS:
        raise ValueError(f"unknown story length {length!r}")
    config = config or PLOT_CONFIG
    shape = LENGTHS[length]
    party = [(str(m.get("name", "")), str(m.get("sheet", ""))) for m in campaign.get("party", []) if isinstance(m, dict)]
    request = PlotRequest(
        length=length,
        setting=str(campaign.get("setting", "")),
        opening=str(campaign.get("opening", "")),
        level=int(campaign.get("level") or 1),
        party=party,
        gm_notes=str(campaign.get("gm_notes") or ""),
        entities=list(world.entities.values()),
        facts=list(world.facts.values()),
        chapters=chapters_to_plan(length),
        quests=shape.quests,
        scales=tuple(sorted(shape.scales)),
        now=str(world.time),
    )
    if progress:
        progress("Planning the story...")
    problems: list[str] = []
    for _ in range(ATTEMPTS):
        proposal = await plot(request)
        result = PlotResult()
        snap = world.copy()
        story, problems = _assemble(snap, proposal, length, request.chapters, [n for n, _ in party], turn, config, result)
        if story is not None and not problems:
            result.story = story
            return result
        request = replace(request, feedback=problems)
    raise CuratorError("the story plan broke the rules: " + "; ".join(problems[:5]))


def _add_to_world(
    snap: World, proposal: PlotProposal, party_names: list[str], turn: int, config: PassConfig, result: PlotResult
) -> Callable[[list[str]], list[str]]:
    """Apply the plotter's world additions to `snap` (hidden, connected, independent) and return a function that turns
    entity names into ids."""
    facts = []
    for fact in proposal.facts:
        why = independence_problem(fact.text, party_names) if isinstance(fact.text, str) else "no text"
        if why:
            result.notes.append(f"dropped plot fact ({why}): {fact.text!r}")
        else:
            facts.append(fact)
    additions = Extraction(entities=list(proposal.entities), facts=facts)
    ops = _plan_expansion(
        snap, additions, turn, config, config.max_new_entities, config.max_new_facts, result, source="plotter"
    )
    applied = apply_ops(snap, ops)
    result.ops += applied.ops
    result.notes += applied.skipped

    def resolve(names: list[str]) -> list[str]:
        ids = []
        for name in names:
            ent = snap.find(name) if isinstance(name, str) else None
            if ent is None:
                result.notes.append(f"the plan names {name!r}, which is not in the world")
            elif ent.id not in ids:
                ids.append(ent.id)
        return ids

    return resolve


def _ending_id(endings: list[Ending], ref: str) -> str | None:
    ref = " ".join(ref.lower().split())
    return next((e.id for e in endings if ref in (e.id.lower(), " ".join(e.title.lower().split()))), None)


def _deadline(raw: DeadlineProposal | None, label: str, problems: list[str]) -> Deadline | None:
    if raw is None:
        return None
    try:
        return Deadline(WorldTime(raw.day, raw.hour), raw.cue.strip(), raw.fixed)
    except WorldError as exc:
        problems.append(f"{label}: the deadline is not a real time ({exc})")
        return None


def _doom_list(proposal: PlotProposal, endings: list[Ending], first: int) -> tuple[list[Doom], list[str]]:
    dooms, problems = [], []
    for n, raw in enumerate(proposal.dooms, first):
        label = f"doom {n}"
        chapters = sorted({c for c in raw.chapters if c in (2, 3)})
        if not raw.when.strip() or not chapters:
            problems.append(f"{label}: give `when` and `chapters` (2, 3 or both; a doom is never in chapter 1)")
            continue
        ending = _ending_id(endings, raw.ending) if raw.ending.strip() else None
        if raw.ending.strip() and ending is None:
            problems.append(f"{label}: the ending {raw.ending!r} is not one of the endings (use its title)")
        dooms.append(Doom(f"d{n}", raw.when.strip(), chapters, _deadline(raw.deadline, label, problems), ending))
    return dooms, problems


def _quests(
    proposal: PlotProposal,
    chapters: tuple[int, ...],
    resolve: Callable[[list[str]], list[str]],
    first: int,
    endings: list[Ending],
) -> tuple[list[Milestone], list[str]]:
    """The proposal's quests for `chapters` as milestones numbered from `first`, and what is wrong with them."""
    keys: dict[str, str] = {}
    problems: list[str] = []
    quests = [q for q in proposal.quests if q.chapter in chapters]
    for n, quest in enumerate(quests, first):
        if not quest.key.strip() or quest.key in keys:
            problems.append(f"quest keys must be unique and non-empty (saw {quest.key!r})")
        keys[quest.key] = f"m{n:02d}"
    milestones = []
    for quest in quests:
        missing = [r for r in quest.requires if r not in keys]
        if missing:
            problems.append(f"quest {quest.key!r} requires {missing[0]!r}, which is not one of the quests")
        milestones.append(
            Milestone(
                id=keys[quest.key],
                chapter=quest.chapter,
                title=quest.title.strip(),
                brief=quest.brief.strip(),
                scale=quest.scale,
                gives=quest.gives.strip(),
                requires=[keys[r] for r in quest.requires if r in keys],
                required=quest.required,
                entities=resolve(quest.entities),
                finds=(resolve([quest.finds]) or [None])[0] if quest.finds.strip() else None,
                needs=resolve(quest.needs),
                fails_if=[" ".join(f.split()) for f in quest.fails_if if f.strip()],
                deadline=_deadline(quest.deadline, f"quest {quest.key!r}", problems),
                ending=_ending_id(endings, quest.ending) if quest.ending.strip() else None,
            )
        )
        if quest.ending.strip() and milestones[-1].ending is None:
            problems.append(f"quest {quest.key!r}: the ending {quest.ending!r} is not one of the endings (use its title)")
        for label, names in (("finds", [quest.finds] if quest.finds.strip() else []), ("needs", quest.needs)):
            for name in dict.fromkeys(names):
                if not resolve([name]):
                    problems.append(
                        f"quest {quest.key!r} {label} {name!r}, which is not a key item you created: add it to `entities` "
                        "(kind item) with `appearance` and `whereabouts` facts, the whereabouts fact also naming a place or "
                        "person that exists, and use exactly the same name here"
                    )
    if any(not m.title or not m.brief for m in milestones):
        problems.append("every quest needs a title and a brief")
    if any(m.scale not in ("small", "medium", "large") for m in milestones):
        problems.append("quest scale must be small, medium or large")
    return milestones, problems


def _assemble(
    snap: World,
    proposal: PlotProposal,
    length: str,
    chapters: tuple[int, ...],
    party_names: list[str],
    turn: int,
    config: PassConfig,
    result: PlotResult,
) -> tuple[Story | None, list[str]]:
    """Apply the world additions to `snap` and build the story. Returns the story and what is wrong with the plan."""
    if not proposal.goal_title.strip() or not proposal.goal_summary.strip():
        return None, ["the plan has no goal: give goal_title and goal_summary"]
    resolve = _add_to_world(snap, proposal, party_names, turn, config, result)
    endings = [Ending(f"end{i}", e.title.strip(), e.when.strip()) for i, e in enumerate(proposal.endings, 1)]
    milestones, problems = _quests(proposal, chapters, resolve, 1, endings)
    dooms, doom_problems = _doom_list(proposal, endings, 1)
    problems += doom_problems
    if len(proposal.chapters) != len(CHAPTERS) or any(not c.title.strip() for c in proposal.chapters):
        problems.append("give a title and purpose for each of the three chapters")
    if problems:
        return None, problems

    story = Story(
        length=length,
        goal=Goal(
            proposal.goal_title.strip(), proposal.goal_summary.strip(), resolve(proposal.goal_entities), False,
            proposal.min_strength.strip(),
        ),
        chapters=[Chapter(c.title.strip(), c.purpose.strip(), c.target_level) for c in proposal.chapters],
        milestones=milestones,
        endings=endings,
        dooms=dooms,
        chapter_started_turn=max(turn, 1),
        last_progress_turn=max(turn, 1),
    )  # fmt: skip
    missing_chapters = [c for c in chapters if not story.in_chapter(c)]
    if missing_chapters:
        problems.append(f"write quests for chapter {missing_chapters[0]}")
    problems += validate_plan(story, snap)
    problems += stakes_problems(story, chapters, snap.time)
    settle_ready(story, snap)
    return story, problems


async def run_chapter_plot(
    world: World,
    campaign: dict[str, Any],
    story: Story,
    chapter: int,
    curator: Curator,
    *,
    turn: int = 0,
    config: PassConfig | None = None,
) -> PlotResult:
    """Write the quests of a later chapter against the world as it has grown (docs/STORY.md 5). `world` and `story`
    are not modified; the result holds the quests and any world additions, to apply when the session is idle."""
    plot = getattr(curator, "plot", None)
    if plot is None:
        raise CuratorError("this curator cannot plan a story")
    config = config or PLOT_CONFIG
    shape = LENGTHS[story.length]
    party = [(str(m.get("name", "")), str(m.get("sheet", ""))) for m in campaign.get("party", []) if isinstance(m, dict)]
    request = PlotRequest(
        length=story.length,
        setting=str(campaign.get("setting", "")),
        opening=str(campaign.get("opening", "")),
        level=int(campaign.get("level") or 1),
        party=party,
        gm_notes=str(campaign.get("gm_notes") or ""),
        entities=list(world.entities.values()),
        facts=list(world.facts.values()),
        chapters=(chapter,),
        quests=shape.quests,
        scales=tuple(sorted(shape.scales)),
        now=str(world.time),
        story_so_far=summary_so_far(story),
    )
    first = len(story.milestones) + 1
    problems: list[str] = []
    for _ in range(ATTEMPTS):
        proposal = await plot(request)
        result = PlotResult(chapter=chapter)
        snap = world.copy()
        resolve = _add_to_world(snap, proposal, [n for n, _ in party], turn, config, result)
        milestones, problems = _quests(proposal, (chapter,), resolve, first, story.endings)
        dooms, doom_problems = _doom_list(proposal, story.endings, len(story.dooms) + 1)
        problems += doom_problems
        if not problems:
            merged = story.copy()
            merged.milestones += milestones
            merged.dooms += dooms
            problems = validate_plan(merged, snap) + stakes_problems(merged, (chapter,), snap.time)
        if not problems:
            result.milestones = milestones
            result.dooms = dooms
            result.names = {e.id: e.name for e in snap.entities.values()}
            return result
        request = replace(request, feedback=problems)
    raise CuratorError(f"the plan for chapter {chapter} broke the rules: " + "; ".join(problems[:5]))


def repair_brief(story: Story, failed: Milestone) -> str:
    """What the plotter is told about a failed quest and what its repair must do (docs/STAKES.md 4, 5)."""
    response = failure_response(story, failed.chapter)
    depth = repair_depth(story, failed)
    lines = [
        f'Quest {failed.id} "{failed.title}" (chapter {failed.chapter}) has failed. Its brief was: {failed.brief}',
        f"What happened: {failed.outcome or 'it can no longer be done'}",
    ]
    spent = [c["text"] for c in story.costs if c.get("milestone") == failed.id]
    lines.append("What it cost: " + (" ".join(spent) if spent else "(not recorded: name the cost in `cost` and `cost_kind`)"))
    lines.append(
        f"Write {1 if depth == 1 else 'one or two'} new required quest(s) of chapter {failed.chapter} that restore a way "
        "to the end of the chapter, and nothing else: no other quests, no new chapter titles (repeat the existing ones). "
        "They take the failed quest's place; the quests that waited on it will wait on them."
    )
    if response.backup_quest:
        lines.append(
            "This is a hard road, not a free one. The backup is a different way to the same end (a copy of the burned "
            "ledger, a mage who can restore it, another source for the same facts), found inside the world as it is: "
            "add no region, settlement, faction or idea, only details (a person, a room, an item). It must name a real "
            f"cost in `cost` (one sentence) of one of these kinds in `cost_kind`: {', '.join(COST_KINDS)}."
        )
    else:
        lines.append(
            "The cost is small and never blocks the story. You may add new places, people or factions to the world if "
            "that is what the way round needs."
        )
    if depth > 1:
        lines.append(
            f"This line of the story has now failed {depth} times. Each failure costs more: make the new way harder "
            "and its price higher than the last."
        )
    return "\n".join(lines)


async def run_repair_plot(
    world: World,
    campaign: dict[str, Any],
    story: Story,
    failed: Milestone,
    curator: Curator,
    *,
    turn: int = 0,
    config: PassConfig | None = None,
) -> PlotResult:
    """Mend the plan around a failed required quest (docs/STORY.md 8.2). `world` and `story` are not modified; the result
    holds the backup quests and any world additions, to apply when the session is idle."""
    plot = getattr(curator, "plot", None)
    if plot is None:
        raise CuratorError("this curator cannot plan a story")
    config = config or PLOT_CONFIG
    shape = LENGTHS[story.length]
    party = [(str(m.get("name", "")), str(m.get("sheet", ""))) for m in campaign.get("party", []) if isinstance(m, dict)]
    request = PlotRequest(
        length=story.length,
        setting=str(campaign.get("setting", "")),
        opening=str(campaign.get("opening", "")),
        level=int(campaign.get("level") or 1),
        party=party,
        gm_notes=str(campaign.get("gm_notes") or ""),
        entities=list(world.entities.values()),
        facts=list(world.facts.values()),
        chapters=(failed.chapter,),
        quests=shape.quests,
        scales=tuple(sorted(shape.scales)),
        story_so_far=summary_so_far(story),
        now=str(world.time),
        repair=repair_brief(story, failed),
    )
    first = len(story.milestones) + 1
    problems: list[str] = []
    for _ in range(ATTEMPTS):
        proposal = await plot(request)
        result = PlotResult(chapter=failed.chapter, repair_of=failed.id)
        snap = world.copy()
        problems = _repair_additions(story, snap, proposal, failed)
        if not problems:
            resolve = _add_to_world(snap, proposal, [n for n, _ in party], turn, config, result)
            milestones, problems = _quests(proposal, (failed.chapter,), resolve, first, story.endings)
            required = [m for m in milestones if m.required]
            if not problems and not 1 <= len(required) <= MAX_BACKUPS:
                problems = [f"write one or two required quests that replace {failed.id}, not {len(required)}"]
            if not problems:
                merged = story.copy()
                apply_repair(merged, failed.id, [replace(m) for m in milestones])
                problems = validate_plan(merged, snap)
        if not problems:
            result.milestones = milestones
            result.names = {e.id: e.name for e in snap.entities.values()}
            if proposal.cost.strip() and proposal.cost_kind in COST_KINDS:
                result.cost = (proposal.cost_kind, proposal.cost.strip())
            return result
        request = replace(request, feedback=problems)
    raise CuratorError(f"the repair of {failed.id} broke the rules: " + "; ".join(problems[:5]))


def _entity_problems(story: Story, snap: World, proposal: PlotProposal, chapter: int) -> list[str]:
    """After chapter 1 a plotter may add only details to the world (docs/STORY.md 6.4)."""
    problems = []
    probe = story.copy()
    probe.chapter = chapter
    names = {e.name for e in snap.entities.values()}
    for ent in proposal.entities:
        ok, why = addition_allowed(probe, snap, ent.kind, ent.parent)
        if not ok and ent.name not in names:
            problems.append(f"{ent.name!r}: {why}")
    return problems


def _repair_additions(story: Story, snap: World, proposal: PlotProposal, failed: Milestone) -> list[str]:
    """A repair adds only details after chapter 1; a chapter 2 repair also needs a cost to name when the failure has
    none recorded."""
    problems = _entity_problems(story, snap, proposal, failed.chapter)
    response = failure_response(story, failed.chapter)
    recorded = any(c.get("milestone") == failed.id for c in story.costs)
    if response.cost_required and not recorded and not (proposal.cost.strip() and proposal.cost_kind in response.cost_kinds):
        problems.append(f"name what the failure cost: `cost` and a `cost_kind` of {', '.join(response.cost_kinds)}")
    return problems


def escape_brief(story: Story, escape: dict[str, Any]) -> str:
    """What the plotter is told about a captured party and the quest that gets it out (docs/STAKES.md 7.5)."""
    response = failure_response(story)
    hours = escape.get("hours")
    lines = [
        f"The whole party was beaten and taken. This is already narrated to the player, and it is the truth: {escape['held']}",
        "Keep to it exactly: the same holders, the same place, the same things taken. Do not choose different captors "
        "or another prison. If the holders or the place are not in the world yet, say so through the quest's own "
        "details rather than changing them.",
        f"Write ONE small required quest of chapter {story.chapter} (the escape quest): its brief says where the party "
        "is held, who holds them and what they have lost, and it is done when they are free. Give it no `requires`.",
        "It is a real quest with more than one way out (a guard's mercy, a stolen key, a bribe, a riot, a daring break), "
        "built to be finished soon: small, and leaving the party poorer rather than stopped.",
    ]
    if hours is not None:
        lines.append(f"The party has about {hours} hours before something fixed in the world cannot wait. Fit the escape inside it.")
    if response.backup_quest:
        lines.append(
            "Use what the world already has: the holder is an existing faction or person, the prison an existing place "
            "or a detail inside one (a cellar, a cage), and the way out something the party has met. Add no region, "
            "settlement, faction or idea. Leave `cost` and `cost_kind` empty."
        )
    else:
        lines.append(
            "You may add a new place (the slavers' pens), a new person (a sympathetic guard) or a new faction if the "
            "escape needs it. Leave `cost` and `cost_kind` empty."
        )
    return "\n".join(lines)


async def run_escape_plot(
    world: World,
    campaign: dict[str, Any],
    story: Story,
    curator: Curator,
    *,
    turn: int = 0,
    config: PassConfig | None = None,
) -> PlotResult:
    """Write the escape quest of a captured party. Nothing given is modified; the result holds the quest and any world
    additions, to apply when the session is idle."""
    plot = getattr(curator, "plot", None)
    escape = story.escape
    if plot is None or escape is None:
        raise CuratorError("there is nothing to plan an escape with")
    config = config or PLOT_CONFIG
    shape = LENGTHS[story.length]
    party = [(str(m.get("name", "")), str(m.get("sheet", ""))) for m in campaign.get("party", []) if isinstance(m, dict)]
    request = PlotRequest(
        length=story.length, setting=str(campaign.get("setting", "")), opening=str(campaign.get("opening", "")),
        level=int(campaign.get("level") or 1), party=party, gm_notes=str(campaign.get("gm_notes") or ""),
        entities=list(world.entities.values()), facts=list(world.facts.values()), chapters=(story.chapter,),
        quests=shape.quests, scales=("small",), story_so_far=summary_so_far(story), now=str(world.time), repair=escape_brief(story, escape),
    )  # fmt: skip
    first = len(story.milestones) + 1
    problems: list[str] = []
    for _ in range(ATTEMPTS):
        proposal = await plot(request)
        result = PlotResult(chapter=story.chapter, escape=True)
        snap = world.copy()
        problems = _entity_problems(story, snap, proposal, story.chapter)
        if not problems:
            resolve = _add_to_world(snap, proposal, [n for n, _ in party], turn, config, result)
            milestones, problems = _quests(proposal, (story.chapter,), resolve, first, story.endings)
            if not problems and len([m for m in milestones if m.required]) != 1:
                problems = ["write exactly one required quest: the escape"]
            if not problems:
                merged = story.copy()
                for m in milestones:
                    m.escape, m.scale = True, "small"
                merged.milestones += [replace(m) for m in milestones]
                problems = [p for p in validate_plan(merged, snap) if "required quests" not in p]
        if not problems:
            result.milestones = milestones
            result.names = {e.id: e.name for e in snap.entities.values()}
            return result
        request = replace(request, feedback=problems)
    raise CuratorError("the escape quest broke the rules: " + "; ".join(problems[:5]))
