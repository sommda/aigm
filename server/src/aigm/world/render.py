"""Turns curator requests into the text of a model prompt. Pure functions, so they are easy to test."""

from aigm.world.curator import (
    BootstrapRequest,
    DigestRequest,
    ExpandRequest,
    ExtractRequest,
    PlotRequest,
    ReconcileRequest,
)
from aigm.world.model import Entity, Fact


def _fact(f: Fact) -> str:
    return f"- {f.id} [{f.disclosure}{', ' + f.aspect if f.aspect else ''}] {f.text}"


def _entity(e: Entity) -> str:
    also = f"; also called {', '.join(e.aliases)}" if e.aliases else ""
    return f"{e.id} {e.name} ({e.kind}{also})"


def render_extract(req: ExtractRequest) -> str:
    parts = []
    if req.setting:
        parts.append(f"## Setting\n{req.setting.strip()}")
    where = req.scene_location or "not recorded"
    with_ = ", ".join(req.present) or "nobody recorded"
    parts.append(f"## State before this transcript\nIn-world time: {req.time}\nThe party was at: {where}\nWith them: {with_}")
    parts.append("## Known names\n" + ("; ".join(req.entity_names) if req.entity_names else "(none yet)"))
    parts.append(
        "## GM-only facts (true, not yet told to the player)\n"
        + ("\n".join(f"- {f.id}: {f.text}" for f in req.hidden_facts) if req.hidden_facts else "(none)")
    )
    parts.append(f"## Transcript\n{req.transcript}")
    return "\n\n".join(parts)


def render_reconcile(req: ReconcileRequest) -> str:
    parts = ["## Proposals"]
    for item in req.items:
        p = item.proposal
        parts.append(f"[{item.index}] about {', '.join(p.about)} ({p.disclosure}): {p.text}")
        if item.neighbors:
            parts.append("  Related existing facts:\n" + "\n".join("  " + _fact(f) for f in item.neighbors))
        else:
            parts.append("  Related existing facts: none")
    if req.questions:
        parts.append("## Same entity?")
        for q in req.questions:
            parts.append(f'Proposed {q.proposal.kind} "{q.proposal.name}". Existing candidates:')
            parts += [f"  - {_entity(c)}" for c in q.candidates]
    return "\n".join(parts)


def render_expand(req: ExpandRequest, guides: dict[str, dict[str, str]]) -> str:
    ent = req.entity
    guide = guides.get(ent.kind, {})
    parts = []
    if req.setting:
        parts.append(f"## Setting\n{req.setting.strip()}")
    parts.append(f"## Now\nIn-world time: {req.time}")
    chain = " > ".join(p.name for p in reversed(req.parents))
    parts.append(f"## Entity to flesh out\n{_entity(ent)}" + (f"\nLocated in: {chain}" if chain else ""))
    parts.append(f"## Tier\n{req.tier}")
    parts.append(
        "## Missing aspects\n" + "\n".join(f"- {a}: {guide.get(a, '')}".rstrip(": ") for a in req.missing)
    )
    parts.append("## Already recorded about it\n" + ("\n".join(_fact(f) for f in req.facts) or "(nothing yet)"))
    if req.neighbor_facts:
        parts.append("## Nearby facts (do not restate)\n" + "\n".join(_fact(f) for f in req.neighbor_facts))
    if req.review:
        parts.append("## Review\n" + "\n".join(_fact(f) for f in req.review))
    parts.append("## Names already used (new entities need new names)\n" + "; ".join(req.known_names))
    if req.feedback:
        parts.append(
            "## Your previous answer was rejected\nFix these and answer again:\n" + "\n".join(f"- {x}" for x in req.feedback)
        )
    return "\n\n".join(parts)


def render_bootstrap(req: BootstrapRequest) -> str:
    parts = [f"## Setting\n{req.setting.strip()}", f"## Opening situation\n{req.opening.strip()}"]
    members = "\n\n".join(f"### {name}\n{sheet.strip()}" for name, sheet in req.party)
    parts.append(f"## Player characters (level {req.level})\n{members}")
    parts.append("## Private GM notes (the player has not been told these)\n" + (req.gm_notes.strip() or "(none)"))
    return "\n\n".join(parts)


def render_digest(req: DigestRequest) -> str:
    parts = [f"## Setting\n{req.setting.strip()}"] if req.setting else []
    parts += [f"## Turn {t.number}\n{t.text}" for t in req.turns]
    return "\n\n".join(parts)


MAX_PLOT_FACTS = 120  # facts shown to the plotter; the world at the start of a game is far smaller


def render_plot(req: PlotRequest) -> str:
    low, high = req.quests
    parts = [
        f"## Length\n{req.length}: {low} to {high} required quests per chapter; quest sizes allowed: "
        + ", ".join(req.scales),
        f"## Setting\n{req.setting.strip()}",
        f"## Opening situation\n{req.opening.strip()}",
    ]
    members = "\n\n".join(f"### {name}\n{sheet.strip()}" for name, sheet in req.party)
    parts.append(f"## Player characters (level {req.level})\n{members}")
    parts.append("## Private GM notes (the player has not been told these)\n" + (req.gm_notes.strip() or "(none)"))
    parts.append("## The world so far (entities)\n" + ("\n".join(_entity(e) for e in req.entities) or "(empty)"))
    facts = [f for f in req.facts if f.active][:MAX_PLOT_FACTS]
    parts.append("## The world so far (facts)\n" + ("\n".join(_fact(f) for f in facts) or "(none)"))
    which = ", ".join(str(c) for c in req.chapters)
    parts.append(f"## Write quests for chapter(s)\n{which}. Give the title and purpose of all three chapters.")
    if req.feedback:
        parts.append(
            "## Your previous answer was rejected\nFix these and answer again:\n" + "\n".join(f"- {x}" for x in req.feedback)
        )
    return "\n\n".join(parts)
