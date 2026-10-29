"""The describer's sweep: write a Look for every character that has none (docs/LOOKS.md 5).

The model-facing work is `Curator.look`. The rules that must hold whichever curator is used (who is described and in
what order, batching, the content rules, no near-duplicates, keeping what was already decided, one retry) are here.
Nothing in this module raises for a model failure: a character without a Look is simply tried again by the next sweep."""

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aigm.looks import Look, problems
from aigm.world.curator import Curator, CuratorError, LookRequest, LookRevision, LookSubject, ReviseRequest, ReviseSubject
from aigm.world.model import Entity, World
from aigm.world.ops import Correct, Op, ReviseLook, SetLook
from aigm.world.passes import _members
from aigm.world.text import STOPWORDS, normalize_name, tokens

log = logging.getLogger(__name__)

BATCH = 6  # characters per curator call, so the cast of a call is varied
MAX_PER_SWEEP = 12
MAX_CONCURRENT = 4  # batches in flight at once
FACTS_PER_SUBJECT = 12
FACT_ASPECTS = ("appearance", "role", "manner", "location", None)  # what bears on how someone looks
SIMILAR_SUMMARY = 0.85  # token overlap of two summaries above which the looks count as the same
HINT_COVERAGE = 0.5  # share of a hint's significant words that must survive into the look


@dataclass
class Given:
    """Appearance that has already been decided and must be kept."""

    texts: list[str]
    source: str  # the Look's `source`: session_zero | narration
    by: str  # words for the prompt: "the player in Session 0", "the narration"


@dataclass
class LooksResult:
    ops: list[Op] = field(default_factory=list)  # SetLook for people, to apply to the live world
    party: dict[str, Look] = field(default_factory=dict)  # party members' Looks, by name
    notes: list[str] = field(default_factory=list)  # what was skipped and why, for the log


# ---- who needs a Look -------------------------------------------------------------------


def needing(
    world: World, party_names: list[str], party_looks: dict[str, Look], recent_text: str = ""
) -> list[tuple[bool, str]]:
    """The characters with no Look, as (is a party member, name), in the order they should be described: party
    members, then people in the scene, then people named in `recent_text` (the last turn's narration), then those the
    characters' backgrounds name, those the player has met, and the rest."""
    out: list[tuple[bool, str]] = [(True, n) for n in party_names if n not in party_looks]
    people = [e for e in world.entities.values() if e.kind == "npc" and e.look is None]
    recent = {e.id for e in world.mentioned(recent_text)} if recent_text else set()
    background = {f.about[0] for f in world.facts.values() if f.active and f.source == "background"}

    def tier(e: Entity) -> int:
        if e.id in world.scene.present:
            return 0
        if e.id in recent:
            return 1
        if e.id in background:
            return 2
        return 3 if e.discovered else 4

    out += [(False, e.name) for e in sorted(people, key=lambda e: (tier(e), int(e.id[1:])))]
    return out


# ---- checks that need more than one Look -------------------------------------------------


def too_similar(a: Look, b: Look) -> bool:
    """Would a painter draw the same person twice? The same controlled tags with the same hair and eyes, or
    summaries that share most of their words."""
    keys = ("ancestry", "age", "gender", "build", "height")
    if all(a.tags.get(k) == b.tags.get(k) for k in keys) and all(
        a.tags.get(k, "").lower() == b.tags.get(k, "").lower() and a.tags.get(k) for k in ("hair", "eyes")
    ):
        return True
    ta, tb = tokens(a.summary), tokens(b.summary)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= SIMILAR_SUMMARY


def _significant(text: str) -> set[str]:
    return {w[:5] for w in tokens(text) if w not in STOPWORDS}


def missing_details(look: Look, given: list[str]) -> list[str]:
    """The decided details that did not make it into the look. A detail counts as kept when at least half of its
    significant words (compared by their first five letters, so "braided" matches "braids") appear in the description
    or tags."""
    haystack = _significant(
        " ".join([look.summary, look.description, *(" ".join(v) if isinstance(v, list) else str(v) for v in look.tags.values())])
    )
    out = []
    for detail in given:
        words = _significant(detail)
        if words and len(words & haystack) / len(words) < HINT_COVERAGE:
            out.append(detail)
    return out


# ---- the story's sentences about a character ----------------------------------------------

