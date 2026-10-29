"""The place describer's sweep: write a Look for every location the player knows well enough to picture
(docs/PLACES.md 5 and 6).

The model-facing work is `Curator.place_look`. The rules that must hold whichever curator is used are here: which
places are describable (known facts only, and only those of a visual aspect make a place so), in what order they are
described, what the model is shown (nothing the player has not been told), batching, the content rules, no
near-duplicates and one retry. Nothing in this module raises for a model failure: a place without a Look is simply
tried again by a later sweep."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from aigm.compendium import _visible, known_facts
from aigm.looks import PLACE, Look, problems
from aigm.world.curator import Curator, CuratorError, PlaceLookRequest, PlaceSubject
from aigm.world.describe import SIMILAR_SUMMARY, about
from aigm.world.model import Entity, World
from aigm.world.ops import Op, SetLook
from aigm.world.text import tokens

log = logging.getLogger(__name__)

# A known fact of one of these aspects, about the place itself, is what makes a place describable: it says something a
# painter can use. Rumor and hearsay (history, inhabitants, tensions...) do not, however many there are.
VISUAL_ASPECTS = ("overview", "items", "approach", "entry", "interior", "layout")
BATCH = 6  # places per curator call, so the places of a call are varied
MAX_PER_SWEEP = 12
MAX_CONCURRENT = 4  # batches in flight at once
FACTS_PER_PLACE = 12
MENTIONS_PER_PLACE = 3  # known facts about something else that mention the place
CONTEXT_FACTS = 2  # known facts shown for each place that contains it
CONTEXT_CHARS = 220


@dataclass
class PlaceLooksResult:
    ops: list[Op] = field(default_factory=list)  # SetLook, to apply to the live world
    notes: list[str] = field(default_factory=list)  # what was skipped and why, for the log


# ---- who needs a Look --------------------------------------------------------------------


def describable(world: World, ent: Entity) -> bool:
    """Does the player know enough about this place to picture it? At least one known fact of a visual aspect, about
    the place itself. Hidden and hinted facts never count (docs/PLACES.md 5.1)."""
    return (
        ent.kind == "location"
        and ent.discovered
        and any(f.subject == ent.id and f.aspect in VISUAL_ASPECTS for f in known_facts(world, ent.id))
    )


def needing_places(world: World, recent_text: str = "") -> list[str]:
    """The describable places with no Look, in the order they should be described: the party's current location, then
    the places the last narration named, then the rest, those made describable most recently first."""
    recent = {e.id for e in world.mentioned(recent_text)} if recent_text else set()
    here = world.scene.location

    def newest(e: Entity) -> int:
        return max(f.learned_seq for f in known_facts(world, e.id) if f.subject == e.id and f.aspect in VISUAL_ASPECTS)

    places = [e for e in world.entities.values() if e.kind == "location" and e.look is None and describable(world, e)]
    places.sort(key=lambda e: (e.id != here, e.id not in recent, -newest(e), -int(e.id[1:])))
    return [e.name for e in places]


def too_alike(a: Look, b: Look) -> bool:
    """Would a painter paint the same view twice? The same scale, setting and climate with the same architecture and
    terrain, or summaries that share most of their words."""
    keys = ("scale", "setting", "climate")
    if all(a.tags.get(k) == b.tags.get(k) for k in keys) and all(
        a.tags.get(k, "").lower() == b.tags.get(k, "").lower() and a.tags.get(k) for k in ("architecture", "terrain")
    ):
        return True
    ta, tb = tokens(a.summary), tokens(b.summary)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= SIMILAR_SUMMARY


# ---- what the model is shown -------------------------------------------------------------


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _subject(world: World, name: str, recent_text: str) -> PlaceSubject:
    """Everything the player knows about the place, and nothing else: only `known` facts are read, so a secret in the
    world cannot reach the model however it was written."""
    ent = world.find(name)
    assert ent is not None
    known = known_facts(world, ent.id)
    own = [f"[{f.aspect or 'general'}] {f.text}" for f in known if f.subject == ent.id][-FACTS_PER_PLACE:]
    mentions = [f"[mentioned] {f.text}" for f in known if f.subject != ent.id][-MENTIONS_PER_PLACE:]
    chain = []
    for parent in world.parent_chain(ent.id):  # nearest first; stops at the first one the player does not know
        if not _visible(world, parent.id):
            break
        chain.append(parent)
    context = []
    for parent in reversed(chain):  # outermost first
        texts = [f.text for f in known_facts(world, parent.id) if f.subject == parent.id][:CONTEXT_FACTS]
        context.append(f"{parent.name}: " + (" ".join(_clip(t, CONTEXT_CHARS) for t in texts) or "(nothing more is known)"))
    return PlaceSubject(
        ent.name, list(ent.aliases), [*own, *mentions], context, about(recent_text, ent.name, ent.aliases)
    )


# ---- the sweep ---------------------------------------------------------------------------


async def run_place_looks(
    world: World,
    campaign: dict[str, Any],
    ruleset: str,
    curator: Curator,
    *,
    recent_text: str = "",
    limit: int = MAX_PER_SWEEP,
) -> PlaceLooksResult:
    """Write the missing Looks of describable places, up to `limit`. Never raises for a model failure."""
    result = PlaceLooksResult()
    write = getattr(curator, "place_look", None)
    todo = needing_places(world, recent_text)[:limit]
    if write is None or not todo:
        return result
    setting = str(campaign.get("setting", ""))
    existing = {f"{e.name}: {e.look.summary}": e.look for e in world.entities.values() if e.kind == "location" and e.look}
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
            accepted[name] = look
            result.ops.append(SetLook(name, look))
    return result


async def _describe_batch(
    write: Any,
    subjects: list[PlaceSubject],
    setting: str,
    ruleset: str,
    existing: dict[str, Look],
    result: PlaceLooksResult,
    split: bool = True,
) -> list[Look | None]:
    """One batch, with one retry for the places whose answers were rejected, and one split in two if the model cannot
    answer for all of them at once (`split` is False for the halves, which are not split again)."""
    accepted: list[Look | None] = [None] * len(subjects)
    feedback: dict[int, list[str]] = {}
    for attempt in range(2):
        wanted = [i for i, look in enumerate(accepted) if look is None]
        if not wanted:
            break
        request = PlaceLookRequest(subjects, setting, ruleset, list(existing), feedback)
        if attempt:  # the retry asks only for what failed
            request.subjects = [subjects[i] for i in wanted]
            request.feedback = {k: feedback[i] for k, i in enumerate(wanted)}
        try:
            answers = await write(request)
        except CuratorError as exc:
            if split and len(request.subjects) > 1:  # too much for one answer: two smaller ones
                return await _split(write, subjects, setting, ruleset, existing, result, accepted, wanted, exc)
            result.notes.append(f"place looks skipped ({exc})")
            return accepted
        except Exception as exc:  # a model failure never fails a turn
            log.exception("describing places failed")
            result.notes.append(f"place looks skipped ({type(exc).__name__}: {exc})")
            return accepted
        earlier, feedback = feedback, {}
        mapping = wanted if attempt else list(range(len(subjects)))
        for k, i in enumerate(mapping):
            look = answers.get(k)
            sub = subjects[i]
            found = ["no answer was given"] if look is None else problems(look, sub.name, PLACE)
            if look is not None:
                found += [
                    f"too like {label.split(':')[0]}: make this place clearly different"
                    for label, other in existing.items()
                    if too_alike(look, other)
                ][:1]
                found += [
                    f"too like {subjects[j].name}: make this place clearly different"
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
    subjects: list[PlaceSubject],
    setting: str,
    ruleset: str,
    existing: dict[str, Look],
    result: PlaceLooksResult,
    accepted: list[Look | None],
    wanted: list[int],
    why: Exception,
) -> list[Look | None]:
    """The model could not answer for the whole batch (it ran out of room, or did not return usable JSON): ask for each
    half separately, once. A half that fails again is skipped and left for a later sweep."""
    result.notes.append(f"a batch of {len(wanted)} places failed ({why}); trying two smaller ones")
    middle = len(wanted) // 2
    for part in (wanted[:middle], wanted[middle:]):
        got = await _describe_batch(write, [subjects[i] for i in part], setting, ruleset, existing, result, split=False)
        for i, look in zip(part, got):
            accepted[i] = look
    return accepted
