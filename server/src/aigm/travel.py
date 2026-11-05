"""How long it takes to get from one place to another (docs/TIME.md 5.3 to 5.6).

Places are the nodes of a graph and routes its edges (`World.routes`), with the containment tree (`parent`) beside it. A
place with no route of its own is lifted to the nearest ancestor that has one; where no recorded path joins two places the
distance is an estimate from their scales and where they sit in the tree. Pure functions of a world: no clock, no model."""

import heapq
from collections.abc import Callable
from dataclasses import dataclass, field

from aigm.world.model import Route, World
from aigm.world.text import normalize_text

SCALE_RANK = {"room": 0, "site": 1, "settlement": 2, "region": 3}

# The estimates, in minutes (docs/TIME.md 5.6). Tuned after play tests.
ROOMS_OF_A_SITE = 5
SITES_IN_A_SETTLEMENT = 20
ENDPOINT_DEPTH = 5  # added for each end that lies deeper than a direct part of the shared place
PLACES_IN_A_REGION = 6 * 60
ACROSS_REGIONS = 2 * 24 * 60
UNRELATED = {"room": 30, "site": 30, "settlement": 6 * 60, "region": 24 * 60}  # no shared ancestor: by the larger place
INSIDE = {"room": 5, "site": 15, "settlement": 6 * 60, "region": 2 * 24 * 60}  # a place and one that lies within it

PACES = ("normal", "fast", "instant")
FAST_FACTOR = 0.5


def scale_of(world: World, place: str) -> str:
    """A place's scale: the recorded one, else read from what the world holds, from the top down (docs/TIME.md 5.6): what
    lies in a room is a room, what lies in a site is a room, what lies in a settlement is a site (a gate, a square, a
    building, which cannot be a settlement itself), and under a region a place is a region if it holds a settlement, a
    settlement if it looks like one (the curator's own test), and a site otherwise."""
    ent = world.entities[place]
    if ent.scale:
        return ent.scale
    parent_scale = scale_of(world, ent.parent) if ent.parent else None
    if parent_scale in ("room", "site"):
        return "room"
    if parent_scale == "settlement":
        return "site"
    if _holds_settlement(world, place):
        return "region"
    return "settlement" if _settlement_like(world, place) else "site"


def _holds_settlement(world: World, place: str) -> bool:
    """Is a settlement anywhere inside it?"""
    for kid in world.children(place):
        if kid.scale in ("settlement", "region") or _settlement_like(world, kid.id) or _holds_settlement(world, kid.id):
            return True
    return False


def _settlement_like(world: World, place: str) -> bool:
    """The curator's own test for a settlement (world/passes.py `checklist`): settlement-only facts, or three parts."""
    settlement_only = {"layout", "leaders", "economy", "notable_places", "tensions"}
    return bool(world.coverage(place) & settlement_only) or len(world.children(place)) >= 3


def _chain(world: World, place: str) -> list[str]:
    return [place, *(p.id for p in world.parent_chain(place))]


def shared_ancestor(world: World, a: str, b: str) -> str | None:
    """The nearest place that contains (or is) both."""
    above_b = set(_chain(world, b))
    return next((p for p in _chain(world, a) if p in above_b), None)


def estimate(world: World, a: str, b: str) -> int:
    """Minutes between two places with no recorded way, from their scales and the tree."""
    if a == b:
        return 0
    common = shared_ancestor(world, a, b)
    if common in (a, b):  # one lies inside the other
        inner = b if common == a else a
        return INSIDE[scale_of(world, inner)]
    if common is None:
        return UNRELATED[max(scale_of(world, a), scale_of(world, b), key=SCALE_RANK.__getitem__)]
    kind = scale_of(world, common)
    deeper = sum(1 for end in (a, b) if world.entities[end].parent != common)
    if kind == "region" and any(scale_of(world, end) == "region" for end in (a, b)):
        return ACROSS_REGIONS
    if kind == "region":
        return PLACES_IN_A_REGION + ENDPOINT_DEPTH * 2 * deeper
    if kind == "settlement":
        return SITES_IN_A_SETTLEMENT + ENDPOINT_DEPTH * deeper
    return ROOMS_OF_A_SITE


