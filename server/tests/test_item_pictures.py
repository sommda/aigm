"""Pictures of key items: the portrait pipeline's still-life jobs, in their own shapes (docs/KEY_ITEMS.md 8)."""

import json

from aigm import art
from aigm.images import ImageError
from aigm.looks import Look
from aigm.portraits import MAX_PER_SWEEP
from tests.conftest import chat
from tests.test_item_looks import make_item_look
from tests.test_place_pictures import add_place
from tests.test_portraits import add_npc, make_client, party_session, service

PLACE_SIZE = "1536x1024"


def add_item(session, name, *, status="held", frame="square", turn=3, rev=1, look=True):
    world = session.state.world
    ent = world.add_entity(name, "item")
    if status != "unfound":
        world.set_holding(ent.id, "learned" if status == "known" else "acquired", turn=turn)
    if look:
        ent.look = make_item_look(name)
        ent.look.tags["frame"] = frame
        ent.look.rev = rev
        ent.look.description += f" Mark of {name}."
    return ent


def jobs(svc, session):
    return [(j.name, j.kind) for j in svc.due_jobs(session.state)]


def test_the_order_is_party_here_scene_people_items_other_people_other_places(tmp_path):
    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed",))
    add_place(session, "Old Mill")
    add_npc(session, "Old Tam")
    add_item(session, "Brass Key", turn=2)
    add_item(session, "Ledger", turn=7)
    add_npc(session, "Wren Tallow", present=True)
    add_place(session, "The Flagon", here=True)
    assert jobs(svc, session) == [
        ("Toby Reed", "person"), ("The Flagon", "place"), ("Wren Tallow", "person"), ("Ledger", "item"),
    ][:MAX_PER_SWEEP]
    session.state.portraits = {}
    quiet = party_session(("Toby Reed",))
    add_place(quiet, "Old Mill")
    add_npc(quiet, "Old Tam")
    add_item(quiet, "Brass Key", turn=2)
    add_item(quiet, "Ledger", turn=7)
    assert jobs(svc, quiet) == [  # the most recently acquired first
        ("Toby Reed", "person"), ("Ledger", "item"), ("Brass Key", "item"), ("Old Tam", "person"),
    ]


def test_an_item_the_player_has_not_met_or_that_has_no_look_gets_no_picture(tmp_path):
    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed",))
    add_item(session, "Held Key")
    add_item(session, "Unfound Key", status="unfound")  # a Look is impossible, but even with one it is not shown
    session.state.world.find("Unfound Key").look = make_item_look("Unfound Key")
    add_item(session, "Sought Key", status="known", look=False)
    add_item(session, "Plain Key", look=False)  # held, not yet described
    assert [n for n, _ in jobs(svc, session)] == ["Toby Reed", "Held Key"]


async def test_each_frame_has_its_own_size_and_shape_and_the_prompt_is_the_item_prompt(tmp_path):
    svc, fake = service(tmp_path)
    session = party_session(("Toby Reed",))
    session.state.looks.clear()  # no party picture: only the items
    wide = add_item(session, "Harbor Chart", frame="landscape", turn=3)
    tall = add_item(session, "Steward's Ledger", frame="portrait", turn=4)
    square = add_item(session, "Sluice Key", frame="square", turn=5)
    assert await svc.run_if_due(session)
    assert dict(zip(fake.prompts, fake.sizes)) and sorted(s for s in fake.sizes if s) == sorted(
        ["1024x1024", PLACE_SIZE, "1024x1536"]
    )
    by_size = {size: prompt for prompt, size in zip(fake.prompts, fake.sizes)}
    for prompt in by_size.values():
        assert art.ITEM_FRAMING in prompt and art.FRAMING not in prompt and art.PLACE_FRAMING not in prompt
        assert "Sluice Key" not in prompt and "Harbor Chart" not in prompt and "Steward" not in prompt
    shapes = {e.name: svc.view_entity(session, e.id)["shape"] for e in (wide, tall, square)}
    assert shapes == {"Harbor Chart": "landscape", "Steward's Ledger": "portrait", "Sluice Key": "square"}
    rec = session.state.world.entities[square.id].portrait
    notes = json.loads((svc.store.root / rec.image.rsplit(".", 1)[0]).with_suffix(".json").read_text())
    assert notes["kind"] == "item" and notes["size"] == "1024x1024" and notes["look_search_text"].startswith("key small |")


