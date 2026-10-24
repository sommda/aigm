import json

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from aigm.session.persistence import HistoryRepository
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.world import World, WorldTime
from aigm.world.dump import WorldDumper, dump_world, fact_line, main, render
from tests.conftest import chat


@pytest.fixture
def w():
    world = World()
    region = world.add_entity("Thornwood", "location")
    town = world.add_entity("Ashby", "location", aliases=["the town"], parent=region.id)
    mine = world.add_entity("Harrow Mine", "location", parent=region.id)
    cellar = world.add_entity("Smugglers' Cellar", "location", parent=town.id)
    guild = world.add_entity("Thorn Guild", "faction")
    world.advance_time(30)
    world.add_fact("The Harrow Mine lies east of Ashby.", [mine.id, town.id], aspect="approach", disclosure="known", turn=2)
    world.add_fact("The mine's lower gallery joins the cellar under Ashby.", [mine.id, cellar.id], aspect="secret")
    old = world.add_fact("The mine shaft is flooded to the first gallery.", [mine.id], aspect="hazards")
    world.supersede(old.id, "The mine shaft was drained last spring.", turn=3)
    world.add_fact("The Thorn Guild controls the toll road.", [guild.id, region.id])
    world.facts["f0002"].until_time = WorldTime(10, 6)
    world.set_scene(town.id, [guild.id])
    world.mark_processed(6)
    world.add_correction("The player was told X. Treat that as true.", 4)
    return world


def test_fact_line_format(w):
    assert fact_line(w, w.fact("f0001")) == "[known|approach|f0001 d2h14] The Harrow Mine lies east of Ashby.  (also: Ashby)"
    assert fact_line(w, w.fact("f0002")).startswith("[hidden|secret|f0002 d2h14 until d10h6] The mine's lower gallery")
    assert fact_line(w, w.fact("f0003")).startswith("[hidden|hazards|f0003 d2h14 -> f0004] ")
    assert fact_line(w, w.fact("f0005")) == "[hidden|-|f0005 d2h14] The Thorn Guild controls the toll road.  (also: Thornwood)"


def test_dump_is_grouped_by_entity_with_a_header_and_fixed_key_order(w):
    d = dump_world(w, session_id="s1")
    assert list(d) == ["session", "time", "scene", "processed_through", "counts", "corrections", "entities"]
    assert d["time"] == "Day 2, 14:00" and d["scene"] == {"location": "Ashby", "present": ["Thorn Guild"]}
    assert d["processed_through"] == 6 and d["counts"] == {"entities": 5, "facts": 4, "superseded": 1}
    assert d["corrections"] == ["The player was told X. Treat that as true."]
    mine = next(e for e in d["entities"] if e["name"] == "Harrow Mine")
    assert list(mine) == ["name", "id", "kind", "in", "discovered", "facts", "superseded"]
    assert mine["in"] == ["Thornwood"] and mine["discovered"] is True
    assert [f.split("]")[0] for f in mine["facts"]] == ["[known|approach|f0001 d2h14", "[hidden|secret|f0002 d2h14 until d10h6", "[hidden|hazards|f0004 d2h14"]
    assert len(mine["superseded"]) == 1 and "flooded" in mine["superseded"][0]
    ashby = next(e for e in d["entities"] if e["name"] == "Ashby")
    assert ashby["aliases"] == ["the town"] and ashby["in"] == ["Thornwood"] and ashby["facts"] == []
    cellar = next(e for e in d["entities"] if e["name"] == "Smugglers' Cellar")
    assert cellar["in"] == ["Ashby", "Thornwood"] and "superseded" not in cellar


def test_rendered_text_is_indented_one_fact_per_line_and_deterministic(w):
    text = render(w, session_id="s1")
    lines = text.splitlines()
    assert len(lines) > 30 and text.endswith("}\n") and text == render(w, session_id="s1")
    assert json.loads(text)["entities"][0]["name"] == "Thornwood"
    fact_lines = [l for l in lines if l.strip().startswith('"[')]
    assert len(fact_lines) == 5 and all(l.count("] ") >= 1 for l in fact_lines)  # four active facts and one superseded
    assert "Smugglers' Cellar" in text  # unescaped unicode and quotes stay readable


