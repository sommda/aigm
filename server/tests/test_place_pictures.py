"""Pictures of places: the portrait pipeline's landscape jobs (docs/PLACES.md 8)."""

import json

from aigm import art, images
from aigm.images import FakeImages, ImageError
from aigm.portraits import MAX_PER_SWEEP, REGEN_TURNS, Portrait, _visible_places
from tests.conftest import chat
from tests.test_place_looks import make_place_look
from tests.test_portraits import MODEL, add_npc, make_client, party_session, service

PLACE_SIZE = "1536x1024"


def add_place(session, name, *, known=True, here=False, aspect="overview", rev=1):
    world = session.state.world
    ent = world.add_entity(name, "location")
    look = make_place_look(name)
    look.rev = rev
    look.description += f" Mark of {name}."
    ent.look = look
    if known:
        world.add_fact(f"{name} is a place to see.", [ent.id], aspect=aspect, disclosure="known")
    if here:
        world.set_scene(ent.id, list(world.scene.present))
    return ent


def jobs(svc, session):
    return [(j.name, j.place) for j in svc.due_jobs(session.state)]


def test_the_current_place_comes_right_after_the_party_then_people_in_the_scene_then_others_then_other_places(tmp_path):
    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed", "Wren Tallow"))
    add_place(session, "Old Mill")
    add_npc(session, "Quiet Pol", known=False, present=True)
    add_npc(session, "Old Tam")
    add_place(session, "The Flagon", here=True)
    world = session.state.world
    world.set_scene(world.find("The Flagon").id, [world.find("Quiet Pol").id])
    assert jobs(svc, session) == [
        ("Toby Reed", False), ("Wren Tallow", False), ("The Flagon", True), ("Quiet Pol", False),
    ][:MAX_PER_SWEEP]
    session.state.portraits = {}
    big = party_session(("Toby Reed",))
    add_place(big, "Hall One")
    add_place(big, "Hall Two", here=True)
    add_npc(big, "Old Tam")
    assert [n for n, _ in jobs(svc, big)] == ["Toby Reed", "Hall Two", "Old Tam", "Hall One"]


def test_only_places_the_player_knows_and_that_have_a_look_get_pictures(tmp_path):
    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed",))
    add_place(session, "Known Hall")
    add_place(session, "Secret Vault", known=False)  # a Look but never discovered
    hidden = session.state.world.add_entity("Hidden Hall", "location")
    session.state.world.add_fact("The hall is round.", [hidden.id], aspect="overview", disclosure="hidden")
    session.state.world.add_entity("Plain Hall", "location").discovered = True  # no Look, no facts
    # The vault has a Look but is not discovered: it is pictured ahead of arrival, last, and stays out of the compendium.
    assert [n for n, _ in jobs(svc, session)] == ["Toby Reed", "Known Hall", "Secret Vault"]
    assert [p.name for p in _visible_places(session.state.world)] == ["Known Hall"]