def test_a_portrait_shape_turns_the_place_size_on_its_side(tmp_path):
    svc, _ = service(tmp_path, place_size="1792x1024")
    session = party_session(("Toby Reed",))
    session.state.looks.clear()
    add_item(session, "Ledger", frame="portrait")
    (job,) = svc.due_jobs(session.state)
    assert svc.size_for(job) == "1024x1792"


def test_the_style_has_an_object_variant_where_the_plain_one_speaks_of_faces(tmp_path):
    for style in art.STYLES:
        prompt = art.build_item_prompt(make_item_look(), style, ["Sluice Key"])
        assert style.direction_for("item") in prompt and "face" not in style.direction_for("item").lower()
    assert "portrait sketch" not in art.BY_ID["sketch"].direction_for("item")
    assert "eyes" not in art.BY_ID["anime"].direction_for("item")
    assert "Sluice Key" not in art.build_item_prompt(make_item_look(), art.BY_ID["ink"], ["Sluice Key"])


async def test_a_refused_item_picture_is_recorded_and_not_softened_or_retried(tmp_path):
    svc, fake = service(tmp_path, fake=None)
    fake.fail = [ImageError("moderation", "no")]
    session = party_session(("Toby Reed",))
    session.state.looks.clear()
    item = add_item(session, "Sluice Key")
    assert await svc.run_if_due(session)
    assert len(fake.prompts) == 1  # no softer second prompt
    rec = session.state.world.entities[item.id].portrait
    assert not rec.ready and rec.failure.reason == "moderation"
    assert not svc.due_jobs(session.state)


def test_an_item_waiting_for_its_look_is_pending_a_sought_one_is_not(tmp_path):
    svc, _ = service(tmp_path)
    svc.describes["item"] = True
    session = party_session(("Toby Reed",))
    held = add_item(session, "Held Key", look=False)
    sought = add_item(session, "Sought Key", status="known", look=False)
    assert svc.view_entity(session, held.id) == {"state": "pending", "style": "ink", "shape": "square"}
    assert svc.view_entity(session, sought.id) is None
    session.item_looks_retry_turn = session.state.turn + 5
    assert svc.view_entity(session, held.id) is None
    session.item_looks_retry_turn = 0
    svc.describes["item"] = False
    assert svc.view_entity(session, held.id) is None


def test_a_limit_to_important_items_would_stop_the_rest_being_pictured(tmp_path, monkeypatch):
    import aigm.portraits as portraits

    svc, _ = service(tmp_path)
    session = party_session(("Toby Reed",))
    add_item(session, "Minor Trinket")
    monkeypatch.setattr(portraits, "item_wanted", lambda ent: False)
    assert jobs(svc, session) == [("Toby Reed", "person")]


def acquire_through_a_turn(tmp_path):
    client = make_client(tmp_path)
    chat(client, "begin")
    session = client.app.state.sessions.get("default")
    world = session.state.world
    item = world.add_entity("Sluice Key", "item")
    world.add_fact("Sluice Key is a heavy brass key.", [item.id], aspect="appearance")
    world.add_fact("SECRET: the key is cursed.", [item.id], aspect="secret")
    return client, session, item


