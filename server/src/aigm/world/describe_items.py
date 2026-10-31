"""The item describer's sweep: write a Look for every key item the party has had in hand (docs/KEY_ITEMS.md 7).

The model-facing work is `Curator.item_look`. The rules that must hold whichever curator is used are here: which items
are describable (only those the party has acquired: one it merely knows of has no Look), in what order they are
described, what the model is shown (the known facts and how the item was found, never a hidden fact or the bookkeeping
sentence), batching, the content rules, no near-duplicates and one retry. Nothing in this module raises for a model
failure: an item without a Look is simply tried again by a later sweep. It follows `describe_places.py`."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from aigm.compendium import known_facts
from aigm.looks import ITEM, Look, frame_of, problems
from aigm.world.curator import Curator, CuratorError, ItemLookRequest, ItemSubject
from aigm.world.describe import SIMILAR_SUMMARY, about
from aigm.world.model import Entity, World
from aigm.world.ops import Op, SetLook
from aigm.world.text import tokens

log = logging.getLogger(__name__)

BATCH = 6  # items per curator call, so the items of a call are varied
MAX_PER_SWEEP = 12
MAX_CONCURRENT = 4  # batches in flight at once
FACTS_PER_ITEM = 12
MENTIONS_PER_ITEM = 3  # known facts about something else that mention the item


@dataclass
class ItemLooksResult:
    ops: list[Op] = field(default_factory=list)  # SetLook, to apply to the live world
    notes: list[str] = field(default_factory=list)  # what was skipped and why, for the log


# ---- who needs a Look --------------------------------------------------------------------


def describable(ent: Entity) -> bool:
    """Has the party had this item in hand? One it only knows of (or has not heard of) is never described."""
    return ent.kind == "item" and ent.holding is not None and ent.holding.acquired


def _acquired_turn(ent: Entity) -> int:
    return max((h.turn for h in ent.holding.history if h.status == "held"), default=0) if ent.holding else 0


def needing_items(world: World, recent_text: str = "") -> list[str]:
    """The acquired items with no Look, in the order they should be described: the ones the last narration named,
    then the rest, the most recently acquired first."""
    recent = {e.id for e in world.mentioned(recent_text)} if recent_text else set()
    items = [e for e in world.entities.values() if e.look is None and describable(e)]
    items.sort(key=lambda e: (e.id not in recent, -_acquired_turn(e), -int(e.id[1:])))
    return [e.name for e in items]


def too_alike(a: Look, b: Look) -> bool:
    """Would a painter paint the same object twice? The same form, material and markings, or summaries that share most
    of their words."""
    keys = ("form", "material", "markings")
    if all(str(a.tags.get(k, "")).lower() == str(b.tags.get(k, "")).lower() and a.tags.get(k) for k in keys):
        return True
    ta, tb = tokens(a.summary), tokens(b.summary)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= SIMILAR_SUMMARY


# ---- what the model is shown -------------------------------------------------------------


def _subject(world: World, name: str, recent_text: str) -> ItemSubject:
    """Everything the players know about the item, and nothing else: only `known` facts are read, so a secret in the
    world cannot reach the model however it was written, and the `custody` sentences ("The party has ...") are left out."""
    ent = world.find(name)
    assert ent is not None and ent.holding is not None
    known = [f for f in known_facts(world, ent.id) if f.aspect != "custody"]
    own = [f"[{f.aspect or 'general'}] {f.text}" for f in known if f.subject == ent.id][-FACTS_PER_ITEM:]
    mentions = [f"[mentioned] {f.text}" for f in known if f.subject != ent.id][-MENTIONS_PER_ITEM:]
    found = next((h.note for h in ent.holding.history if h.status == "held" and h.note), "")
    return ItemSubject(ent.name, list(ent.aliases), [*own, *mentions], found, about(recent_text, ent.name, ent.aliases))


# ---- the sweep ---------------------------------------------------------------------------


async def run_item_looks(
    world: World,
    campaign: dict[str, Any],
    ruleset: str,
    curator: Curator,
    *,
    recent_text: str = "",
    limit: int = MAX_PER_SWEEP,
) -> ItemLooksResult:
    """Write the missing Looks of acquired items, up to `limit`. Never raises for a model failure."""
    result = ItemLooksResult()
    write = getattr(curator, "item_look", None)
    todo = needing_items(world, recent_text)[:limit]
    if write is None or not todo:
        return result
    setting = str(campaign.get("setting", ""))
    existing = {f"{e.name}: {e.look.summary}": e.look for e in world.entities.values() if e.kind == "item" and e.look}
    batches = [todo[i : i + BATCH] for i in range(0, len(todo), BATCH)]
    gate = asyncio.Semaphore(MAX_CONCURRENT)

    async def one(names: list[str]) -> list[Look | None]:
        async with gate:
            subjects = [_subject(world, n, recent_text) for n in names]
            return await _describe_batch(write, subjects, setting, ruleset, dict(existing), result)

    done = await asyncio.gather(*(one(b) for b in batches))
    accepted: dict[str, Look] = {}
    for names, looks in zip(batches, done):
        for name, look in zip(names, looks):
            if look is None:
                continue
            clash = next((other for other, lk in accepted.items() if too_alike(look, lk)), None)
            if clash:  # from another batch of this sweep: left for the next one
                result.notes.append(f"no look for {name}: too like {clash}, tried again later")
                continue
            look.source, look.state = "generated", "provisional"
            look.tags["frame"] = frame_of(look)  # a missing or unknown shape is a square one
            accepted[name] = look
            result.ops.append(SetLook(name, look))
    return result


async def _describe_batch(
    write: Any,
    subjects: list[ItemSubject],
    setting: str,
    ruleset: str,
    existing: dict[str, Look],
    result: ItemLooksResult,
    split: bool = True,
) -> list[Look | None]:
    """One batch, with one retry for the items whose answers were rejected, and one split in two if the model cannot
    answer for all of them at once (`split` is False for the halves, which are not split again)."""
    accepted: list[Look | None] = [None] * len(subjects)
    feedback: dict[int, list[str]] = {}
    for attempt in range(2):
        wanted = [i for i, look in enumerate(accepted) if look is None]
        if not wanted:
            break
        request = ItemLookRequest(subjects, setting, ruleset, list(existing), feedback)
        if attempt:  # the retry asks only for what failed
            request.subjects = [subjects[i] for i in wanted]
            request.feedback = {k: feedback[i] for k, i in enumerate(wanted)}
        try:
            answers = await write(request)
        except CuratorError as exc:
            if split and len(request.subjects) > 1:  # too much for one answer: two smaller ones
                return await _split(write, subjects, setting, ruleset, existing, result, accepted, wanted, exc)
            result.notes.append(f"item looks skipped ({exc})")
            return accepted
        except Exception as exc:  # a model failure never fails a turn
            log.exception("describing items failed")
            result.notes.append(f"item looks skipped ({type(exc).__name__}: {exc})")
            return accepted
        earlier, feedback = feedback, {}
        mapping = wanted if attempt else list(range(len(subjects)))
        for k, i in enumerate(mapping):
            look = answers.get(k)
            sub = subjects[i]
            found = ["no answer was given"] if look is None else problems(look, sub.name, ITEM)
            if look is not None:
                found += [
                    f"too like {label.split(':')[0]}: make this item clearly different"
                    for label, other in existing.items()
                    if too_alike(look, other)
                ][:1]
                found += [
                    f"too like {subjects[j].name}: make this item clearly different"
                    for j, other in enumerate(accepted)
                    if other is not None and j != i and too_alike(look, other)
                ][:1]
            if found == ["no answer was given"] and i in earlier:
                found = earlier[i]  # keep the real reasons from the first attempt
            if found:
                feedback[i] = found
            else:
                accepted[i] = look
    for i, found in feedback.items():
        result.notes.append(f"no look for {subjects[i].name}: " + "; ".join(found))
    return accepted


async def _split(
    write: Any,
    subjects: list[ItemSubject],
    setting: str,
    ruleset: str,
    existing: dict[str, Look],
    result: ItemLooksResult,
    accepted: list[Look | None],
    wanted: list[int],
    why: Exception,
) -> list[Look | None]:
    """The model could not answer for the whole batch: ask for each half separately, once. A half that fails again is
    skipped and left for a later sweep."""
    result.notes.append(f"a batch of {len(wanted)} items failed ({why}); trying two smaller ones")
    middle = len(wanted) // 2
    for part in (wanted[:middle], wanted[middle:]):
        got = await _describe_batch(write, [subjects[i] for i in part], setting, ruleset, existing, result, split=False)
        for i, look in zip(part, got):
            accepted[i] = look
    return accepted
