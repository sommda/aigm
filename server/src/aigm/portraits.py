"""Character portraits: the record, the image files and the background pipeline (docs/PORTRAITS.md 6 and 8).

A `Portrait` is data about a picture, kept beside the character's Look (`GameState.portraits` for the party). The bytes
live in a shared library folder named by what produced them, so a restored or repeated game finds its picture instead
of paying again. `PortraitService` decides who needs a picture, builds the prompt, calls the generator and returns
the new records; the session applies them between turns, as it does for Looks. Nothing here raises into a turn."""

import asyncio
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aigm import art
from aigm.art import Style
from aigm.errors import CorruptSave
from aigm.images import MODERATION, QUOTA, Image, ImageError, Images
from aigm.looks import Look

log = logging.getLogger(__name__)

REGEN_TURNS = 20  # a picture is replaced for a revised Look at most this often (docs/PORTRAITS.md 8.4)
RETRY_TURNS = 2  # turns to wait before trying again after a failure
MAX_FAILED_ATTEMPTS = 3
MAX_PER_SWEEP = 4
MAX_CONCURRENT = 2
FILE_NAME = re.compile(r"^p_[0-9a-f]{16}\.(?:png|webp|jpg)$")
CONTENT_TYPES = {"png": "image/png", "webp": "image/webp", "jpg": "image/jpeg"}


@dataclass
class Failure:
    """The last failed attempt at a target: this Look revision in this style."""

    reason: str  # moderation | unavailable | bad_reply
    attempts: int
    turn: int
    rev: int
    style: str

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "attempts": self.attempts, "turn": self.turn, "rev": self.rev, "style": self.style}


def _int(value: Any, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CorruptSave(f"{what} must be a non-negative whole number")
    return value


@dataclass
class Portrait:
    """`image` is the file name in the library (None when only a failure is recorded). `look_rev` and `style` say what
    the picture was made from; a Look that has moved on makes it stale, but it stays shown until a new one is ready."""

    image: str | None
    style: str
    look_rev: int
    model: str = ""
    turn: int = 0  # when it was made
    failure: Failure | None = None

    @property
    def ready(self) -> bool:
        return self.image is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "image": self.image, "style": self.style, "look_rev": self.look_rev, "model": self.model, "turn": self.turn,
            "failure": self.failure.to_dict() if self.failure else None,
        }  # fmt: skip

    @classmethod
    def from_dict(cls, data: Any) -> "Portrait":
        if not isinstance(data, dict):
            raise CorruptSave("a portrait must be an object")
        image = data.get("image")
        if image is not None and not (isinstance(image, str) and FILE_NAME.match(image)):
            raise CorruptSave(f"bad portrait image name {image!r}")
        style = data.get("style")
        if not isinstance(style, str) or style not in art.BY_ID:
            raise CorruptSave(f"unknown portrait style {style!r}")
        failure = None
        if data.get("failure") is not None:
            f = data["failure"]
            if not isinstance(f, dict) or not isinstance(f.get("reason"), str) or f.get("style") not in art.BY_ID:
                raise CorruptSave("a portrait failure must name a reason and a style")
            failure = Failure(f["reason"], _int(f.get("attempts"), "attempts"), _int(f.get("turn"), "turn"),
                              _int(f.get("rev"), "rev"), f["style"])  # fmt: skip
        model = data.get("model", "")
        if not isinstance(model, str):
            raise CorruptSave("a portrait's model must be text")
        return cls(image, style, _int(data.get("look_rev"), "look_rev"), model, _int(data.get("turn", 0), "turn"), failure)

    def copy(self) -> "Portrait":
        return Portrait.from_dict(self.to_dict())


