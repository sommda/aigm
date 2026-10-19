"""One curator pass: extract what the narration established, reconcile it with the world, then
expand the world ahead of the party (docs/WORLD.md section 4).

The model-facing work is delegated to a `Curator`; every rule that must hold whichever curator is
used (precedence between old and new facts, caps, connectivity, which entities to expand, what
counts as a page of narration) is enforced here."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from aigm.world.curator import (
    BootstrapRequest,
    Curator,
    DigestRequest,
    DigestTurn,
    EntityProposal,
    EntityQuestion,
    ExpandRequest,
    ExtractRequest,
    Extraction,
    FactProposal,
    Label,
    ReconcileItem,
    ReconcileRequest,
    ReconcileResult,
)
from aigm.history import digest_for, turn_chars, turns as split_turns
from aigm.world.digest import Digest, clean_digest_text
from aigm.world.independence import independence_problem, standalone_problem
from aigm.world.model import ASPECTS, DISCLOSURES, KINDS, Entity, Fact, World
from aigm.world.ops import (
    AddAlias,
    AddDigest,
    AddEntity,
    AddFact,
    Correct,
    MarkProcessed,
    Op,
    Reveal,
    SetScene,
    SettleTime,
    StartClock,
    Supersede,
    apply_ops,
)
from aigm.world.text import normalize_name, tokens

log = logging.getLogger(__name__)

DEFAULT_PAGE_CHARS = 1800
DEFAULT_EVERY_PAGES = 3.0
SITE_ASPECTS = ("approach", "discovery", "entry", "interior", "inhabitants", "history", "hazards", "connections", "secret")
SETTLEMENT_ASPECTS = ("layout", "leaders", "economy", "notable_places", "tensions", "history", "connections")
SKETCH_ASPECTS = {"site": ("approach", "entry", "inhabitants"), "settlement": ("layout", "notable_places")}
DEEP_ASPECTS = ("interior", "secret")  # left until the party is close


@dataclass
class PassConfig:
    max_extract_facts: int = 40
    max_expand_entities: int = 3  # entities fleshed out per pass
    max_new_facts: int = 30  # generated facts per pass
    max_new_entities: int = 8  # generated entities per pass
    max_facts_per_call: int = 10
    max_entities_per_call: int = 4
    neighbor_hits: int = 5
    digests: bool = True  # write digests of finished turns (docs/HISTORY.md)
    max_digest_turns: int = 40  # turns digested per pass (older saves are caught up over several passes)
    digest_batch: int = 8  # turns per curator call


@dataclass
class PassResult:
    ops: list[Op] = field(default_factory=list)  # to apply to the live world
    notes: list[str] = field(default_factory=list)  # what was dropped and why, for the log


# ---- reading the history ----------------------------------------------------------------


def narration_chars(messages: list[dict[str, Any]], start: int = 0) -> int:
    """Characters of GM narration (assistant text) from message index `start` on."""
    return sum(
        len(b.get("text", ""))
        for m in messages[start:]
        if m.get("role") == "assistant"
        for b in m.get("content", [])
        if b.get("type") == "text"
    )


def narration_pages(messages: list[dict[str, Any]], start: int = 0, page_chars: int = DEFAULT_PAGE_CHARS) -> float:
    return narration_chars(messages, start) / max(1, page_chars)


def player_turns(messages: list[dict[str, Any]]) -> int:
    return sum(
        1
        for m in messages
        if m.get("role") == "user" and any(b.get("type") == "text" for b in m.get("content", []))
    )


WORLD_TOOLS = ("establish", "set_scene")


def transcript(messages: list[dict[str, Any]]) -> str:
    """The conversation as plain text for the curator: what the player and GM said (including the
    narration that comes with each dice roll), plus a note of the GM's own world-tool calls. Dice, tool results and
    the server's [System: ...] notes are left out."""
    lines: list[str] = []
    for m in messages:
        for b in m.get("content", []):
            kind = b.get("type")
            text = b.get("text", "").strip()
            if kind == "text" and text and m["role"] == "assistant":
                lines.append(f"GM: {text}")
            elif kind == "text" and text and m["role"] == "user" and not text.startswith("[System:"):
                lines.append(f"PLAYER: {text}")
            elif kind == "tool_use" and b.get("name") == "roll_dice" and m["role"] == "assistant":
                narration = str((b.get("input") or {}).get("narration", "")).strip()
                if narration:  # the narration that leads into a roll was shown to the player as story text
                    lines.append(f"GM: {narration}")
            elif kind == "tool_use" and b.get("name") in WORLD_TOOLS:
                lines.append(f"[GM called {b['name']}: {b.get('input')}]")
    return "\n\n".join(lines)


