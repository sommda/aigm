"""A human-readable view of a world, for debugging (docs/WORLD.md 2.6).

The server keeps one such file per session next to the saves and rewrites it whenever the world
changes. It is never read back. The same view can be rendered from a save file after a game has
ended:  uv run python -m aigm.world.dump SAVE_NAME [--known-only]"""

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from aigm.errors import CorruptSave
from aigm.world.model import Fact, World

log = logging.getLogger(__name__)


def _stamp(fact: Fact) -> str:
    return f"d{fact.created_at.day}h{fact.created_at.hour}"


def fact_line(world: World, fact: Fact) -> str:
    """`[hidden|approach|f0042 d3h14] The Harrow Mine lies ...` plus any other entities involved."""
    head = f"{fact.disclosure}|{fact.aspect or '-'}|{fact.id} {_stamp(fact)}"
    if fact.superseded_by:
        head += f" -> {fact.superseded_by}"
    window = []
    if fact.from_time:
        window.append(f"from d{fact.from_time.day}h{fact.from_time.hour}")
    if fact.until_time:
        window.append(f"until d{fact.until_time.day}h{fact.until_time.hour}")
    if window:
        head += " " + " ".join(window)
    line = f"[{head}] {fact.text}"
    others = [world.entities[e].name for e in fact.about[1:]]
    return line + (f"  (also: {', '.join(others)})" if others else "")


def dump_world(world: World, *, known_only: bool = False, session_id: str | None = None) -> dict[str, Any]:
    """The world as a dictionary with a fixed key order, grouped by entity, one fact per string."""
    scene = world.scene
    out: dict[str, Any] = {}
    if session_id is not None:
        out["session"] = session_id
    out["time"] = str(world.time)
    out["scene"] = {
        "location": world.entities[scene.location].name if scene.location else None,
        "present": [world.entities[e].name for e in scene.present],
    }
    out["processed_through"] = world.processed_through
    out["counts"] = world.counts()
    if known_only:
        out["view"] = "known facts only (what the player has been told)"
    if world.corrections and not known_only:
        out["corrections"] = [c["text"] for c in world.corrections]
    entities = []
    for ent in world.entities.values():
        facts = [f for f in world.facts.values() if f.subject == ent.id]
        shown = [f for f in facts if f.active and (not known_only or f.disclosure == "known")]
        replaced = [f for f in facts if not f.active and not known_only]
        if known_only and not shown:
            continue
        entry: dict[str, Any] = {"name": ent.name, "id": ent.id, "kind": ent.kind}
        if ent.aliases:
            entry["aliases"] = list(ent.aliases)
        chain = [p.name for p in world.parent_chain(ent.id)]
        if chain:
            entry["in"] = chain
        entry["discovered"] = ent.discovered
        entry["facts"] = [fact_line(world, f) for f in shown]
        if replaced:
            entry["superseded"] = [fact_line(world, f) for f in replaced]
        entities.append(entry)
    out["entities"] = entities
    return out


def render(world: World, *, known_only: bool = False, session_id: str | None = None) -> str:
    return json.dumps(dump_world(world, known_only=known_only, session_id=session_id), indent=2, ensure_ascii=False) + "\n"


def write_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class WorldDumper:
    """Keeps `{dir}/{session_id}.world.json` in step with each session's world."""

    def __init__(self, directory: Path, enabled: bool = True) -> None:
        self.dir = Path(directory)
        self.enabled = enabled
        self._stamps: dict[str, tuple[int, int]] = {}  # session id -> (generation, world version) last written

    def path(self, session_id: str) -> Path:
        return self.dir / f"{session_id}.world.json"

    async def update(self, session: Any) -> bool:
        """Rewrite the file if the world changed since it was last written. Returns whether it wrote.
        An empty world (Session 0) has no file. A failure to write is logged, never raised: the dump
        is a debugging aid and must not affect the game."""
        if not self.enabled:
            return False
        world: World = session.state.world
        stamp = (session.generation, world.version)
        if self._stamps.get(session.id) == stamp:
            return False
        try:
            if world.is_empty:
                await asyncio.to_thread(self.path(session.id).unlink, True)
            else:
                text = render(world, session_id=session.id)
                await asyncio.to_thread(write_atomically, self.path(session.id), text)
        except OSError:
            log.exception("could not write the world dump")
            return False
        self._stamps[session.id] = stamp
        return True

    async def remove(self, session_id: str) -> None:
        self._stamps.pop(session_id, None)
        if self.enabled:
            await asyncio.to_thread(self.path(session_id).unlink, True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aigm.world.dump", description="Print the world in a saved game.")
    parser.add_argument("name", help="the save name (a file in the save directory, without .json) or a path")
    parser.add_argument("--known-only", action="store_true", help="show only what the player has been told")
    parser.add_argument("--save-dir", type=Path, help="save directory (default: AIGM_SAVE_DIR or ./saves)")
    args = parser.parse_args(argv)
    path = Path(args.name)
    if not path.suffix:
        from aigm.config import Settings

        path = (args.save_dir or Settings().save_dir) / f"{args.name}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        world = World.from_dict(data.get("world"))
    except FileNotFoundError:
        print(f"No such save: {path}", file=sys.stderr)
        return 1
    except (OSError, ValueError, CorruptSave, AttributeError) as exc:
        print(f"Cannot read {path}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(render(world, known_only=args.known_only, session_id=None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
