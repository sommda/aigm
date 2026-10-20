"""Writing a story plan (docs/STORY.md 5): ask the plotter, hold its answer to the rules, and return ops and a story.

Like the other passes this works on a snapshot of the world and changes nothing itself. The world additions it makes
(the goal and the cast around it, all hidden) come back as ops; the plan comes back as a `Story`."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from aigm.story import CHAPTERS, LENGTHS, Chapter, Ending, Goal, Milestone, Story, settle_ready, validate_plan
from aigm.world import World
from aigm.world.curator import CuratorError, Curator, Extraction, PlotProposal, PlotRequest
from aigm.world.independence import independence_problem
from aigm.world.ops import Op, apply_ops
from aigm.world.passes import PassConfig, _plan_expansion

log = logging.getLogger(__name__)

PLOT_CONFIG = PassConfig(max_facts_per_call=40, max_entities_per_call=10)
ATTEMPTS = 2  # the plotter gets one chance to fix a plan that breaks the rules


@dataclass
class PlotResult:
    ops: list[Op] = field(default_factory=list)  # world additions, to apply to the live world
    story: Story | None = None
    notes: list[str] = field(default_factory=list)


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
    facts = []
    for fact in proposal.facts:
        why = independence_problem(fact.text, party_names) if isinstance(fact.text, str) else "no text"
        if why:
            result.notes.append(f"dropped plot fact ({why}): {fact.text!r}")
        else:
            facts.append(fact)
    additions = Extraction(entities=list(proposal.entities), facts=facts)
    ops = _plan_expansion(snap, additions, turn, config, config.max_new_entities, config.max_new_facts, result)
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

    keys: dict[str, str] = {}
    problems: list[str] = []
    quests = [q for q in proposal.quests if q.chapter in chapters]
    for n, quest in enumerate(quests, 1):
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
            )
        )
    if any(not m.title or not m.brief for m in milestones):
        problems.append("every quest needs a title and a brief")
    if any(m.scale not in ("small", "medium", "large") for m in milestones):
        problems.append("quest scale must be small, medium or large")
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
        endings=[Ending(f"end{i}", e.title.strip(), e.when.strip()) for i, e in enumerate(proposal.endings, 1)],
        chapter_started_turn=max(turn, 1),
        last_progress_turn=max(turn, 1),
    )  # fmt: skip
    missing_chapters = [c for c in chapters if not story.in_chapter(c)]
    if missing_chapters:
        problems.append(f"write quests for chapter {missing_chapters[0]}")
    problems += validate_plan(story, snap)
    settle_ready(story)
    return story, problems