# ---- the frontier -----------------------------------------------------------------------


def checklist(world: World, ent: Entity) -> tuple[str, ...]:
    if ent.kind != "location":
        return ASPECTS[ent.kind]
    settlement_only = set(SETTLEMENT_ASPECTS) - set(SITE_ASPECTS)
    is_settlement = bool(world.coverage(ent.id) & settlement_only) or len(world.children(ent.id)) >= 3
    return SETTLEMENT_ASPECTS if is_settlement else SITE_ASPECTS


def wanted_aspects(world: World, ent: Entity, tier: str) -> list[str]:
    full = checklist(world, ent)
    if tier == "full":
        return list(full)
    if tier == "most":
        return [a for a in full if a not in DEEP_ASPECTS]
    if ent.kind == "location":
        return list(SKETCH_ASPECTS["settlement" if full is SETTLEMENT_ASPECTS else "site"])
    return list(full[:2])


def frontier(world: World, limit: int) -> list[tuple[Entity, str, list[str]]]:
    """The entities to flesh out next, with how deep to go and which aspects are missing. Decided by
    graph distance from the party (the table in docs/WORLD.md 4.4); the model never chooses."""
    loc = world.scene.location
    if loc is None:
        return []
    dist = world.distances(loc)
    ranked = []
    for ent in world.entities.values():
        d = dist.get(ent.id)
        if d is None:
            if not ent.discovered:
                continue
            d = 99  # the player has heard of it, so it counts even if nothing links it to the scene yet
        if ent.id == loc or ent.parent == loc or ent.id in world.scene.present:
            rank, tier = 0, "full"
        elif d == 1 or ent.discovered:
            rank, tier = 1, "most"
        elif d == 2:
            rank, tier = 2, "sketch"
        else:
            continue
        covered = world.coverage(ent.id)
        missing = [a for a in wanted_aspects(world, ent, tier) if a not in covered]
        if missing:
            ranked.append(((rank, d, not ent.discovered, ent.id), ent, tier, missing))
    ranked.sort(key=lambda r: r[0])
    return [(ent, tier, missing) for _, ent, tier, missing in ranked[:limit]]


# ---- the pass ---------------------------------------------------------------------------


async def run_pass(
    world: World,
    messages: list[dict[str, Any]],
    curator: Curator,
    *,
    setting: str = "",
    party_names: list[str] | None = None,
    config: PassConfig | None = None,
) -> PassResult:
    """Run extract, reconcile and expand against a snapshot of the world and return the ops that
    capture the result. `world` is not modified. Raises whatever the curator raises, in which case
    nothing at all should be applied."""
    config = config or PassConfig()
    snap = world.copy()
    result = PassResult()
    turn = player_turns(messages)

    def commit(ops: list[Op]) -> None:
        applied = apply_ops(snap, ops)
        result.ops += applied.ops
        result.notes += applied.skipped

    pending = messages[world.processed_through :]
    if pending:
        extraction = await curator.extract(
            ExtractRequest(
                transcript=transcript(pending),
                setting=setting,
                time=snap.time,
                scene_location=snap.entity(snap.scene.location).name if snap.scene.location else None,
                present=[snap.entities[e].name for e in snap.scene.present],
                entity_names=[e.name for e in snap.entities.values()],
                hidden_facts=_scene_secrets(snap),
            )
        )
        commit(await _plan_extraction(snap, extraction, curator, turn, config, result))

    if config.digests:
        await _digest_turns(snap, messages, curator, setting, config, result)

    review: dict[str, list[Fact]] = {}  # entity id -> hidden facts to re-check after a correction
    for op in result.ops:
        if isinstance(op, Supersede):
            old = snap.fact(op.old_id)
            if old:
                review[old.subject] = [f for f in snap.facts_about(old.subject) if f.disclosure == "hidden"]

    await _expand_frontier(
        snap, curator, setting=setting, party_names=party_names or [], turn=turn, config=config, result=result,
        commit=commit, review=review,
    )  # fmt: skip

    result.ops.append(MarkProcessed(len(messages)))
    return result


