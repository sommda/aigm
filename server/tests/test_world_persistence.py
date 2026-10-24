import json

import pytest

from aigm.errors import CorruptSave
from aigm.session.persistence import HistoryRepository
from aigm.session.state import GameState, Phase
from aigm.world import World, WorldTime

MESSAGES = [
    {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
]


def adventure_state():
    state = GameState(Phase.ADVENTURE, {"setting": "x"})
    w = state.world
    town = w.add_entity("Ashby", "location")
    mine = w.add_entity("Harrow Mine", "location", aliases=["the old mine"], parent=town.id)
    w.add_fact("The Harrow Mine was abandoned forty years ago.", [mine.id, town.id], disclosure="known", turn=1)
    w.add_fact("The mine's lower gallery joins a cellar under Ashby.", [mine.id], aspect="secret")
    w.set_scene(mine.id)
    w.advance_time(30)
    w.mark_processed(2)
    return state


@pytest.fixture
def repo(tmp_path):
    return HistoryRepository(tmp_path / "saves")


async def test_world_round_trips_through_a_save(repo):
    state = adventure_state()
    await repo.save("g", MESSAGES, state, "m")
    _, loaded, info = await repo.load("g")
    assert loaded.world == state.world and loaded.world.find("old mine").name == "Harrow Mine"
    assert loaded.world.processed_through == 2 and loaded.world.time == WorldTime(2, 14)
    assert (info["entity_count"], info["fact_count"], info["world_time"]) == (2, 2, {"day": 2, "hour": 14})


async def test_saves_are_pretty_printed_not_one_line(repo):
    await repo.save("g", MESSAGES, adventure_state(), "m")
    text = (repo.dir / "g.json").read_text(encoding="utf-8")
    assert text.count("\n") > 50 and text.endswith("}\n")
    assert '\n    "facts": [' in text or '\n  "world": {' in text
    assert json.loads(text)["version"] == 7


async def test_listing_includes_world_counts(repo):
    await repo.save("g", MESSAGES, adventure_state(), "m")
    (entry,) = await repo.list_all()
    assert entry["fact_count"] == 2 and entry["entity_count"] == 2


async def test_save_snapshots_the_world(repo):
    state = adventure_state()
    await repo.save("g", MESSAGES, state, "m")
    state.world.add_entity("Wren", "npc")  # later changes must not leak into the file
    _, loaded, _ = await repo.load("g")
    assert loaded.world.find("Wren") is None


def write_raw(repo, name, **fields):
    repo.dir.mkdir(parents=True, exist_ok=True)
    data = {"version": 3, "name": name, "messages": MESSAGES, **fields}
    (repo.dir / f"{name}.json").write_text(json.dumps(data))


async def test_older_saves_load_with_an_empty_world(repo):
    write_raw(repo, "v1", version=1)
    write_raw(repo, "v2", version=2, phase="adventure", campaign={"setting": "x"})
    for name in ("v1", "v2"):
        _, state, info = await repo.load(name)
        assert state.phase is Phase.ADVENTURE and state.world.is_empty and info["fact_count"] == 0


async def test_corrupt_world_in_a_save_is_rejected_and_skipped_in_listing(repo):
    await repo.save("good", MESSAGES, adventure_state(), "m")
    write_raw(repo, "bad", phase="adventure", campaign={}, world={"time": {"day": 0, "hour": 0}})
    with pytest.raises(CorruptSave, match="world"):
        await repo.load("bad")
    assert [h["name"] for h in await repo.list_all()] == ["good"]


def test_session_zero_cannot_carry_a_world():
    data = {"phase": "session_zero", "campaign": None, "world": adventure_state().world.to_dict()}
    with pytest.raises(CorruptSave, match="session_zero"):
        GameState.from_dict(data)
    assert GameState.from_dict({"phase": "session_zero", "world": World().to_dict()}).world.is_empty


def test_state_copy_deep_copies_the_world():
    state = adventure_state()
    copy = state.copy()
    copy.world.add_entity("Wren", "npc")
    assert state.world.find("Wren") is None and copy != state
    assert state.copy() == state


def test_save_and_restore_over_http(client):
    client.put("/history/s0/save")
    info = client.get("/history/s0").json()
    assert info["fact_count"] == 0 and info["world_time"] == {"day": 1, "hour": 8}


async def test_a_story_is_saved_and_loaded(repo):
    from aigm.story import Goal, Story

    state = adventure_state()
    state.structure, state.story = "short", Story("short", goal=Goal("The Crown", "It binds the river."))
    await repo.save("s", MESSAGES, state, "m")
    _, loaded, _ = await repo.load("s")
    assert loaded.structure == "short" and loaded.story == state.story
    write_raw(repo, "v3", phase="adventure", campaign={"setting": "x"})  # a version 3 save has neither
    _, old, _ = await repo.load("v3")
    assert old.structure == "endless" and old.story is None
    write_raw(repo, "bad", phase="adventure", campaign={}, structure="short", story={**state.story.to_dict(), "length": "long"})
    with pytest.raises(CorruptSave, match="short game cannot have a long"):
        await repo.load("bad")