def test_an_acquired_item_is_described_pictured_and_served_after_a_turn(tmp_path):
    client, session, item = acquire_through_a_turn(tmp_path)
    assert client.get(f"/compendium/entities/{item.id}").status_code == 404  # not in play yet
    session.state.world.set_holding(item.id, "acquired", "Found.", turn=session.state.turn)
    page = client.get(f"/compendium/entities/{item.id}").json()
    assert page["look"] is None and page["portrait"] == {"state": "pending", "style": "modern", "shape": "square"}
    chat(client, "look around")
    ent = session.state.world.find("Sluice Key")
    assert ent.look is not None and ent.portrait is not None and ent.portrait.ready
    page = client.get(f"/compendium/entities/{item.id}").json()
    assert page["look"]["summary"] and page["portrait"]["state"] == "ready"
    assert page["portrait"]["shape"] == ent.look.tags["frame"]
    resp = client.get(page["portrait"]["url"])
    assert resp.status_code == 200 and resp.content == (tmp_path / "images" / ent.portrait.image).read_bytes()


def test_a_known_item_has_neither_a_look_nor_a_picture_until_it_is_acquired(tmp_path):
    client, session, item = acquire_through_a_turn(tmp_path)
    session.state.world.set_holding(item.id, "learned", turn=session.state.turn)
    chat(client, "look around")
    chat(client, "look again")
    ent = session.state.world.find("Sluice Key")
    assert ent.look is None and ent.portrait is None
    page = client.get(f"/compendium/entities/{item.id}").json()
    assert page["look"] is None and page["portrait"] is None and page["holding"]["status"] == "known"
    session.state.world.set_holding(item.id, "acquired", turn=session.state.turn)
    chat(client, "look once more")
    assert session.state.world.find("Sluice Key").portrait.ready


def test_the_picture_of_an_item_the_player_has_not_met_is_not_served(tmp_path):
    from aigm.portraits import Portrait
    from tests.test_portraits import MODEL

    client, session, item = acquire_through_a_turn(tmp_path)
    ent = session.state.world.find("Sluice Key")
    ent.look = make_item_look("Sluice Key")
    ent.portrait = Portrait("p_dddddddddddddddd.png", "modern", 1, MODEL, 1)
    (tmp_path / "images").mkdir(exist_ok=True)
    (tmp_path / "images" / "p_dddddddddddddddd.png").write_bytes(b"\x89PNG\r\n\x1a\nxx")
    assert client.get("/portraits/p_dddddddddddddddd.png").status_code == 404
    session.state.world.set_holding(item.id, "acquired", turn=1)
    assert client.get("/portraits/p_dddddddddddddddd.png").status_code == 200


def test_a_loaded_game_describes_and_pictures_the_items_it_holds(tmp_path):
    client, session, item = acquire_through_a_turn(tmp_path)
    session.state.world.set_holding(item.id, "acquired", turn=session.state.turn)
    client.put("/history/g/save")
    saved = json.loads((tmp_path / "g.json").read_text())
    assert next(e for e in saved["world"]["entities"] if e["name"] == "Sluice Key")["holding"]["status"] == "held"
    assert client.post("/history/g/restore").status_code == 200  # no turn after it
    ent = client.app.state.sessions.get("default").state.world.find("Sluice Key")
    assert ent.look is not None and ent.portrait is not None and ent.portrait.ready


def test_the_test_mode_gm_can_hand_over_an_item_and_the_whole_chain_runs(tmp_path):
    client = make_client(tmp_path)

    def key():  # a turn replaces the game state, so look the item up again each time
        return client.app.state.sessions.get("default").state.world.find("Sluice Key")

    chat(client, "begin")
    chat(client, "item Sluice Key learned")
    chat(client, "look around")
    assert key().holding.status == "known" and key().look is None  # sought, not yet described
    assert client.get(f"/compendium/entities/{key().id}").json()["portrait"] is None
    chat(client, "item Sluice Key acquired")
    chat(client, "look around")
    assert key().holding.status == "held" and key().look is not None and key().portrait.ready
    chat(client, "item Sluice Key lost")
    assert client.get(f"/compendium/entities/{key().id}").json()["holding"]["status"] == "lost"