def read_portraits(raw: Any) -> dict[str, Portrait]:
    """The party's portraits in a save file; a file from before portraits existed has none."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CorruptSave("portraits must be an object")
    return {str(name): Portrait.from_dict(data) for name, data in raw.items()}


# ---- the image files ---------------------------------------------------------------------------


class ImageStore:
    """The library folder: `<id>.<ext>` and a `<id>.json` beside it holding the prompt and what it was made from."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def valid(name: str) -> bool:
        return bool(FILE_NAME.match(name))

    def path(self, name: str) -> Path | None:
        """The file for a name, or None if the name is not one of ours or the file is not there."""
        if not self.valid(name):
            return None
        path = self.root / name
        return path if path.is_file() else None

    def has(self, name: str | None) -> bool:
        return name is not None and self.path(name) is not None

    def find(self, image_id: str) -> str | None:
        """The stored file name for an id, whatever its extension."""
        for ext in CONTENT_TYPES:
            if (self.root / f"{image_id}.{ext}").is_file():
                return f"{image_id}.{ext}"
        return None

    def save(self, image_id: str, image: Image, meta: dict[str, Any]) -> str:
        """Write the picture and its notes atomically; the notes first, so a picture never lacks them."""
        self.root.mkdir(parents=True, exist_ok=True)
        name = f"{image_id}.{image.ext}"
        self._write(self.root / f"{image_id}.json", json.dumps(meta, indent=2).encode())
        self._write(self.root / name, image.data)
        return name

    def _write(self, target: Path, data: bytes) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _visible_people(world: Any, *, any_look: bool = False) -> list[Any]:
    """The NPCs the player can see in the compendium that have a Look, in the order they are given pictures: those in
    the scene first, then the rest newest first. `any_look` also lists those with a picture but no Look."""
    from aigm.compendium import _visible  # not at the top: the compendium imports the world, which imports this module

    people = [
        e for e in world.entities.values()
        if e.kind == "npc" and (e.look or (any_look and e.portrait)) and _visible(world, e.id)
    ]  # fmt: skip
    present = {eid: i for i, eid in enumerate(world.scene.present)}
    return sorted(people, key=lambda e: (e.id not in present, present.get(e.id, 0), -int(e.id[1:])))


# ---- who needs a picture -----------------------------------------------------------------------


def is_due(look: Look, portrait: Portrait | None, style: Style, turn: int, store: ImageStore) -> bool:
    """Does this character need a (new) picture now? (docs/PORTRAITS.md 8.1, 8.3 and 8.4)"""
    shown = portrait is not None and store.has(portrait.image)
    if shown and portrait.look_rev == look.rev and portrait.style == style.id:
        return False  # current
    failure = portrait.failure if portrait else None
    if failure and failure.rev == look.rev and failure.style == style.id:  # this very target already failed
        if failure.reason == MODERATION or failure.attempts >= MAX_FAILED_ATTEMPTS:
            return False
        return turn >= failure.turn + RETRY_TURNS
    if shown:  # stale: the Look moved on or the style changed; replaced, but not often
        return turn >= portrait.turn + REGEN_TURNS
    return True


@dataclass
class Job:
    name: str
    look: Look
    old: Portrait | None
    names: list[str]  # the name and aliases to take out of the text
    entity: str | None = None  # the NPC's entity id; None for a party member

    @property
    def key(self) -> str:
        """What the result is filed under: a party member's name or an NPC's entity id."""
        return self.entity or self.name