async def _digest_turns(
    snap: World, messages: list[dict[str, Any]], curator: Curator, setting: str, config: PassConfig, result: PassResult
) -> None:
    """Write digests for finished turns that have none, oldest first. The first turn (the campaign record) is
    left out. This stage never fails the pass: turns without a digest are picked up again by the next one."""
    digest = getattr(curator, "digest", None)
    if digest is None:
        return
    todo = [t for t in split_turns(messages)[1:] if digest_for(t, snap.digests) is None][: config.max_digest_turns]
    for i in range(0, len(todo), max(1, config.digest_batch)):
        batch = todo[i : i + max(1, config.digest_batch)]
        request = DigestRequest(
            [DigestTurn(t.number, transcript(messages[t.start : t.end])) for t in batch], setting=setting
        )
        try:
            texts = await digest(request)
        except Exception as exc:  # a failed call must not lose the rest of the pass
            log.warning("digest call failed: %s", exc)
            result.notes.append(f"digest: {type(exc).__name__}: {exc}")
            return
        if len(texts) != len(batch):
            result.notes.append(f"digest: expected {len(batch)} digests, got {len(texts)}")
            continue
        ops: list[Op] = []
        for turn, text in zip(batch, texts):
            text = clean_digest_text(text) if isinstance(text, str) else ""
            if text:
                new = Digest(turn.start, turn.end, turn.number, text, turn_chars(messages, turn))
                ops.append(AddDigest(new, replace_stale=True))  # a mismatched digest of this turn is out of date
        applied = apply_ops(snap, ops)
        result.ops += applied.ops
        result.notes += applied.skipped


async def _expand_frontier(
    snap: World,
    curator: Curator,
    *,
    setting: str,
    party_names: list[str],
    turn: int,
    config: PassConfig,
    result: PassResult,
    commit: Callable[[list[Op]], None],
    review: dict[str, list[Fact]] | None = None,
    progress: Callable[[str], None] | None = None,
) -> None:
    """Flesh out the entities nearest the party, up to the pass caps, committing each result to `snap`."""
    review = review or {}
    new_facts = new_entities = 0
    for ent, tier, missing in frontier(snap, config.max_expand_entities):
        if new_facts >= config.max_new_facts and new_entities >= config.max_new_entities:
            break
        if progress:
            progress(f"Detailing {ent.name}...")
        request = ExpandRequest(
            entity=ent,
            tier=tier,
            missing=missing,
            facts=snap.facts_about(ent.id),
            parents=snap.parent_chain(ent.id),
            neighbor_facts=[f for n in sorted(snap.neighbors(ent.id)) for f in snap.facts_about(n)][:20],
            review=review.get(ent.id, []),
            known_names=[e.name for e in snap.entities.values()],
            setting=setting,
            time=snap.time,
        )
        out = await _independent_expansion(curator, request, party_names, result)
        ops = _plan_expansion(
            snap, out, turn, config, config.max_new_entities - new_entities, config.max_new_facts - new_facts, result
        )
        before = len(result.ops)
        commit(ops)
        added = result.ops[before:]
        new_entities += sum(isinstance(o, AddEntity) for o in added)
        new_facts += sum(isinstance(o, (AddFact, Supersede)) for o in added)


# ---- bootstrap --------------------------------------------------------------------------

BOOTSTRAP_CONFIG = PassConfig(max_expand_entities=5, max_new_facts=60, max_new_entities=16)