def shortest_path(
    world: World, src: str, usable: Callable[[Route], bool] = lambda r: True
) -> tuple[dict[str, int], dict[str, tuple[str, Route]]]:
    """Dijkstra over the routes from `src`: the minutes to every place that can be reached, and how (the place before it
    and the route used)."""
    dist: dict[str, int] = {src: 0}
    came: dict[str, tuple[str, Route]] = {}
    queue = [(0, src)]
    while queue:
        d, place = heapq.heappop(queue)
        if d > dist.get(place, d):
            continue
        for route in world.routes_of(place):
            if not usable(route):
                continue
            other = route.other(place)
            nd = d + route.minutes
            if nd < dist.get(other, nd + 1):
                dist[other] = nd
                came[other] = (place, route)
                heapq.heappush(queue, (nd, other))
    return dist, came


@dataclass
class Step:
    """One leg of a journey: arriving at `place` after `minutes`, by `route` (None for the short walk to or from a place
    that has no route of its own, and for an estimated journey)."""

    place: str
    minutes: int
    route: Route | None = None


@dataclass
class Journey:
    """The way between two places: the minutes it takes, the places passed (both ends included), the legs in order, and
    whether the time comes from recorded routes (`recorded`) or from the estimate."""

    minutes: int
    places: list[str] = field(default_factory=list)
    recorded: bool = False
    steps: list[Step] = field(default_factory=list)


def _anchors(world: World, place: str) -> list[tuple[str, int]]:
    """The place itself and its ancestors that have a route of their own, with the minutes to reach each."""
    out = []
    for p in _chain(world, place):
        if world.routes_of(p):
            out.append((p, 0 if p == place else estimate(world, place, p)))
    return out


def _journey(world: World, a: str, b: str, anchor_a: str, leg_a: int, path: list[Route], anchor_b: str, leg_b: int) -> Journey:
    steps: list[Step] = []
    here = anchor_a
    if anchor_a != a:
        steps.append(Step(anchor_a, leg_a))
    for route in path:
        here = route.other(here)
        steps.append(Step(here, route.minutes, route))
    if anchor_b != b:
        steps.append(Step(b, leg_b))
    return Journey(leg_a + sum(r.minutes for r in path) + leg_b, [a, *(st.place for st in steps)], True, steps)


def plan_ways(
    world: World, a: str, b: str, usable: Callable[[Route], bool] = lambda r: True, *, limit: int = 3, ratio: float = 2.0
) -> list[Journey]:
    """The recorded ways from `a` to `b`, shortest first, each a different run of routes: the shortest and up to
    `limit - 1` others that cost no more than `ratio` times as much (docs/TIME.md 5.4.1). Empty when no recorded path
    joins them. Places without routes of their own are lifted to the nearest ancestor that has them (5.3)."""
    found: list[tuple[int, tuple[str, ...], Journey]] = []
    for anchor_a, leg_a in _anchors(world, a):
        dist, _ = shortest_path(world, anchor_a, usable)
        for anchor_b, leg_b in _anchors(world, b):
            if anchor_a == anchor_b or anchor_b not in dist:
                continue
            cap = (dist[anchor_b] * ratio) + 1e-9
            for path in _simple_paths(world, anchor_a, anchor_b, usable, cap):
                found.append((leg_a + sum(r.minutes for r in path) + leg_b, tuple(r.id for r in path), _journey(world, a, b, anchor_a, leg_a, path, anchor_b, leg_b)))
    found.sort(key=lambda f: (f[0], f[1]))
    out: list[Journey] = []
    seen: set[tuple[str, ...]] = set()
    for _, key, journey in found:
        if key not in seen:
            seen.add(key)
            out.append(journey)
        if len(out) >= limit:
            break
    return out


def _simple_paths(world: World, src: str, dst: str, usable: Callable[[Route], bool], cap: float, max_hops: int = 8) -> list[list[Route]]:
    """Every run of routes from `src` to `dst` that visits no place twice and costs at most `cap` minutes."""
    out: list[list[Route]] = []

    def walk(place: str, path: list[Route], seen: set[str], cost: int) -> None:
        if place == dst:
            out.append(list(path))
            return
        if len(path) >= max_hops:
            return
        for route in world.routes_of(place):
            other = route.other(place)
            if other in seen or not usable(route) or cost + route.minutes > cap:
                continue
            path.append(route)
            walk(other, path, seen | {other}, cost + route.minutes)
            path.pop()

    walk(src, [], {src}, 0)
    return out


def plan_journey(world: World, a: str, b: str, usable: Callable[[Route], bool] = lambda r: True) -> Journey:
    """The way from `a` to `b` (docs/TIME.md 5.3): the shortest recorded path between the places, or their nearest
    ancestors that have routes, with the short legs at either end; else the estimate."""
    if a == b:
        return Journey(0, [a], True)
    ways = plan_ways(world, a, b, usable, limit=1, ratio=1.0)
    if ways:
        return ways[0]
    minutes = estimate(world, a, b)
    return Journey(minutes, [a, b], False, [Step(b, minutes)])