class PortraitService:
    def __init__(self, images: Images, store: ImageStore, size: str, quality: str | None) -> None:
        self.images = images
        self.store = store
        self.size = size
        self.quality = quality
        self.disabled = False  # set after a billing or key failure: stop trying until the server restarts

    def due_jobs(self, state: Any) -> list[Job]:
        """Who needs a picture, at most one sweep's worth: the party in order, then the people the player can see who
        are in the scene, then the others they can see, newest first (docs/PORTRAITS.md 8.1)."""
        style = art.resolve_style(state.art_style, state.ruleset)
        if style is None or self.disabled:
            return []
        jobs = []
        for name in state.party_names:
            look = state.looks.get(name)
            if look is not None and is_due(look, state.portraits.get(name), style, state.turn, self.store):
                jobs.append(Job(name, look, state.portraits.get(name), [name]))
        for ent in _visible_people(state.world):
            if is_due(ent.look, ent.portrait, style, state.turn, self.store):
                jobs.append(Job(ent.name, ent.look, ent.portrait, ent.names(), ent.id))
        return jobs[:MAX_PER_SWEEP]

    def view(self, session: Any, name: str) -> dict[str, Any] | None:
        """What a client is told about a party member's portrait (docs/PORTRAITS.md 9): `ready` with its address,
        `pending` while one is on the way, or None. A character whose retry is waiting is not pending."""
        state = session.state
        found = state.find_hero(name)
        if found is None:
            return None
        return self._view(session, state.looks.get(found), state.portraits.get(found))

    def view_entity(self, session: Any, entity_id: str) -> dict[str, Any] | None:
        """The same for an NPC, who must already be visible to the player (the caller has checked)."""
        ent = session.state.world.entities.get(entity_id)
        if ent is None or ent.kind != "npc":
            return None
        return self._view(session, ent.look, ent.portrait)

    def _view(self, session: Any, look: Look | None, record: Portrait | None) -> dict[str, Any] | None:
        state = session.state
        style = art.resolve_style(state.art_style, state.ruleset)
        if style is None:
            return None
        if record is not None and self.store.has(record.image):
            url = f"/portraits/{record.image}?session_id={quote(session.id, safe='')}"
            return {"state": "ready", "url": url, "style": record.style}
        if look is not None and not self.disabled and is_due(look, record, style, state.turn, self.store):
            return {"state": "pending", "style": style.id}
        return None

    def shown(self, session: Any, file: str) -> Path | None:
        """The file of an image this session may show its player: a party member's current portrait, or that of a
        person the player has met (the compendium's rule), or None."""
        state = session.state
        records = [*state.portraits.values(), *(e.portrait for e in _visible_people(state.world, any_look=True) if e.portrait)]
        if not any(record.image == file for record in records):
            return None
        return self.store.path(file)

    def due(self, session: Any) -> bool:
        """Is anyone waiting for a picture, and is no sweep already running? Cheap: it only reads records."""
        state = session.state
        return state.phase.value == "adventure" and not session.imaging and bool(self.due_jobs(state))

    async def run_if_due(self, session: Any) -> bool:
        """Make the missing pictures in the background, after the turn. The results wait for the session to be idle
        and are applied with the other pending work. Never raises."""
        if not self.due(session):
            return False
        state, generation = session.state, session.generation
        style = art.resolve_style(state.art_style, state.ruleset)
        jobs, turn = self.due_jobs(state), state.turn
        session.imaging = True
        try:
            made = await self.run(jobs, style, turn)
        except Exception:  # run() already guards each picture; this is the last net
            log.exception("portrait sweep failed")
            return False
        finally:
            session.imaging = False
        if session.generation != generation or not made:
            return False
        from aigm.world.ops import SetPortrait  # not at the top: the world imports this module

        people = {job.key for job in jobs if job.entity}
        session.pending_portraits.append({k: v for k, v in made.items() if k not in people})
        if people & made.keys():
            session.pending.append([SetPortrait(k, v) for k, v in made.items() if k in people])
        session.drain_pending()
        return True

    async def run(self, jobs: list[Job], style: Style, turn: int) -> dict[str, Portrait]:
        """Make the pictures, two at a time. Returns the new record of each character it got an answer for, by `Job.key`."""
        gate = asyncio.Semaphore(MAX_CONCURRENT)

        async def one(job: Job) -> tuple[str, Portrait | None]:
            async with gate:
                if self.disabled:
                    return job.key, None
                try:
                    return job.key, await self._make(job, style, turn)
                except Exception:
                    log.exception("making the portrait of %s failed", job.name)
                    return job.key, None

        return {name: rec for name, rec in await asyncio.gather(*(one(j) for j in jobs)) if rec is not None}

    async def _make(self, job: Job, style: Style, turn: int) -> Portrait | None:
        prompt = art.build_prompt(job.look, style, job.names)
        model = self.images.model
        image_id = art.image_id(model, self.size, style, prompt, self.quality)
        stored = self.store.find(image_id)
        if stored:  # the same picture was made before (a restored game, a repeated Look)
            return Portrait(stored, style.id, job.look.rev, model, turn)
        try:
            image = await self._generate(prompt, job, style)
        except ImageError as exc:
            if exc.kind == QUOTA:
                self.disabled = True
                log.error("portraits are off until the server restarts: %s", exc)
                return None
            log.warning("portrait of %s: %s (%s)", job.name, exc, exc.kind)
            return self._failed(job, style, turn, exc.kind)
        meta = {
            "prompt": prompt, "model": image.model, "style": style.id, "size": self.size, "quality": self.quality,
            "look_summary": job.look.summary, "look_search_text": job.look.search_text(), "look_rev": job.look.rev,
            "usage": image.usage, "turn": turn,
        }  # fmt: skip
        try:
            name = self.store.save(image_id, image, meta)
        except OSError:
            log.exception("could not store the portrait of %s", job.name)
            return self._failed(job, style, turn, "unavailable")
        return Portrait(name, style.id, job.look.rev, image.model, turn)

    async def _generate(self, prompt: str, job: Job, style: Style) -> Image:
        try:
            return await self.images.generate(prompt)
        except ImageError as exc:
            if exc.kind != MODERATION:
                raise
        # Refused: one more try with only the tags and the Look's first sentence (docs/PORTRAITS.md 8.3).
        return await self.images.generate(art.build_prompt(job.look, style, job.names, softened=True))

    @staticmethod
    def _failed(job: Job, style: Style, turn: int, reason: str) -> Portrait:
        """The old record (its picture stays shown) with the failure noted; a new one if there was none."""
        old = job.old
        before = old.failure if old and old.failure and (old.failure.rev, old.failure.style) == (job.look.rev, style.id) else None
        failure = Failure(reason, (before.attempts if before else 0) + 1, turn, job.look.rev, style.id)
        if old is None:
            return Portrait(None, style.id, job.look.rev, "", turn, failure)
        record = old.copy()
        record.failure = failure
        return record