MAX_NARRATION_SENTENCES = 6  # per character
FOLLOWING = 2  # sentences after a mention that still count as about the character
CUES = frozenset(
    """hair haired eyes eyed eyebrow eyebrows beard bearded moustache mustache sideburns scar scarred tattoo tattooed
    wearing wears wore dressed cloak robe robes tunic coat hat hood hooded armor armour skin tanned freckled freckles
    bald blond blonde auburn gaunt stout limp limped limps missing earring necklace apron jerkin helm helmet gloves
    cheek cheeks brow nose jaw lips teeth braid braided plait shouldered tall bearing complexion""".split()
)  # specific words only: colors and "face", "short" or "ring" turn up in most paragraphs
TITLES = frozenset(
    """lord lady sir dame master mistress mother father brother sister old young king queen prince princess marshal
    captain reeve gaffer goodwife goodman bargewife saltwife sailmaker harbormaster washmistress boilerman sexton
    brother cooper""".split()
)  # words that many people share, so they do not identify one
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
_LOOK_DIRECTIVE = "[[look:"  # test mode: the scripted GM can state a look change by hand (aigm.world.scripted)


def sentences(text: str) -> list[str]:
    return [x.strip() for x in _SENTENCE_END.split(text) if x.strip()]


def _name_words(name: str, aliases: list[str]) -> set[str]:
    """The words that identify a character on their own: those of the name and aliases, less titles, and less the
    first word of a name of three or more ("Reeve" in "Reeve Tamsin Cobb")."""
    out: set[str] = set()
    for n in (name, *aliases):
        words = tokens(n)
        first = n.split()[0].lower().strip(".,'") if n.split() else ""
        if len(n.split()) >= 3:
            words.discard(first)
        out |= words - TITLES
    return out


def about(text: str, name: str, aliases: list[str] | None = None) -> list[str]:
    """The sentences of `text` that name a character (the full name, or any word of it written with a capital letter,
    "Marta" for Marta Venn) and the two after each, since description often says "she" or "his". Used as context for a
    model that is told whom to look at, so a stray match only costs a few tokens."""
    words = _name_words(name, aliases or [])
    parts = sentences(text)
    keep: set[int] = set()
    for i, sentence in enumerate(parts):
        capitalised = {w.lower() for w in re.findall(r"\b[A-Z][\w'-]*", sentence)}
        if name.lower() in sentence.lower() or words & capitalised:
            keep.update(range(i, min(i + FOLLOWING + 1, len(parts))))
    return [parts[i] for i in sorted(keep)][:MAX_NARRATION_SENTENCES]


def describing(sentence: str) -> bool:
    """Does a sentence look like it describes someone's appearance? A cheap gate before asking a model."""
    return _LOOK_DIRECTIVE in sentence.lower() or bool(CUES & set(re.findall(r"[a-z]+", sentence.lower())))


# ---- the sweep ----------------------------------------------------------------------------


def _subject(
    world: World, campaign: dict[str, Any], is_party: bool, name: str, given: dict[str, Given], recent_text: str = ""
) -> tuple[LookSubject, Given | None]:
    note = given.get(normalize_name(name))
    if is_party:
        member = next((m for m in campaign.get("party", []) if isinstance(m, dict) and m.get("name") == name), {})
        sheet, background = str(member.get("sheet", "")), str(member.get("background", ""))
        appearance = str(member.get("appearance") or "").strip()
        if appearance:
            note = Given([appearance], "session_zero", "the player in Session 0")
        return LookSubject(name, True, sheet=sheet, background=background), note
    ent = world.find(name)
    assert ent is not None
    if note is None:  # a key person made in Session 0 may come with an appearance
        person = next(
            (c for c in campaign.get("characters", []) if isinstance(c, dict) and normalize_name(str(c.get("name"))) == normalize_name(name)),
            None,
        )
        if person and str(person.get("appearance") or "").strip():
            note = Given([str(person["appearance"]).strip()], "session_zero", "the player in Session 0")
    facts = [
        f"[{f.disclosure}] {f.text}"
        for f in world.facts_about(ent.id)
        if f.subject == ent.id and f.aspect in FACT_ASPECTS
    ][-FACTS_PER_SUBJECT:]
    return (
        LookSubject(name, False, aliases=list(ent.aliases), facts=facts, narration=about(recent_text, name, ent.aliases)),
        note,
    )


