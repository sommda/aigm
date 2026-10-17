"""The world briefing: the slice of the knowledge base the GM is shown with each request.

Built from the world state by fixed rules, in priority order, within a size budget (docs/WORLD.md
6.1). It includes hidden facts, labeled so the GM can tell what the player has not been told."""

from aigm.world.model import Entity, Fact, World

CHARS_PER_TOKEN = 4  # rough; the budget is a guide, not a hard limit
LABELS = {
    "known": "known",
    "hinted": "GM only: the player has heard only hints of this",
    "hidden": "GM only, not yet known to the player",
}
_ORDER = {"known": 0, "hinted": 1, "hidden": 2}
LOCATION_FACTS = 14
PRESENT_FACTS = 8
NEARBY_PLACES = 6
RELEVANT_FACTS = 3
SEARCH_HITS = 5
_PATH_ASPECTS = ("approach", "connections", "entry", "discovery")  # most useful one-liners for a place


def time_of_day(hour: int) -> str:
    if 5 <= hour < 7:
        return "dawn"
    if 7 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def _by_disclosure(facts: list[Fact]) -> list[Fact]:
    return sorted(facts, key=lambda f: (_ORDER[f.disclosure], int(f.id[1:])))


class _Budget:
    """Collects lines until the size budget runs out. Lower-priority lines are added later, so
    once one does not fit, everything after it is dropped as well."""

    def __init__(self, chars: int) -> None:
        self.chars = chars
        self.lines: list[str] = []
        self.used = 0
        self.full = False
        self.seen: set[str] = set()  # fact ids already shown

    def add(self, line: str, fact: Fact | None = None, *, force: bool = False) -> bool:
        if fact is not None and fact.id in self.seen:
            return True
        if self.full and not force:
            return False
        if not force and self.used + len(line) + 1 > self.chars:
            self.full = True
            return False
        self.lines.append(line)
        self.used += len(line) + 1
        if fact is not None:
            self.seen.add(fact.id)
        return True


def fact_line(fact: Fact, prefix: str = "") -> str:
    return f"- {prefix}[{LABELS[fact.disclosure]}] {fact.text}"


def build_briefing(world: World, *, user_text: str = "", gm_text: str = "", budget_tokens: int = 2000) -> str:
    """The briefing text, or "" when the world has nothing in it yet."""
    if world.is_empty:
        return ""
    out = _Budget(budget_tokens * CHARS_PER_TOKEN)
    out.add(f"Time: {world.time} ({time_of_day(world.time.hour)})", force=True)

    shown: set[str] = set()  # entities covered in the sections above the free-form ones
    loc = world.entity(world.scene.location) if world.scene.location else None
    if loc:
        shown.add(loc.id)
        chain = " in ".join(p.name for p in world.parent_chain(loc.id))
        out.add(f"Location: {loc.name}" + (f" (in {chain})" if chain else ""), force=True)
        for fact in _by_disclosure(world.facts_about(loc.id))[:LOCATION_FACTS]:
            out.add(fact_line(fact), fact)
    else:
        out.add("Location: not yet recorded", force=True)

    present = [e for eid in world.scene.present if (e := world.entity(eid))]
    if present:
        out.add("Present:")
    for npc in present:
        shown.add(npc.id)
        out.add(f"{npc.name} ({npc.kind}, {_aliases(npc)})".replace(", )", ")"))
        for fact in _by_disclosure(world.facts_about(npc.id))[:PRESENT_FACTS]:
            out.add(fact_line(fact), fact)

    nearby = _nearby(world, loc) if loc else []
    if nearby:
        out.add("Nearby:")
    for place in nearby:
        shown.add(place.id)
        fact = _one_liner([f for f in world.facts_about(place.id) if f.id not in out.seen])
        if fact is None:
            out.add(f"- {place.name}")
        else:
            out.add(fact_line(fact, f"{place.name}: "), fact)

    relevant = _relevant(world, f"{user_text}\n{gm_text}", shown)
    if relevant:
        out.add("Also relevant:")
    for fact in relevant:
        out.add(fact_line(fact), fact)

    if world.corrections:
        out.add("Corrections (reconcile these in your next reply if natural, without breaking the fiction):", force=True)
        for note in world.corrections:
            out.add(f"- {note['text']}", force=True)

    return "\n".join(out.lines)


def _aliases(ent: Entity) -> str:
    return f"also called {', '.join(ent.aliases)}" if ent.aliases else ""


def _nearby(world: World, loc: Entity) -> list[Entity]:
    chain = {p.id for p in world.parent_chain(loc.id)}
    places = [
        world.entities[eid]
        for eid in world.neighbors(loc.id)
        if world.entities[eid].kind == "location" and eid not in chain
    ]
    return sorted(places, key=lambda e: e.id)[:NEARBY_PLACES]


def _one_liner(facts: list[Fact]) -> Fact | None:
    """The fact that best sums up a place for someone deciding where to go."""
    if not facts:
        return None
    for aspect in _PATH_ASPECTS:
        for fact in _by_disclosure(facts):
            if fact.aspect == aspect:
                return fact
    return _by_disclosure(facts)[0]


def _relevant(world: World, text: str, shown: set[str]) -> list[Fact]:
    """Facts the GM may need because the conversation mentions them. These come from outside
    the scene, so only what the player knows or has heard hints of is included; `recall` is for
    the rest."""
    facts: list[Fact] = []
    seen: set[str] = set()

    def take(fact: Fact) -> None:
        if fact.id not in seen and fact.disclosure != "hidden":
            seen.add(fact.id)
            facts.append(fact)

    for ent in world.mentioned(text):
        if ent.id not in shown:
            for fact in [f for f in _by_disclosure(world.facts_about(ent.id)) if f.disclosure != "hidden"][
                :RELEVANT_FACTS
            ]:
                take(fact)
    for fact in world.search(text, limit=SEARCH_HITS * 3):
        if not shown.issuperset(fact.about):
            take(fact)
        if len(facts) >= SEARCH_HITS + RELEVANT_FACTS * 2:
            break
    return facts
