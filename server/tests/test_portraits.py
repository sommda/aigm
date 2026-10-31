"""Portraits: the record, the image library and the background pipeline (docs/PORTRAITS.md 6 and 8)."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from aigm import art, images
from aigm.app import create_app
from aigm.config import Settings
from aigm.errors import CorruptSave
from aigm.images import FakeImages, Image, ImageError
from aigm.portraits import (
    MAX_CONCURRENT, MAX_FAILED_ATTEMPTS, MAX_PER_SWEEP, REGEN_TURNS, RETRY_TURNS, Failure, ImageStore, Portrait,
    PortraitService, is_due, read_portraits,
)  # fmt: skip
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from tests.conftest import chat
from tests.test_looks import make_look

MODEL = FakeImages.model
INK, ANIME = art.BY_ID["ink"], art.BY_ID["anime"]
NAMES = ["Toby Reed", "Wren Tallow", "Garrick Stone", "Ilsa Moor", "Bram Ash", "Dov Quill"]


def look_of(name: str, rev: int = 1):
    """A Look whose text differs between people and revisions (names are scrubbed from prompts, so they would not)."""
    look = make_look(name, rev=rev)
    look.description += f" A scarf of color number {NAMES.index(name) if name in NAMES else 0} and revision {rev}."
    return look


def party_session(names=("Toby Reed",), turn=1, **state) -> Session:
    session = Session("s")
    state.setdefault("art_style", "ink")
    session.state = GameState(
        Phase.ADVENTURE, {"setting": "A river town.", "party": [{"name": n, "sheet": "Rogue."} for n in names]}, **state
    )
    session.state.turn = turn
    for n in names:
        session.state.looks[n] = look_of(n)
    return session


def service(tmp_path, fake=None, **kw) -> tuple[PortraitService, FakeImages]:
    fake = fake or FakeImages()
    return PortraitService(fake, ImageStore(tmp_path / "images"), "1024x1024", None, **kw), fake


def record(name="p_0123456789abcdef.png", rev=1, style="ink", turn=1, failure=None) -> Portrait:
    return Portrait(name, style, rev, MODEL, turn, failure)


# ---- the record --------------------------------------------------------------------------------


def test_a_portrait_round_trips_with_and_without_a_failure():
    plain = record()
    failed = Portrait(None, "ink", 2, "", 4, Failure("unavailable", 2, 4, 2, "ink"))
    for p in (plain, failed):
        assert Portrait.from_dict(json.loads(json.dumps(p.to_dict()))).to_dict() == p.to_dict()
    assert plain.ready and not failed.ready


@pytest.mark.parametrize("bad", [
    "text", {"image": "../etc/passwd", "style": "ink", "look_rev": 1}, {"image": "p_x.png", "style": "ink", "look_rev": 1},
    {"image": None, "style": "nope", "look_rev": 1}, {"image": None, "style": "ink", "look_rev": -1},
    {"image": None, "style": "ink", "look_rev": True}, {"image": None, "style": "ink", "look_rev": 1, "failure": 5},
    {"image": None, "style": "ink", "look_rev": 1, "failure": {"reason": "x", "style": "nope"}},
])
def test_a_bad_portrait_is_a_corrupt_save(bad):
    with pytest.raises(CorruptSave):
        Portrait.from_dict(bad)


def test_a_game_without_portraits_reads_as_none_and_a_non_object_is_rejected():
    assert read_portraits(None) == {}
    with pytest.raises(CorruptSave):
        read_portraits([])


def test_the_game_state_saves_portraits_and_the_art_style_and_copies_them():
    state = GameState(Phase.ADVENTURE, {"party": [{"name": "A"}]}, art_style="anime", portraits={"A": record()})
    again = GameState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert again.art_style == "anime" and again.portraits["A"].image == "p_0123456789abcdef.png"
    copy = state.copy()
    copy.portraits["A"].turn = 99
    assert state.portraits["A"].turn == 1 and copy.art_style == "anime"
    assert GameState.from_dict({"phase": "adventure", "campaign": None}).portraits == {}  # an older save
    with pytest.raises(CorruptSave):
        GameState.from_dict({**state.to_dict(), "art_style": "bogus"})


# ---- the library -------------------------------------------------------------------------------


def test_the_store_writes_a_picture_and_its_notes_and_finds_it_again(tmp_path):
    store = ImageStore(tmp_path / "images")
    img = Image(b"\x89PNG\r\n\x1a\n...", "png", "m")
    name = store.save("p_0123456789abcdef", img, {"prompt": "x"})
    assert name == "p_0123456789abcdef.png" and store.has(name) and store.find("p_0123456789abcdef") == name
    assert store.path(name).read_bytes() == img.data
    assert json.loads((tmp_path / "images" / "p_0123456789abcdef.json").read_text()) == {"prompt": "x"}
    assert not list((tmp_path / "images").glob(".tmp-*"))
    assert store.find("p_ffffffffffffffff") is None and not store.has(None)


@pytest.mark.parametrize("name", ["../x.png", "p_1.png", "p_0123456789abcdef.gif", "p_0123456789abcdef.png/..", ""])
def test_the_store_serves_only_its_own_names(tmp_path, name):
    (tmp_path / "images").mkdir()
    assert ImageStore(tmp_path / "images").path(name) is None and not ImageStore.valid(name)


# ---- who is due --------------------------------------------------------------------------------


def test_who_is_due(tmp_path):
    store = ImageStore(tmp_path / "images")
    name = store.save("p_0123456789abcdef", Image(b"x", "png", "m"), {})
    look = make_look("Toby Reed")
    current = record(name, rev=look.rev)
    assert is_due(look, None, INK, 5, store)  # nothing yet
    assert not is_due(look, current, INK, 5, store)  # current
    stale_style = record(name, rev=look.rev, style="anime")
    assert not is_due(look, stale_style, INK, current.turn + REGEN_TURNS - 1, store)  # too soon to replace
    assert is_due(look, stale_style, INK, current.turn + REGEN_TURNS, store)
    moved = record(name, rev=look.rev - 1 if look.rev > 1 else 0, turn=10)
    assert is_due(look, moved, INK, 10 + REGEN_TURNS, store) and not is_due(look, moved, INK, 11, store)
    assert is_due(look, record("p_ffffffffffffffff.png", rev=look.rev), INK, 5, store)  # its file is gone


def test_failures_back_off_and_moderation_and_too_many_stop_it(tmp_path):
    store = ImageStore(tmp_path / "images")
    look = make_look("Toby Reed")

    def failed(reason, attempts, turn=10):
        return Portrait(None, "ink", look.rev, "", turn, Failure(reason, attempts, turn, look.rev, "ink"))

    assert not is_due(look, failed("unavailable", 1), INK, 10 + RETRY_TURNS - 1, store)
    assert is_due(look, failed("unavailable", 1), INK, 10 + RETRY_TURNS, store)
    assert not is_due(look, failed("unavailable", MAX_FAILED_ATTEMPTS), INK, 999, store)
    assert not is_due(look, failed("moderation", 1), INK, 999, store)
    revised = look.copy()
    revised.rev += 1  # a new Look is a new target: the failure does not count against it
    assert is_due(revised, failed("moderation", 1), INK, 11, store)


# ---- making pictures ---------------------------------------------------------------------------


async def make(svc, session, style=INK):
    jobs = svc.due_jobs(session.state)
    return jobs, await svc.run(jobs, style, session.state.turn)


async def test_a_picture_is_made_stored_and_recorded_without_the_name(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session()
    jobs, made = await make(svc, session)
    rec = made["Toby Reed"]
    assert rec.ready and rec.style == "ink" and rec.look_rev == 1 and rec.model == MODEL and rec.failure is None
    assert svc.store.has(rec.image) and "Toby" not in fake.prompts[0] and "Reed" not in fake.prompts[0]
    notes = json.loads((svc.store.root / rec.image.replace(".png", ".json")).read_text())
    assert notes["prompt"] == fake.prompts[0] and notes["look_rev"] == 1 and notes["look_search_text"]


async def test_the_same_inputs_reuse_the_stored_picture_and_cost_nothing(tmp_path):
    svc, fake = service(tmp_path)
    first = (await make(svc, party_session()))[1]["Toby Reed"]
    second = (await make(svc, party_session()))[1]["Toby Reed"]
    assert second.image == first.image and len(fake.prompts) == 1


async def test_a_refusal_is_retried_once_with_a_softer_prompt(tmp_path):
    fake = FakeImages(fail=[ImageError(images.MODERATION, "no")])
    svc, _ = service(tmp_path, fake)
    made = (await make(svc, party_session()))[1]
    assert made["Toby Reed"].ready and len(fake.prompts) == 2 and len(fake.prompts[1]) < len(fake.prompts[0])


async def test_two_refusals_record_a_moderation_failure_that_is_not_retried(tmp_path):
    fake = FakeImages(fail=[ImageError(images.MODERATION, "no")] * 2)
    svc, _ = service(tmp_path, fake)
    session = party_session()
    rec = (await make(svc, session))[1]["Toby Reed"]
    assert not rec.ready and rec.failure.reason == images.MODERATION
    session.state.portraits["Toby Reed"] = rec
    session.state.turn += 100
    assert svc.due_jobs(session.state) == []


async def test_a_transient_failure_is_retried_later_and_counts_attempts(tmp_path):
    fake = FakeImages(fail=[ImageError(images.UNAVAILABLE, "down")] * 3)
    svc, _ = service(tmp_path, fake)
    session = party_session()
    for expected in (1, 2, 3):
        rec = (await make(svc, session))[1]["Toby Reed"]
        assert not rec.ready and rec.failure.attempts == expected
        session.state.portraits["Toby Reed"] = rec
        assert svc.due_jobs(session.state) == []  # waits
        session.state.turn += RETRY_TURNS
    assert svc.due_jobs(session.state) == []  # three attempts used


async def test_a_failed_replacement_keeps_the_old_picture(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session(turn=1)
    old = (await make(svc, session))[1]["Toby Reed"]
    session.state.portraits["Toby Reed"] = old
    session.state.looks["Toby Reed"] = look_of("Toby Reed", rev=2)
    session.state.turn = 1 + REGEN_TURNS
    fake.fail.append(ImageError(images.UNAVAILABLE, "down"))
    rec = (await make(svc, session))[1]["Toby Reed"]
    assert rec.image == old.image and rec.look_rev == 1 and rec.failure.rev == 2
    session.state.portraits["Toby Reed"] = rec
    session.state.turn += RETRY_TURNS
    new = (await make(svc, session))[1]["Toby Reed"]
    assert new.image != old.image and new.look_rev == 2 and new.failure is None


async def test_a_billing_failure_switches_portraits_off_without_a_record(tmp_path):
    fake = FakeImages(fail=[ImageError(images.QUOTA, "pay")])
    svc, _ = service(tmp_path, fake)
    session = party_session(("Toby Reed", "Wren Tallow"))
    made = (await make(svc, session))[1]
    assert made == {} and svc.disabled and svc.due_jobs(session.state) == []


async def test_a_surprise_error_is_swallowed_and_leaves_no_record(tmp_path):
    class Broken(FakeImages):
        async def generate(self, prompt, size=None):
            raise RuntimeError("bug")

    svc, _ = service(tmp_path, Broken())
    assert (await make(svc, party_session()))[1] == {}


def test_no_portraits_when_the_game_chose_none_and_the_default_follows_the_ruleset(tmp_path):
    svc, _ = service(tmp_path)
    assert svc.due_jobs(party_session(art_style=art.NO_PORTRAITS).state) == []
    assert len(svc.due_jobs(party_session(art_style="anime").state)) == 1


def test_a_sweep_takes_the_party_in_order_and_only_a_few(tmp_path):
    svc, _ = service(tmp_path)
    session = party_session(NAMES)
    assert [j.name for j in svc.due_jobs(session.state)] == NAMES[:MAX_PER_SWEEP]
    del session.state.looks[NAMES[0]]  # no Look yet: skipped
    assert [j.name for j in svc.due_jobs(session.state)] == NAMES[1 : MAX_PER_SWEEP + 1]


async def test_only_a_few_run_at_once(tmp_path):
    class Counting(FakeImages):
        active = peak = 0

        async def generate(self, prompt, size=None):
            Counting.active += 1
            Counting.peak = max(Counting.peak, Counting.active)
            await asyncio.sleep(0.02)
            Counting.active -= 1
            return await super().generate(prompt, size)

    svc, _ = service(tmp_path, Counting())
    made = (await make(svc, party_session(NAMES)))[1]
    assert len(made) == MAX_PER_SWEEP and Counting.peak == MAX_CONCURRENT


# ---- in a session ------------------------------------------------------------------------------


async def test_the_sweep_applies_its_results_and_then_goes_quiet(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session(("Toby Reed", "Wren Tallow"))
    assert svc.due(session) and await svc.run_if_due(session)
    assert sorted(session.state.portraits) == ["Toby Reed", "Wren Tallow"] and not session.imaging
    assert not svc.due(session) and not await svc.run_if_due(session) and len(fake.prompts) == 2


def test_nothing_is_due_in_session_zero_or_while_a_sweep_runs(tmp_path):
    svc, _ = service(tmp_path)
    zero = Session("z")
    assert not svc.due(zero)
    busy = party_session()
    busy.imaging = True
    assert not svc.due(busy)


async def test_results_for_a_game_that_was_replaced_are_dropped(tmp_path):
    session = party_session()

    class Replacing(FakeImages):
        async def generate(self, prompt, size=None):
            session.reset_world_work()
            return await super().generate(prompt, size)

    svc, _ = service(tmp_path, Replacing())
    assert not await svc.run_if_due(session)
    assert session.state.portraits == {} and session.pending_portraits == []


def test_waiting_portraits_are_applied_when_idle_and_only_to_party_members():
    session = party_session()
    session.pending_portraits.append({"Toby Reed": record(), "Stranger": record()})
    session.busy = True
    session.drain_pending()
    assert session.state.portraits == {}  # not during a turn
    session.busy = False
    session.drain_pending()
    assert list(session.state.portraits) == ["Toby Reed"] and session.pending_portraits == []


# ---- the whole server --------------------------------------------------------------------------


def make_client(tmp_path, **kw):
    settings = Settings(test_mode=True, test_delay=0, save_dir=tmp_path, _env_file=None, **kw)
    return TestClient(create_app(settings))


def test_a_test_game_makes_the_partys_portrait_on_disk_and_saves_it(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    chat(client, "look around")
    state = client.app.state.sessions.get("default").state
    rec = state.portraits["Test Hero"]
    assert rec.ready and (tmp_path / "images" / rec.image).is_file() and rec.style == "modern"  # the dnd55e default
    client.put("/history/g/save")
    saved = json.loads((tmp_path / "g.json").read_text())
    assert saved["version"] == 12 and saved["portraits"]["Test Hero"]["image"] == rec.image
    client.post("/history/g/restore")
    again = client.app.state.sessions.get("default").state
    assert again.portraits["Test Hero"].image == rec.image


def test_portraits_stay_off_without_a_key_or_when_switched_off(tmp_path):
    for kw in ({"images": False}, {}):
        client = TestClient(create_app(Settings(test_mode=False, anthropic_api_key="x", save_dir=tmp_path, _env_file=None, **kw)))
        assert client.app.state.portraits is None
    client = make_client(tmp_path, images=False)
    chat(client, "begin")
    chat(client, "look around")
    assert client.app.state.sessions.get("default").state.portraits == {}


# ---- what clients see (docs/PORTRAITS.md 9) ----------------------------------------------------


def test_the_character_page_carries_the_portrait_in_each_state(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    session = client.app.state.sessions.get("default")
    svc = client.app.state.portraits
    page = client.get("/characters/Test Hero").json()
    rec = session.state.portraits.get("Test Hero")
    if rec is None:  # the sweep after the first turn has not made it yet: it is on its way
        assert page["portrait"] == {"state": "pending", "style": "modern", "shape": "square"}
        chat(client, "look around")
        page = client.get("/characters/Test Hero").json()
        rec = session.state.portraits["Test Hero"]
    assert page["portrait"] == {
        "state": "ready", "style": "modern", "shape": "square", "url": f"/portraits/{rec.image}?session_id=default"
    }
    session.state.art_style = art.NO_PORTRAITS
    assert client.get("/characters/Test Hero").json()["portrait"] is None
    session.state.art_style = None
    session.state.portraits.clear()
    svc.disabled = True
    assert client.get("/characters/Test Hero").json()["portrait"] is None  # off for the run: nothing is coming
    svc.disabled = False
    failure = Failure("unavailable", 1, session.state.turn, session.state.looks["Test Hero"].rev, "modern")
    session.state.portraits["Test Hero"] = Portrait(None, "modern", 1, "", session.state.turn, failure)
    assert client.get("/characters/Test Hero").json()["portrait"] is None  # waiting to retry: not "pending"


def test_a_server_without_portraits_says_null(tmp_path):
    client = make_client(tmp_path, images=False)
    chat(client, "begin")
    assert client.get("/characters/Test Hero").json()["portrait"] is None
    assert client.get("/health").json()["images"] is False
    assert client.get("/portraits/p_0123456789abcdef.webp").status_code == 404


def test_the_image_route_serves_a_shown_picture_with_the_right_headers(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    chat(client, "look around")
    rec = client.app.state.sessions.get("default").state.portraits["Test Hero"]
    resp = client.get(f"/portraits/{rec.image}")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert resp.content == (tmp_path / "images" / rec.image).read_bytes()


def test_the_image_route_refuses_what_this_game_does_not_show(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    chat(client, "look around")
    rec = client.app.state.sessions.get("default").state.portraits["Test Hero"]
    other = tmp_path / "images" / "p_aaaaaaaaaaaaaaaa.png"
    other.write_bytes(b"\x89PNG\r\n\x1a\nxx")  # a picture in the library that no character of this game has
    assert client.get("/portraits/p_aaaaaaaaaaaaaaaa.png").status_code == 404
    assert client.get(f"/portraits/{rec.image}?session_id=other").status_code == 404  # another game
    for bad in ("..%2Fsecret.png", "p_1.png", f"{rec.image}x", "p_0123456789abcdef.gif"):
        assert client.get(f"/portraits/{bad}").status_code in (404, 422)
    assert client.get("/portraits/p_aaaaaaaaaaaaaaaa.png").json()["error"]["message"] == "No such portrait"


# ---- people the player has met -----------------------------------------------------------------


def add_npc(session, name, *, known=True, present=False, rev=1):
    world = session.state.world
    ent = world.add_entity(name, "npc")
    ent.look = look_of(name, rev=rev)
    ent.look.description += f" Mark of {name}."
    if known:
        world.add_fact(f"{name} is a local.", [ent.id], disclosure="known")
    if present:
        world.set_scene(None, [*world.scene.present, ent.id])
    return ent


def test_only_people_the_player_can_see_get_pictures_and_the_scene_comes_first(tmp_path):
    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed",))
    old = add_npc(session, "Old Tam")
    here = add_npc(session, "Wren Tallow", present=True)
    newer = add_npc(session, "Brisk Ilsa")
    add_npc(session, "Secret Villain", known=False)  # never met: hidden facts only
    session.state.world.add_fact("The villain plots.", [session.state.world.find("Secret Villain").id])
    names = [j.name for j in svc.due_jobs(session.state)]
    assert names == ["Toby Reed", "Wren Tallow", "Brisk Ilsa", "Old Tam"]
    assert [j.entity for j in svc.due_jobs(session.state)] == [None, here.id, newer.id, old.id]


def test_a_met_person_with_no_facts_yet_still_gets_a_picture(tmp_path):
    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed",))
    add_npc(session, "Quiet Pol", known=False, present=True)  # in the scene, so met
    assert [j.name for j in svc.due_jobs(session.state)] == ["Toby Reed", "Quiet Pol"]


def test_a_sweep_is_four_in_all_party_first(tmp_path):
    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed", "Wren Tallow"))
    for n in ("A One", "B Two", "C Three", "D Four"):
        add_npc(session, n)
    assert [j.name for j in svc.due_jobs(session.state)] == ["Toby Reed", "Wren Tallow", "D Four", "C Three"]


async def test_the_sweep_files_the_partys_and_the_peoples_pictures_in_the_right_places(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session(("Toby Reed",))
    npc = add_npc(session, "Old Tam")
    assert await svc.run_if_due(session)
    rec = session.state.world.entities[npc.id].portrait
    assert rec.ready and svc.store.has(rec.image) and "Toby Reed" in session.state.portraits
    assert "Tam" not in " ".join(fake.prompts)  # names are scrubbed for everyone
    assert not svc.due(session)


async def test_a_failure_for_a_person_is_recorded_on_them_and_waits(tmp_path):
    fake = FakeImages(fail=[ImageError(images.UNAVAILABLE, "down")] * 2)
    svc, _ = service(tmp_path, fake)
    session = party_session(("Toby Reed",))
    npc = add_npc(session, "Old Tam")
    await svc.run_if_due(session)
    assert session.state.world.entities[npc.id].portrait.failure.attempts == 1
    assert session.state.world.entities[npc.id].portrait.image is None
    assert [j.name for j in svc.due_jobs(session.state)] == []  # backing off


async def test_a_revised_look_replaces_a_persons_picture_later_and_keeps_it_meanwhile(tmp_path):
    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed",))
    npc = add_npc(session, "Old Tam")
    await svc.run_if_due(session)
    first = session.state.world.entities[npc.id].portrait
    revised = look_of("Old Tam", rev=2)
    revised.description += " A new scar."
    session.state.world.set_look(npc.id, revised)
    assert svc.due_jobs(session.state) == []  # too soon
    session.state.turn += REGEN_TURNS
    assert [j.name for j in svc.due_jobs(session.state)] == ["Old Tam"]
    await svc.run_if_due(session)
    second = session.state.world.entities[npc.id].portrait
    assert second.image != first.image and second.look_rev == 2


def test_a_persons_portrait_is_saved_with_the_world_and_only_people_have_one(tmp_path):
    from aigm.world import World
    from aigm.world.model import WorldError

    world = World()
    npc = world.add_entity("Old Tam", "npc")
    world.set_portrait(npc.id, record())
    again = World.from_dict(json.loads(json.dumps(world.to_dict())))
    assert again.entities[npc.id].portrait.image == "p_0123456789abcdef.png"
    copy = world.copy()
    copy.entities[npc.id].portrait.turn = 77
    assert world.entities[npc.id].portrait.turn == 1
    place = world.add_entity("Ashby", "location")
    world.set_portrait(place.id, record())  # a place has one too (docs/PLACES.md)
    guild = world.add_entity("Thorn Guild", "faction")
    with pytest.raises(WorldError):
        world.set_portrait(guild.id, record())
    bad = world.to_dict()
    bad["entities"][2]["portrait"] = record().to_dict()  # the faction
    with pytest.raises(CorruptSave):
        World.from_dict(bad)
    broken = world.to_dict()
    broken["entities"][0]["portrait"] = {"image": "../x", "style": "ink", "look_rev": 1}
    with pytest.raises(CorruptSave):
        World.from_dict(broken)


def test_the_compendium_entry_carries_the_portrait_and_the_image_is_served_to_those_who_met_them(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    chat(client, "establish Wren")
    chat(client, "look around")
    chat(client, "look around")
    session = client.app.state.sessions.get("default")
    world = session.state.world
    met = next(e for e in world.entities.values() if e.kind == "npc" and e.portrait and e.discovered)
    page = client.get(f"/compendium/entities/{met.id}").json()
    assert page["portrait"] == {
        "state": "ready", "style": "modern", "shape": "square", "url": f"/portraits/{met.portrait.image}?session_id=default",
    }
    assert client.get(page["portrait"]["url"]).status_code == 200
    # a person who has not been met has no entry, and so no picture is served for them
    secret = world.add_entity("Hidden Duke", "npc")
    secret.look = look_of("Hidden Duke")
    secret.portrait = Portrait("p_bbbbbbbbbbbbbbbb.png", "modern", 1, MODEL, 1)
    (tmp_path / "images" / "p_bbbbbbbbbbbbbbbb.png").write_bytes(b"\x89PNG\r\n\x1a\nxx")
    assert client.get("/portraits/p_bbbbbbbbbbbbbbbb.png").status_code == 404
    assert client.get(f"/compendium/entities/{secret.id}").status_code == 404
    world.set_scene(None, [secret.id])  # now the player sees him
    assert client.get("/portraits/p_bbbbbbbbbbbbbbbb.png").status_code == 200


def test_places_and_unpictured_people_say_null_or_pending(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    chat(client, "establish Wren")
    session = client.app.state.sessions.get("default")
    world = session.state.world
    faction = world.add_entity("Thorn Guild", "faction")
    world.add_fact("The Thorn Guild keeps the roads.", [faction.id], aspect="goals", disclosure="known")
    assert client.get(f"/compendium/entities/{faction.id}").json()["portrait"] is None  # only people and places
    npc = next(e for e in world.entities.values() if e.kind == "npc" and e.discovered)
    npc.portrait = None
    session.state.turn += 50
    assert client.get(f"/compendium/entities/{npc.id}").json()["portrait"] == {
        "state": "pending", "style": "modern", "shape": "square"
    }