async def test_a_view_is_landscape_built_from_the_place_prompt_and_stored_with_its_notes(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session(("Toby Reed",))
    place = add_place(session, "Icehold Square", here=True)
    assert await svc.run_if_due(session)
    rec = session.state.world.entities[place.id].portrait
    assert rec.ready and svc.store.has(rec.image) and rec.style == "ink" and rec.look_rev == 1
    assert fake.sizes == [None, PLACE_SIZE]  # the portrait at the server's size, the view at its own
    view = fake.prompts[1]
    assert art.PLACE_FRAMING in view and "Icehold" not in view and art.FRAMING not in view
    assert art.FRAMING in fake.prompts[0] and art.PLACE_FRAMING not in fake.prompts[0]
    notes = json.loads((svc.store.root / rec.image.rsplit(".", 1)[0]).with_suffix(".json").read_text())
    assert notes["kind"] == "place" and notes["size"] == PLACE_SIZE and notes["prompt"] == view
    assert notes["look_search_text"].startswith("site urban cold |")


async def test_the_size_is_part_of_the_picture_id_so_views_and_portraits_never_collide(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session(("Toby Reed",))
    add_place(session, "Icehold Square")
    await svc.run_if_due(session)
    files = sorted(p.name for p in svc.store.root.glob("p_*.png"))
    assert len(files) == 2 and len(set(files)) == 2


async def test_a_refused_view_is_recorded_and_not_retried_and_the_people_are_unaffected(tmp_path):
    fake = FakeImages(fail=[ImageError(images.MODERATION, "no")])
    svc, _ = service(tmp_path, fake)
    session = party_session(("Toby Reed",))
    place = add_place(session, "Icehold Square", here=True)
    session.state.portraits["Toby Reed"] = Portrait("p_0123456789abcdef.png", "modern", 1, MODEL, 1)
    (svc.store.root).mkdir(parents=True, exist_ok=True)
    (svc.store.root / "p_0123456789abcdef.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
    await svc.run_if_due(session)
    rec = session.state.world.entities[place.id].portrait
    assert not rec.ready and rec.failure.reason == images.MODERATION and len(fake.prompts) == 1  # one try only
    assert not svc.due_jobs(session.state)  # and not tried again


async def test_a_revised_place_gets_a_new_view_after_a_while_and_keeps_the_old_one_meanwhile(tmp_path):
    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed",))
    place = add_place(session, "Icehold Square")
    await svc.run_if_due(session)
    first = session.state.world.entities[place.id].portrait
    revised = make_place_look("Icehold Square")
    revised.rev, revised.description = 2, revised.description + " A new tower rises beside the well."
    session.state.world.set_look(place.id, revised)
    assert [n for n, p in jobs(svc, session) if p] == []  # too soon
    assert session.state.world.entities[place.id].portrait.image == first.image
    session.state.turn += REGEN_TURNS
    assert [n for n, p in jobs(svc, session) if p] == ["Icehold Square"]
    await svc.run_if_due(session)
    assert session.state.world.entities[place.id].portrait.image != first.image


def test_a_limit_to_major_places_would_stop_the_rest_being_pictured(tmp_path, monkeypatch):
    import aigm.portraits as portraits

    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed",))
    add_place(session, "Minor Shed")
    monkeypatch.setattr(portraits, "place_wanted", lambda ent: ent.name != "Minor Shed")
    assert jobs(svc, session) == [("Toby Reed", False)]


def test_the_view_says_landscape_and_a_place_that_is_only_waiting_is_pending(tmp_path):
    svc, _ = service(tmp_path)
    client_session = party_session(("Toby Reed",))
    place = add_place(client_session, "Icehold Square")
    assert svc.view_entity(client_session, place.id) == {"state": "pending", "style": "ink", "shape": "landscape"}
    assert svc.view_entity(client_session, "e999") is None


def test_a_test_game_pictures_each_described_place_and_serves_the_pictures(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    for _ in range(3):
        chat(client, "look around")
    session = client.app.state.sessions.get("default")
    world = session.state.world
    flagon = world.find("Rusty Flagon")
    assert flagon.look is not None and flagon.portrait is not None and flagon.portrait.ready
    assert world.find("The Test Marches").portrait is None  # never described, so never pictured
    assert world.find("Rusty Flagon Cellar").portrait is None  # not discovered
    page = client.get(f"/compendium/entities/{flagon.id}").json()
    assert page["portrait"] == {
        "state": "ready", "style": "modern", "shape": "landscape",
        "url": f"/portraits/{flagon.portrait.image}?session_id=default",
    }
    resp = client.get(page["portrait"]["url"])
    assert resp.status_code == 200 and resp.content == (tmp_path / "images" / flagon.portrait.image).read_bytes()


def test_a_place_the_player_has_not_discovered_is_not_served_even_by_name(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    chat(client, "look around")
    session = client.app.state.sessions.get("default")
    cellar = session.state.world.find("Rusty Flagon Cellar")
    cellar.look = make_place_look("Rusty Flagon Cellar")
    cellar.portrait = Portrait("p_cccccccccccccccc.png", "modern", 1, MODEL, 1)
    (tmp_path / "images" / "p_cccccccccccccccc.png").write_bytes(b"\x89PNG\r\n\x1a\nxx")
    assert client.get("/portraits/p_cccccccccccccccc.png").status_code == 404
    assert client.get(f"/compendium/entities/{cellar.id}").status_code == 404
    session.state.world.add_fact("A cold cellar of barrels.", [cellar.id], aspect="overview", disclosure="known")
    assert client.get("/portraits/p_cccccccccccccccc.png").status_code == 200


def test_the_save_keeps_a_places_picture(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    for _ in range(3):
        chat(client, "look around")
    client.put("/history/g/save")
    saved = json.loads((tmp_path / "g.json").read_text())
    flagon = next(e for e in saved["world"]["entities"] if e["name"] == "Rusty Flagon")
    assert flagon["portrait"]["image"].startswith("p_") and flagon["look"]["summary"]


def strip_visuals(path):
    """A save as it was before descriptions and pictures: no Looks, no portraits."""
    saved = json.loads(path.read_text())
    for e in saved["world"]["entities"]:
        e["look"] = e["portrait"] = None
    saved["looks"], saved["portraits"] = {}, {}
    path.write_text(json.dumps(saved))


def test_a_loaded_game_writes_its_missing_descriptions_and_pictures_without_waiting_for_a_turn(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    for _ in range(3):
        chat(client, "look around")
    client.put("/history/g/save")
    strip_visuals(tmp_path / "g.json")
    assert client.post("/history/g/restore").status_code == 200  # no turn after it
    state = client.app.state.sessions.get("default").state
    flagon = state.world.find("Rusty Flagon")
    assert flagon.look is not None and flagon.portrait is not None and flagon.portrait.ready  # the place
    assert state.looks["Test Hero"] and state.portraits["Test Hero"].ready  # and the party
    assert state.world.find("The Test Marches").look is None  # still only a rumor
    assert client.get("/compendium/entities/" + flagon.id).json()["look"]["summary"] == flagon.look.summary


def test_a_replaced_game_is_not_caught_up(tmp_path):
    import asyncio

    from aigm.routes.history import catch_up

    client = make_client(tmp_path)
    chat(client, "begin")
    chat(client, "look around")
    session = client.app.state.sessions.get("default")
    stale = session.generation
    session.reset_world_work()  # the game was replaced while the catch-up waited
    flagon = session.state.world.find("Rusty Flagon")
    flagon.look = flagon.portrait = None
    asyncio.run(catch_up(client.app, session, stale))
    assert flagon.look is None


def test_a_place_that_is_about_to_be_described_shows_as_pending_and_one_that_never_will_does_not(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    session = client.app.state.sessions.get("default")
    world = session.state.world
    flagon, marches, cellar = world.find("Rusty Flagon"), world.find("The Test Marches"), world.find("Rusty Flagon Cellar")
    flagon.look = flagon.portrait = None  # described as soon as the next sweep runs
    page = lambda ent: client.get(f"/compendium/entities/{ent.id}").json()["portrait"]  # noqa: E731
    assert page(flagon) == {"state": "pending", "style": "modern", "shape": "landscape"}
    assert page(marches) is None  # known only by an aspect-less fact: it is not going to be described
    world.add_fact("A cold cellar of barrels.", [cellar.id], aspect="overview", disclosure="known")
    assert page(cellar)["state"] == "pending"
    session.place_looks_retry_turn = session.state.turn + 5  # the last sweep failed and is backing off
    assert page(flagon) is None
    session.place_looks_retry_turn = 0
    client.app.state.portraits.describes["location"] = False  # a curator that cannot describe places
    assert page(flagon) is None


def test_the_status_page_carries_the_look_and_picture_of_where_the_party_is(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    for _ in range(3):
        chat(client, "look around")
    session = client.app.state.sessions.get("default")
    flagon = session.state.world.find("Rusty Flagon")
    loc = client.get("/status").json()["location"]
    assert loc["name"] == "Rusty Flagon" and loc["look"] == {
        "summary": flagon.look.summary, "description": flagon.look.description
    }
    assert loc["portrait"] == {
        "state": "ready", "style": "modern", "shape": "landscape",
        "url": f"/portraits/{flagon.portrait.image}?session_id=default",
    }
    flagon.portrait = None  # a picture that is on its way
    session.state.turn += 50
    assert client.get("/status").json()["location"]["portrait"]["state"] == "pending"
    session.state.world.set_scene(None, [])
    assert client.get("/status").json()["location"] is None  # nowhere recorded: nothing to add


def test_without_portraits_the_status_location_has_a_look_and_no_picture(tmp_path):
    client = make_client(tmp_path, images=False)
    chat(client, "begin")
    chat(client, "look around")
    loc = client.get("/status").json()["location"]
    assert loc["portrait"] is None and loc["look"] is not None


async def test_the_current_place_is_made_alone_and_at_once(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session(("Toby Reed",))
    add_place(session, "Old Mill")
    place = add_place(session, "The Flagon", here=True)
    add_npc(session, "Old Tam")
    assert await svc.here_first(None, session)
    assert len(fake.prompts) == 1 and fake.sizes == [PLACE_SIZE]  # not the party, the people or the other place
    assert session.state.world.entities[place.id].portrait.ready
    assert session.state.world.find("Old Mill").portrait is None
    assert not await svc.here_first(None, session)  # nothing left to make for it


async def test_a_sweep_in_progress_does_not_hold_up_the_current_place(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session(("Toby Reed",))
    place = add_place(session, "The Flagon", here=True)
    session.imaging = True  # a sweep is running
    assert await svc.here_first(None, session)
    assert session.state.world.entities[place.id].portrait.ready


async def test_a_picture_being_made_is_not_made_twice(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session(("Toby Reed",))
    place = add_place(session, "The Flagon", here=True)
    session.imaging_keys.add(place.id)
    assert not await svc.here_first(None, session)
    assert await svc.run_if_due(session)  # the sweep takes the others
    assert session.state.world.entities[place.id].portrait is None
    assert len(fake.prompts) == 1


async def test_each_picture_of_a_sweep_is_applied_as_it_finishes(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session(("Toby Reed",))
    add_place(session, "Old Mill")
    seen = []
    jobs = svc.due_jobs(session.state)
    await svc.run(jobs, art.resolve_style(None, session.state.ruleset), 1, lambda key, rec: seen.append(key))
    assert len(seen) == len(jobs) == 2


# ---- places the party has not reached (docs/PLACES.md 6.1) --------------------------------


def test_a_place_made_ahead_is_pictured_but_stays_out_of_the_compendium_and_is_not_served(tmp_path):
    from aigm.compendium import _visible
    from aigm.portraits import _premade_places

    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed",))
    ahead = add_place(session, "Far Keep", known=False)
    world = session.state.world
    assert [p.name for p in _premade_places(world)] == ["Far Keep"] and not _visible(world, ahead.id)
    assert [n for n, _ in jobs(svc, session)] == ["Toby Reed", "Far Keep"]


async def test_the_picture_of_a_place_made_ahead_is_never_served_to_a_player_and_is_ready_on_arrival(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session(("Toby Reed",))
    ahead = add_place(session, "Far Keep", known=False)
    assert await svc.run_if_due(session)
    world = session.state.world
    record = world.entities[ahead.id].portrait
    assert record.ready and svc.shown(session, record.image) is None
    assert [p["name"] for p in svc.premade(session)] == ["Far Keep"]
    assert svc.premade_file(session, record.image) is not None
    world.set_scene(ahead.id, [])  # the party arrives: the picture is there already
    assert svc.shown(session, record.image) is not None and not svc.due_jobs(session.state)
    assert svc.premade(session) == []


def test_the_premade_places_can_be_seen_only_in_debug_mode(tmp_path):
    from fastapi.testclient import TestClient

    from aigm.app import create_app
    from aigm.config import Settings

    def run(debug):
        app = create_app(Settings(
            test_mode=True, test_delay=0, save_dir=tmp_path / str(debug), debug=debug, _env_file=None
        ))
        client = TestClient(app)
        chat(client, "begin")
        chat(client, "look around")
        session = app.state.sessions.get("default")
        world = session.state.world
        far = world.add_entity("Far Keep", "location")
        world.add_fact("The keep is a black tower.", [far.id], aspect="overview", disclosure="hidden")
        far.look = make_place_look("Far Keep")
        return client, far

    client, far = run(False)
    assert client.get("/debug/premade").status_code == 404
    assert client.get("/compendium/locations").json()["entries"] and far.name not in str(
        client.get("/compendium/locations").json()
    )
    client, far = run(True)
    body = client.get("/debug/premade").json()
    assert [p["name"] for p in body["places"]] == ["Far Keep"] and "Far Keep" not in str(
        client.get("/compendium/locations").json()
    )