def test_known_only_shows_what_the_player_was_told(w):
    d = dump_world(w, known_only=True)
    assert "view" in d and "corrections" not in d
    assert [e["name"] for e in d["entities"]] == ["Harrow Mine"]
    assert d["entities"][0]["facts"] == ["[known|approach|f0001 d2h14] The Harrow Mine lies east of Ashby.  (also: Ashby)"]
    assert "superseded" not in d["entities"][0]


def test_empty_world_dump():
    d = dump_world(World())
    assert d["entities"] == [] and d["scene"] == {"location": None, "present": []}


# ---- the dumper ---------------------------------------------------------------------------


def adventure_session(world):
    s = Session("sess")
    s.state = GameState(Phase.ADVENTURE, {"setting": "x"}, world)
    return s


async def test_dumper_writes_when_the_world_changes_and_not_otherwise(tmp_path, w):
    dumper = WorldDumper(tmp_path / "worlds")
    s = adventure_session(w)
    assert await dumper.update(s) is True
    path = tmp_path / "worlds" / "sess.world.json"
    assert json.loads(path.read_text())["session"] == "sess"
    mtime = path.stat().st_mtime_ns
    assert await dumper.update(s) is False and path.stat().st_mtime_ns == mtime
    s.state.world.add_entity("Wren", "npc")
    assert await dumper.update(s) is True and "Wren" in path.read_text()
    assert not list((tmp_path / "worlds").glob(".*.tmp"))


async def test_a_replaced_game_is_rewritten_even_at_the_same_version(tmp_path, w):
    dumper = WorldDumper(tmp_path)
    s = adventure_session(w)
    await dumper.update(s)
    other = w.copy()
    other.add_entity("Elsewhere", "location")
    other.version = w.version  # same version number, different content
    s.state.world = other
    s.reset_world_work()
    assert await dumper.update(s) is True and "Elsewhere" in (tmp_path / "sess.world.json").read_text()


async def test_an_empty_world_has_no_file_and_remove_deletes_it(tmp_path, w):
    dumper = WorldDumper(tmp_path)
    s = adventure_session(w)
    await dumper.update(s)
    path = tmp_path / "sess.world.json"
    assert path.exists()
    await dumper.remove("sess")
    assert not path.exists()
    await dumper.remove("sess")  # nothing to remove is fine
    s.state = GameState()
    s.reset_world_work()
    assert await dumper.update(s) is True and not path.exists()


async def test_a_disabled_dumper_writes_nothing(tmp_path, w):
    dumper = WorldDumper(tmp_path / "worlds", enabled=False)
    assert await dumper.update(adventure_session(w)) is False
    assert not (tmp_path / "worlds").exists()


async def test_a_write_failure_is_not_fatal(tmp_path, w):
    (tmp_path / "blocked").write_text("a file where the directory should be")
    dumper = WorldDumper(tmp_path / "blocked")
    assert await dumper.update(adventure_session(w)) is False


# ---- over HTTP ----------------------------------------------------------------------------


def make_client(tmp_path, **kw):
    settings = Settings(test_mode=True, test_delay=0, save_dir=tmp_path, _env_file=None, **kw)
    return TestClient(create_app(settings))


def dump_of(tmp_path, session="default"):
    return json.loads((tmp_path / "worlds" / f"{session}.world.json").read_text())