async def run_looks(
    world: World,
    campaign: dict[str, Any],
    ruleset: str,
    party_looks: dict[str, Look],
    curator: Curator,
    *,
    given: dict[str, Given] | None = None,
    recent_text: str = "",
    limit: int = MAX_PER_SWEEP,
    progress: Callable[[str], None] | None = None,
) -> LooksResult:
    """Write the Looks that are missing, up to `limit` characters. `given` maps a character's name (normalized with
    `normalize_name`) to appearance that must be kept. Never raises for a model failure."""
    result = LooksResult()
    write = getattr(curator, "look", None)
    party_names = [n for n, _, _ in _members(campaign)]
    todo = needing(world, party_names, party_looks, recent_text)[:limit]
    if write is None or not todo:
        return result
    if progress:
        progress("Picturing the characters...")
    given = given or {}
    existing = {f"{n}: {lk.summary}": lk for n, lk in party_looks.items()}
    existing.update({f"{e.name}: {e.look.summary}": e.look for e in world.entities.values() if e.look})
    setting = str(campaign.get("setting", ""))
    pending = list(todo)
    for _ in range(2):  # a second round re-describes the characters that came out too like one from another batch
        if not pending:
            break
        pending = await _round(write, pending, world, campaign, setting, ruleset, existing, given, recent_text, result)
    return result


async def _round(
    write: Any,
    pending: list[tuple[bool, str]],
    world: World,
    campaign: dict[str, Any],
    setting: str,
    ruleset: str,
    existing: dict[str, Look],
    given: dict[str, Given],
    recent_text: str,
    result: LooksResult,
) -> list[tuple[bool, str]]:
    """Describe `pending` in concurrent batches (the model is the slow part), accept the Looks that pass, and return
    the characters to try again: those whose Look came out too like another one accepted in this round."""
    batches = [pending[i : i + BATCH] for i in range(0, len(pending), BATCH)]
    built = [[_subject(world, campaign, p, n, given, recent_text) for p, n in batch] for batch in batches]
    gate = asyncio.Semaphore(MAX_CONCURRENT)

    async def one(items: list[tuple[LookSubject, Given | None]]) -> list[Look | None]:
        async with gate:
            return await _describe_batch(write, items, setting, ruleset, dict(existing), result)

    done = await asyncio.gather(*(one(items) for items in built))
    again: list[tuple[bool, str]] = []
    accepted_now: dict[str, Look] = {}
    for batch, items, looks in zip(batches, built, done):
        for (is_party, name), (sub, note), look in zip(batch, items, looks):
            if look is None:
                continue
            clash = next((other for other, lk in accepted_now.items() if too_similar(look, lk)), None)
            if clash:
                again.append((is_party, name))
                continue
            look.source = note.source if note else ("narration" if sub.narration else "generated")
            look.state = "fixed" if is_party and note and note.source == "session_zero" else "provisional"
            accepted_now[name] = look
            existing[f"{name}: {look.summary}"] = look
            if is_party:
                result.party[name] = look
            else:
                result.ops.append(SetLook(name, look))
    return again