async def run_bootstrap(
    campaign: dict[str, Any],
    messages: list[dict[str, Any]],
    curator: Curator,
    *,
    config: PassConfig | None = None,
    progress: Callable[[str], None] | None = None,
) -> PassResult:
    """Seed a fresh world from the campaign record (docs/WORLD.md 4.6): record the setting, the
    party's ties and the private GM notes, set the opening scene and clock, then expand around the
    opening. Returns the ops for an empty world; `messages` is the history the first scene follows,
    which counts as already digested."""
    config = config or BOOTSTRAP_CONFIG
    emit = progress or (lambda _msg: None)
    snap = World()
    result = PassResult()
    party = [(str(m.get("name", "")), str(m.get("sheet", ""))) for m in campaign.get("party", []) if isinstance(m, dict)]

    def commit(ops: list[Op]) -> None:
        applied = apply_ops(snap, ops)
        result.ops += applied.ops
        result.notes += applied.skipped

    emit("Building the setting...")
    ex = await curator.bootstrap(
        BootstrapRequest(
            setting=str(campaign.get("setting", "")),
            opening=str(campaign.get("opening", "")),
            level=int(campaign.get("level") or 1),
            party=party,
            gm_notes=str(campaign.get("gm_notes") or ""),
        )
    )
    ex = _clean_extraction(ex, config, result, standalone=True)
    ops: list[Op] = []
    if isinstance(ex.start_hour, int) and not isinstance(ex.start_hour, bool) and 0 <= ex.start_hour < 24:
        ops.append(StartClock(ex.start_hour))
    by_name = {normalize_name(e.name): e for e in ex.entities}

    def depth(e: EntityProposal) -> int:
        n, seen = 0, set()
        while e.parent and normalize_name(e.parent) in by_name and normalize_name(e.name) not in seen:
            seen.add(normalize_name(e.name))
            e, n = by_name[normalize_name(e.parent)], n + 1
        return n

    for prop in sorted(ex.entities, key=depth):  # containers before the things inside them
        ops.append(AddEntity(prop.name, prop.kind, tuple(prop.aliases), prop.parent))
    for prop in ex.facts:
        kinds = [by_name[normalize_name(a)].kind if normalize_name(a) in by_name else None for a in prop.about]
        aspect = prop.aspect if kinds and kinds[0] in ASPECTS and prop.aspect in ASPECTS[kinds[0]] else None
        ops.append(AddFact(prop.text, tuple(prop.about), aspect, prop.disclosure, "seed", 0))
    if ex.location:
        ops.append(SetScene(ex.location, tuple(ex.present or ())))
    commit(ops)
    if snap.is_empty:
        raise ValueError("the curator recorded nothing from the campaign record")

    await _expand_frontier(
        snap, curator, setting=str(campaign.get("setting", "")), party_names=[n for n, _ in party], turn=0,
        config=config, result=result, commit=commit, progress=emit,
    )  # fmt: skip
    result.ops.append(MarkProcessed(len(messages)))
    return result


def _scene_secrets(world: World, limit: int = 40) -> list[Fact]:
    """The GM-only facts around the party, which the narration may have just revealed."""
    ids = [world.scene.location, *world.scene.present] if world.scene.location else list(world.scene.present)
    near = {i for i in ids if i}
    if world.scene.location:
        near |= world.neighbors(world.scene.location)
    facts = {f.id: f for eid in sorted(near) for f in world.facts_about(eid) if f.disclosure != "known"}
    return list(facts.values())[:limit]


async def _independent_expansion(curator: Curator, request: ExpandRequest, party: list[str], result: PassResult) -> Extraction:
    """Ask the world-builder, check the answer against the independence rules, and ask once more
    (telling it what was wrong) if anything fails. Facts that still fail are dropped."""

    def problems(ex: Extraction) -> dict[int, str]:
        found = {}
        for i, fact in enumerate(ex.facts):
            why = independence_problem(fact.text, party) if isinstance(fact.text, str) else "no text"
            if why:
                found[i] = why
        return found

    out = await curator.expand(request)
    bad = problems(out)
    if bad:
        retry = replace(request, feedback=[f"{out.facts[i].text!r}: {why}" for i, why in bad.items()])
        out = await curator.expand(retry)
        bad = problems(out)
    judge = getattr(curator, "judge_independence", None)
    if judge and out.facts:
        try:
            for i in await judge([f.text for f in out.facts]):
                if isinstance(i, int) and 0 <= i < len(out.facts):
                    bad.setdefault(i, "judged to depend on the party or the player's actions")
        except Exception:
            log.exception("independence check failed; keeping the rule-based result")
    for i in sorted(bad, reverse=True):
        result.notes.append(f"dropped generated fact ({bad[i]}): {out.facts[i].text!r}")
        del out.facts[i]
    return out