def test_the_dump_follows_play_restore_and_new_game(tmp_path):
    client = make_client(tmp_path)
    chat(client, "echo hello")
    assert not (tmp_path / "worlds").exists()  # Session 0: no world, no file
    chat(client, "begin")
    d = dump_of(tmp_path)
    assert d["time"] == "Day 1, 18:00" and d["scene"]["location"] == "Rusty Flagon"
    assert {e["name"] for e in d["entities"]} >= {"The Test Marches", "Rusty Flagon", "Innkeeper"}
    flagon = next(e for e in d["entities"] if e["name"] == "Rusty Flagon")
    assert flagon["in"] == ["The Test Marches"] and flagon["facts"]
    inn = next(e for e in d["entities"] if e["name"] == "Innkeeper")
    assert any("reports every guest to the baron" in f and f.startswith("[hidden|") for f in inn["facts"])
    chat(client, "establish Wren")  # a GM tool call changes the world: the dump follows the turn
    assert "Wren" in {e["name"] for e in dump_of(tmp_path)["entities"]}
    client.put("/history/g/save")
    client.post("/chat/new")
    assert not (tmp_path / "worlds" / "default.world.json").exists()
    client.post("/history/g/restore")
    assert "Wren" in {e["name"] for e in dump_of(tmp_path)["entities"]}
    client.post("/chat/new")
    chat(client, "begin")
    assert "Wren" not in {e["name"] for e in dump_of(tmp_path)["entities"]}


def test_each_session_has_its_own_dump_and_the_saves_listing_ignores_the_folder(tmp_path):
    client = make_client(tmp_path)
    for sid in ("a", "b"):
        client.post("/chat", json={"message": "begin", "session_id": sid})
    assert dump_of(tmp_path, "a") and dump_of(tmp_path, "b")
    client.put("/history/g/save", params={"session_id": "a"})
    assert [h["name"] for h in client.get("/history").json()["histories"]] == ["g"]


def test_the_dump_can_be_turned_off(tmp_path):
    client = make_client(tmp_path, AIGM_WORLD_DUMP="false")
    chat(client, "begin")
    assert not (tmp_path / "worlds").exists()


def test_curator_pass_changes_reach_the_dump(tmp_path):
    client = make_client(tmp_path, world_every_pages=0.05, world_page_chars=100)
    chat(client, "begin")
    chat(client, "echo [[fact: Wren:npc | Wren tends the bar at the Rusty Flagon.]] " + "x" * 120)
    assert "Wren" in {e["name"] for e in dump_of(tmp_path)["entities"]}


# ---- the command-line helper --------------------------------------------------------------


async def save_game(tmp_path, world):
    await HistoryRepository(tmp_path).save(
        "mygame",
        [{"role": "user", "content": [{"type": "text", "text": "hi"}]}, {"role": "assistant", "content": [{"type": "text", "text": "yo"}]}],
        GameState(Phase.ADVENTURE, {"setting": "x"}, world),
        "m",
    )


async def test_cli_renders_a_save_file(tmp_path, w, capsys):
    await save_game(tmp_path, w)
    assert main(["mygame", "--save-dir", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["counts"]["facts"] == 4 and any(e["name"] == "Harrow Mine" for e in out["entities"])
    assert main([str(tmp_path / "mygame.json"), "--known-only"]) == 0
    known = json.loads(capsys.readouterr().out)
    assert [e["name"] for e in known["entities"]] == ["Harrow Mine"]


def test_cli_reports_missing_and_broken_saves(tmp_path, capsys):
    assert main(["nope", "--save-dir", str(tmp_path)]) == 1
    assert "No such save" in capsys.readouterr().err
    (tmp_path / "bad.json").write_text(json.dumps({"world": {"time": {"day": 0, "hour": 0}}}))
    assert main(["bad", "--save-dir", str(tmp_path)]) == 1
    assert "Cannot read" in capsys.readouterr().err
    (tmp_path / "old.json").write_text("{not json")
    assert main(["old", "--save-dir", str(tmp_path)]) == 1


def test_cli_handles_saves_with_no_world(tmp_path, capsys):
    (tmp_path / "v2.json").write_text(json.dumps({"version": 2, "messages": []}))
    assert main(["v2", "--save-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["entities"] == []


def test_the_dump_lists_digests_for_the_gm_view_only():
    from aigm.world import Digest

    w = World()
    w.add_digest(Digest(2, 4, 2, "The party met Wren."))
    assert dump_world(w)["digests"] == ["turn 2 (messages 2-3): The party met Wren."]
    assert "digests" not in dump_world(w, known_only=True) and "digests" not in dump_world(World())