def paced(minutes: int, pace: str) -> int:
    """The minutes a journey takes at a pace: `fast` halves it (at least a minute), `instant` is none."""
    if pace == "instant":
        return 0
    if pace == "fast" and minutes:
        return max(1, round(minutes * FAST_FACTOR))
    return minutes


# ---- the walk (docs/TIME.md 5.4) ---------------------------------------------------------------------------------------

CHOICE_MIN_MINUTES = 5  # a way this short is never worth asking the player about


def has_been(world: World, place: str) -> bool:
    """The party has been to the place, or to somewhere inside it (so also the buildings and towns it is standing in)."""
    ent = world.entities[place]
    return ent.visited or any(has_been(world, c.id) for c in world.children(place))


def _known(world: World, place: str) -> bool:
    ent = world.entities[place]
    return ent.visited or ent.discovered or has_been(world, place)


def _is_hidden(route: Route) -> bool:
    return route.block is not None and route.block.kind == "hidden"


@dataclass
class Move:
    """What a request to go somewhere comes to. `kind` is `walk` (a recorded way: the party ends at `stop` after
    `minutes`, having `passed` the places between, short of the destination if `reason` is `unexplored` or `blocked`),
    `estimate` (no recorded way: the whole trip, as the estimate), `choose` (several ways: `options`) or `none` (no
    way the party can find)."""

    kind: str
    stop: str
    minutes: int = 0
    passed: list[str] = field(default_factory=list)
    reason: str | None = None
    blocker: Route | None = None
    next_place: str | None = None
    options: list[Journey] = field(default_factory=list)


def way_text(world: World, journey: Journey) -> str:
    """A way in the words of the places and routes on it: `The Great Hall (down the main stair)`."""
    return " then ".join(
        world.entities[st.place].name + (f" ({st.route.how})" if st.route and st.route.how else "")
        for st in journey.steps
    )


def _pick(world: World, ways: list[Journey], via: str | None) -> Journey | None:
    """The way the GM named, as a place on it or words from the route's description."""
    if not via or not via.strip():
        return None
    wanted = normalize_text(via)
    wanted_place = world.resolve(via)
    for way in ways:
        if wanted_place is not None and any(st.place == wanted_place.id for st in way.steps[:-1]):
            return way
        if any(st.route and wanted and wanted in normalize_text(st.route.how) for st in way.steps):
            return way
    return None


def _walk(world: World, journey: Journey, origin: str, dest: str, guided: bool) -> Move:
    minutes, here, passed = 0, origin, []
    for i, st in enumerate(journey.steps):
        if st.route and st.route.block is not None:
            return Move("walk", here, minutes, passed, "blocked", st.route, st.place)
        minutes += st.minutes
        here = st.place
        passed.append(here)
        if here != dest and not guided and not has_been(world, here):
            ahead = journey.steps[i + 1].place if i + 1 < len(journey.steps) else dest
            return Move("walk", here, minutes, passed, "unexplored", None, ahead)
    return Move("walk", dest, minutes, passed)


def plan_move(world: World, origin: str, dest: str, *, via: str | None = None, guided: bool = False) -> Move:
    """Where the party ends up when it sets out for `dest`, and what that costs (docs/TIME.md 5.4)."""

    def open_way(route: Route) -> bool:
        return route.block is None

    def known_way(route: Route) -> bool:
        return open_way(route) and all(p == dest or _known(world, p) for p in (route.a, route.b))

    ways = plan_ways(world, origin, dest, known_way)
    if ways:
        viable = ways if len(ways) > 1 and ways[0].minutes > CHOICE_MIN_MINUTES else ways[:1]
        chosen = viable[0]
        if len(viable) > 1:
            picked = _pick(world, viable, via)
            if picked is None:
                return Move("choose", origin, options=viable)
            chosen = picked
        return _walk(world, chosen, origin, dest, guided)
    for usable in (lambda r: open_way(r), lambda r: not _is_hidden(r)):  # then through the unknown, then to a block
        found = plan_ways(world, origin, dest, usable, limit=1, ratio=1.0)
        if found:
            return _walk(world, found[0], origin, dest, guided)
    if plan_ways(world, origin, dest, limit=1, ratio=1.0):
        return Move("none", origin)  # the only way there is one the party cannot see
    minutes = estimate(world, origin, dest)
    return Move("estimate", dest, minutes, [dest])