# ---- extraction: reconcile and precedence -----------------------------------------------


def _clean_extraction(ex: Extraction, config: PassConfig, result: PassResult, standalone: bool = False) -> Extraction:
    ex.entities = [
        e for e in ex.entities if isinstance(e.name, str) and e.name.strip() and e.kind in KINDS
    ]
    ex.facts = [
        f
        for f in ex.facts
        if isinstance(f.text, str) and f.text.strip() and f.about and all(isinstance(a, str) for a in f.about)
    ][: config.max_extract_facts]
    if standalone:
        kept = []
        for f in ex.facts:
            why = standalone_problem(f.text)
            if why:
                result.notes.append(f"dropped extracted fact ({why}): {f.text!r}")
            else:
                kept.append(f)
        ex.facts = kept
    for fact in ex.facts:
        if fact.disclosure not in DISCLOSURES:
            fact.disclosure = "hidden"
    ex.elapsed_hours = ex.elapsed_hours if isinstance(ex.elapsed_hours, int) and ex.elapsed_hours > 0 else 0
    return ex


async def _plan_extraction(
    world: World, ex: Extraction, curator: Curator, turn: int, config: PassConfig, result: PassResult
) -> list[Op]:
    ex = _clean_extraction(ex, config, result, standalone=True)
    ops: list[Op] = []

    # Entities that match nothing by name but resemble something: ask whether they are the same.
    questions: list[EntityQuestion] = []
    for prop in ex.entities:
        if world.find(prop.name) is None:
            candidates = _lookalikes(world, prop)
            if candidates:
                questions.append(EntityQuestion(prop, candidates))

    # Facts the server can settle itself, then neighbors for the rest.
    items: list[ReconcileItem] = []
    settled: dict[int, Label] = {}
    candidate_ids = {q.proposal.name: [c.id for c in q.candidates] for q in questions}
    for i, prop in enumerate(ex.facts):
        subjects = [world.find(a) for a in prop.about]
        known_subjects = [s for s in subjects if s]
        twin = world.similar_fact(prop.text, known_subjects[0].id) if subjects[0] else None
        if twin:
            settled[i] = Label(i, "duplicate", twin.id)
            continue
        ids = {s.id for s in known_subjects}
        for name in prop.about:
            ids.update(candidate_ids.get(name, ()))
        neighbors: dict[str, Fact] = {}
        for eid in ids:
            for f in world.facts_about(eid):
                neighbors[f.id] = f
        for f in world.search(prop.text, limit=config.neighbor_hits):
            neighbors.setdefault(f.id, f)
        items.append(ReconcileItem(i, prop, list(neighbors.values())))

    verdict = ReconcileResult()
    if items or questions:
        verdict = await curator.reconcile(ReconcileRequest(items, questions))
    labels = {**settled, **{lab.index: lab for lab in verdict.labels if isinstance(lab, Label)}}

    # Entity identity and new entities.
    for prop in ex.entities:
        same = verdict.same_as.get(prop.name)
        if same and world.entity(same):
            ops.append(AddAlias(same, prop.name))
            ops += [AddAlias(same, a) for a in prop.aliases]
        else:
            ops.append(AddEntity(prop.name, prop.kind, tuple(prop.aliases), prop.parent))
    for name, eid in verdict.same_as.items():  # also covers names only mentioned inside facts
        if world.entity(eid) and not any(isinstance(o, AddAlias) and o.alias == name for o in ops):
            ops.append(AddAlias(eid, name))

    # Precedence rules (docs/WORLD.md 4.3).
    dropped: set[int] = set()
    for i, lab in labels.items():
        if lab.label == "contradicts" and lab.with_proposal is not None and lab.with_proposal < i:
            dropped.add(lab.with_proposal)  # two proposals clash: the later one wins
    for i, prop in enumerate(ex.facts):
        if i in dropped:
            result.notes.append(f"dropped by a later proposal: {prop.text!r}")
            continue
        lab = labels.get(i, Label(i, "new"))
        existing = world.fact(lab.existing_id) if lab.existing_id else None
        if lab.label == "duplicate":
            if existing and existing.active and existing.disclosure != "known" and prop.disclosure == "known":
                ops.append(Reveal(existing.id, turn))  # the narration just told the player
            continue
        if lab.label == "contradicts" and existing and existing.active:
            if existing.disclosure == "known":
                ops.append(
                    Correct(
                        f"The player was told: {existing.text} Your last reply said otherwise "
                        f"({prop.text}). Treat the first as true.",
                        turn,
                    )
                )
                result.notes.append(f"rejected, contradicts known {existing.id}: {prop.text!r}")
                continue
            ops.append(Supersede(existing.id, prop.text, prop.aspect, prop.disclosure, "play", turn))
            continue
        ops.append(AddFact(prop.text, tuple(prop.about), prop.aspect, prop.disclosure, "play", turn))

    for fid in ex.reveals:
        if isinstance(fid, str):
            ops.append(Reveal(fid, turn))
    if ex.location:
        ops.append(SetScene(ex.location, tuple(ex.present) if ex.present is not None else None))
    elif ex.present is not None:
        loc = world.entity(world.scene.location) if world.scene.location else None
        if loc:
            ops.append(SetScene(loc.name, tuple(ex.present)))
    ops.append(SettleTime(ex.elapsed_hours))
    return ops