async def _describe_batch(
    write: Any,
    built: list[tuple[LookSubject, Given | None]],
    setting: str,
    ruleset: str,
    existing: dict[str, Look],
    result: LooksResult,
) -> list[Look | None]:
    """One batch, with one retry for the characters whose answers were rejected."""
    subjects = []
    for sub, note in built:
        if note:
            sub.given, sub.given_by = list(note.texts), note.by
        subjects.append(sub)
    accepted: list[Look | None] = [None] * len(subjects)
    feedback: dict[int, list[str]] = {}
    for attempt in range(2):
        wanted = [i for i, look in enumerate(accepted) if look is None]
        if not wanted:
            break
        request = LookRequest(subjects, setting, ruleset, list(existing), feedback)
        if attempt:  # the retry asks only for what failed
            request.subjects = [subjects[i] for i in wanted]
            request.feedback = {k: feedback[i] for k, i in enumerate(wanted)}
        try:
            answers = await write(request)
        except CuratorError as exc:
            result.notes.append(f"looks skipped ({exc})")
            return accepted
        except Exception as exc:  # a model failure never fails a turn or the start of a game
            log.exception("describing characters failed")
            result.notes.append(f"looks skipped ({type(exc).__name__}: {exc})")
            return accepted
        earlier, feedback = feedback, {}
        mapping = wanted if attempt else list(range(len(subjects)))
        for k, i in enumerate(mapping):
            look = answers.get(k)
            sub = subjects[i]
            found = ["no answer was given"] if look is None else problems(look, sub.name)
            if look is not None:
                found += [f"the decided detail is missing or changed: {d}" for d in missing_details(look, sub.given)]
                found += [
                    f"too like {label.split(':')[0]}: make this character clearly different"
                    for label, other in existing.items()
                    if too_similar(look, other)
                ][:1]
                found += [
                    f"too like {subjects[j].name}: make this character clearly different"
                    for j, other in enumerate(accepted)
                    if other is not None and j != i and too_similar(look, other)
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


# ---- revising a Look after the story described someone (docs/LOOKS.md 7) -----------------


@dataclass
class RevisionResult:
    ops: list[Op] = field(default_factory=list)  # ReviseLook for people, Correct notes for the GM
    party: dict[str, Look] = field(default_factory=dict)  # party members' revised Looks, by name
    notes: list[str] = field(default_factory=list)


MAX_REVISE_PER_CALL = 6


def revision_candidates(
    world: World, party_names: list[str], party_looks: dict[str, Look], narration: str
) -> list[ReviseSubject]:
    """The characters with a Look whom the narration names in a sentence that looks like description."""
    out: list[ReviseSubject] = []
    people = [(True, n, [], party_looks[n]) for n in party_names if n in party_looks]
    people += [(False, e.name, e.aliases, e.look) for e in world.entities.values() if e.kind == "npc" and e.look]
    for is_party, name, aliases, look in people:
        hits = [x for x in about(narration, name, aliases) if describing(x)]
        if hits:
            out.append(ReviseSubject(name, is_party, look, hits, look.state == "fixed"))
    return out[:MAX_REVISE_PER_CALL]


def _revision_ops(
    sub: ReviseSubject, answer: LookRevision | None, turn: int, result: RevisionResult
) -> None:
    """Apply the rules of docs/LOOKS.md 7 to one verdict."""
    if answer is None or answer.verdict == "same":
        return
    name = sub.name
    if answer.verdict == "contradicts":
        if sub.fixed:  # the picture stays; the GM is told to put it right
            note = answer.note.strip() or f"the story described {name} differently from their look"
            text = f"{name}'s look is settled: {note}. Describe {name} that way from now on."
            result.ops.append(Correct(text, turn))
            return
    elif answer.verdict == "adds" and sub.fixed:
        result.notes.append(f"{name}: a new detail was ignored because the look is fixed")
        return
    elif answer.verdict not in ("adds", "lasting", "contradicts"):
        result.notes.append(f"{name}: unknown verdict {answer.verdict!r}")
        return
    revised = answer.look
    if revised is None:
        result.notes.append(f"{name}: a {answer.verdict} verdict came without a look")
        return
    old = sub.current
    revised = Look(revised.summary, revised.description, revised.tags, old.rev + 1, old.state, "narration")
    found = problems(revised, name)
    if found:
        result.notes.append(f"{name}: revision refused ({'; '.join(found)})")
        return
    if revised.description == old.description and revised.tags == old.tags:
        return
    log.info("look of %s revised to rev %s (%s): %s", name, revised.rev, answer.verdict, sub.narration[0])
    if sub.party:
        result.party[name] = revised
    else:
        result.ops.append(ReviseLook(name, revised))


async def run_revisions(
    world: World,
    campaign: dict[str, Any],
    party_looks: dict[str, Look],
    curator: Curator,
    narration: str,
    *,
    turn: int = 0,
) -> RevisionResult:
    """Check the last turn's narration against the Looks of the characters it describes, and revise them: a
    provisional Look takes new and contradicting detail (the story wins, because the player was told); a fixed Look
    changes only for a lasting change, and a contradiction becomes a correction note for the GM. Never raises."""
    result = RevisionResult()
    check = getattr(curator, "revise_looks", None)
    if check is None or not narration.strip():
        return result
    subjects = revision_candidates(world, [n for n, _, _ in _members(campaign)], party_looks, narration)
    if not subjects:
        return result
    try:
        answers = await check(ReviseRequest(subjects, str(campaign.get("setting", ""))))
    except CuratorError as exc:
        result.notes.append(f"look revisions skipped ({exc})")
        return result
    except Exception as exc:
        log.exception("checking looks against the story failed")
        result.notes.append(f"look revisions skipped ({type(exc).__name__}: {exc})")
        return result
    for i, sub in enumerate(subjects):
        _revision_ops(sub, answers.get(i), turn, result)
    return result