def _lookalikes(world: World, prop: EntityProposal) -> list[Entity]:
    mine = tokens(prop.name)
    out = [
        e
        for e in world.entities.values()
        if e.kind == prop.kind and any(mine & tokens(n) for n in e.names())
    ]
    return out[:5]


# ---- expansion: validation --------------------------------------------------------------


def _plan_expansion(
    world: World,
    out: Extraction,
    turn: int,
    config: PassConfig,
    entity_room: int,
    fact_room: int,
    result: PassResult,
) -> list[Op]:
    """Turn the world-builder's answer into ops, keeping only what is allowed: new entities must be
    connected to the existing world, everything is generated hidden, and the caps are respected."""
    out = _clean_extraction(out, config, result)
    entity_cap = max(0, min(config.max_entities_per_call, entity_room))
    fact_cap = max(0, min(config.max_facts_per_call, fact_room))

    new = {normalize_name(e.name): e for e in out.entities if world.find(e.name) is None}
    for key in list(new)[entity_cap:]:
        result.notes.append(f"over the entity cap: {new.pop(key).name!r}")

    def known_name(name: str) -> bool:
        return world.find(name) is not None

    connected: set[str] = set()  # normalized names of new entities that reach the existing world
    changed = True
    while changed:
        changed = False
        for key, prop in new.items():
            if key in connected:
                continue
            links = ([prop.parent] if prop.parent else []) + [
                a for f in out.facts if any(normalize_name(x) == key for x in f.about) for a in f.about
            ]
            if any(known_name(n) or normalize_name(n) in connected for n in links if normalize_name(n) != key):
                connected.add(key)
                changed = True
    for key in set(new) - connected:
        result.notes.append(f"dropped unconnected entity {new.pop(key).name!r}")

    ops: list[Op] = []
    for prop in new.values():
        parent = prop.parent if prop.parent and (known_name(prop.parent) or normalize_name(prop.parent) in new) else None
        ops.append(AddEntity(prop.name, prop.kind, tuple(prop.aliases), parent))

    def kind_of(name: str) -> str | None:
        ent = world.find(name)
        if ent:
            return ent.kind
        prop = new.get(normalize_name(name))
        return prop.kind if prop else None

    n_facts = 0
    for prop in out.facts:
        if n_facts >= fact_cap:
            result.notes.append(f"over the fact cap: {prop.text!r}")
            continue
        kinds = [kind_of(a) for a in prop.about]
        if any(k is None for k in kinds):
            result.notes.append(f"dropped fact about an unknown or dropped entity: {prop.text!r}")
            continue
        aspect = prop.aspect if prop.aspect in ASPECTS.get(kinds[0], ()) else None
        old = world.fact(prop.replaces) if prop.replaces else None
        if old and old.active and old.disclosure == "hidden":
            ops.append(Supersede(old.id, prop.text, aspect, "hidden", "generated", turn))
        else:
            ops.append(AddFact(prop.text, tuple(prop.about), aspect, "hidden", "generated", turn))
        n_facts += 1
    return ops
