"""Turn digests: stored with the world, written by the curator pass, saved next to the messages."""

import json

import pytest

from aigm.errors import CorruptSave
from aigm.history import turns
from aigm.session.persistence import HistoryRepository
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.world import Digest, World
from aigm.world.curator import Extraction
from aigm.world.ops import AddDigest, apply_ops
from aigm.world.passes import PassConfig, run_pass
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService
from tests.test_world_pass import FakeCurator, convo


def history(n):
    return convo(*[f"The GM narrates part {i} of the story. [[at: Ashby:location]]" for i in range(n)])


# ---- storage ------------------------------------------------------------------------------


def test_a_turn_keeps_its_first_digest_and_overlaps_are_refused():
    w = World()
    assert w.add_digest(Digest(2, 4, 2, "first")) and w.version == 1
    assert not w.add_digest(Digest(2, 4, 2, "second")) and w.digests[2].text == "first"
    assert not w.add_digest(Digest(3, 5, 3, "overlaps")) and w.add_digest(Digest(4, 6, 3, "next"))
    assert w.version == 2


def test_digests_survive_copy_and_dict_round_trip():
    w = World()
    w.add_digest(Digest(4, 6, 3, "later", 120))
    w.add_digest(Digest(2, 4, 2, "earlier", 80))
    assert [d["turn"] for d in w.to_dict()["digests"]] == [2, 3]  # in message order
    assert World.from_dict(w.to_dict()) == w and w.copy().digests == w.digests


def test_a_world_without_the_digests_key_loads_empty():
    data = World().to_dict()
    del data["digests"]
    assert World.from_dict(data).digests == {}


@pytest.mark.parametrize(
    "bad",
    [
        [{"start": 2, "end": 2, "turn": 1, "text": "x"}],
        [{"start": 2, "end": 4, "turn": 1, "text": " "}],
        [{"start": "2", "end": 4, "turn": 1, "text": "x"}],
        [{"start": 2, "end": 6, "turn": 1, "text": "x"}, {"start": 4, "end": 8, "turn": 2, "text": "y"}],
        ["not an object"],
    ],
)
def test_malformed_digests_make_the_save_corrupt(bad):
    data = World().to_dict()
    data["digests"] = bad
    with pytest.raises(CorruptSave):
        World.from_dict(data)


async def test_a_save_keeps_the_original_messages_and_the_digests(tmp_path):
    messages = history(5)
    state = GameState(Phase.ADVENTURE, {"setting": "x"})
    state.world.add_digest(Digest(2, 4, 2, "The party reached Ashby.", 500))
    repo = HistoryRepository(tmp_path)
    await repo.save("g", messages, state, "m")
    saved = json.loads((tmp_path / "g.json").read_text(encoding="utf-8"))
    assert saved["messages"] == messages
    assert saved["world"]["digests"] == [
        {"start": 2, "end": 4, "turn": 2, "text": "The party reached Ashby.", "chars": 500}
    ]
    loaded_messages, loaded, _ = await repo.load("g")
    assert loaded_messages == messages and loaded.world.digests == state.world.digests


async def test_an_older_save_without_digests_still_loads(tmp_path):
    state = GameState(Phase.ADVENTURE, {"setting": "x"})
    repo = HistoryRepository(tmp_path)
    await repo.save("g", history(2), state, "m")
    path = tmp_path / "g.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["world"]["digests"]
    path.write_text(json.dumps(data), encoding="utf-8")
    _, loaded, _ = await repo.load("g")
    assert loaded.world.digests == {}


# ---- the curator pass ---------------------------------------------------------------------


def applied(ops):
    return [op.digest for op in ops if isinstance(op, AddDigest)]


async def test_a_pass_digests_every_finished_turn_except_the_first():
    messages = history(4)
    result = await run_pass(World(), messages, ScriptedCurator())
    digests = applied(result.ops)
    assert [(d.start, d.end, d.turn) for d in digests] == [(2, 4, 2), (4, 6, 3), (6, 8, 4)]
    assert all(d.text.startswith("The player: action") and "The GM: The GM narrates" in d.text for d in digests)
    assert "[[" not in digests[0].text and digests[0].chars > 0


async def test_digests_are_not_written_twice():
    messages = history(4)
    world = World()
    first = await run_pass(world, messages, ScriptedCurator())
    apply_ops(world, first.ops)
    curator = ScriptedCurator()
    second = await run_pass(world, messages + history(1), curator)
    assert [d.turn for d in applied(second.ops)] == [5] and curator.calls.count("digest") == 1


async def test_an_old_save_is_caught_up_in_batches_oldest_first():
    messages = history(30)
    config = PassConfig(max_digest_turns=10, digest_batch=4)
    curator = ScriptedCurator()
    world = World()
    result = await run_pass(world, messages, curator, config=config)
    assert [d.turn for d in applied(result.ops)] == list(range(2, 12))
    assert curator.calls.count("digest") == 3  # 4 + 4 + 2 turns
    apply_ops(world, result.ops)
    again = await run_pass(world, messages, curator, config=config)
    assert [d.turn for d in applied(again.ops)] == list(range(12, 22))


async def test_digests_can_be_switched_off():
    curator = ScriptedCurator()
    result = await run_pass(World(), history(4), curator, config=PassConfig(digests=False))
    assert applied(result.ops) == [] and "digest" not in curator.calls


async def test_a_curator_that_cannot_digest_is_fine():
    result = await run_pass(World(), history(4), FakeCurator(Extraction()))
    assert applied(result.ops) == [] and result.ops  # the rest of the pass still ran


class Flaky(FakeCurator):
    def __init__(self, behavior):
        super().__init__()
        self.behavior = behavior

    async def digest(self, request):
        return self.behavior(request)


async def test_a_failing_digest_call_does_not_fail_the_pass():
    def boom(request):
        raise RuntimeError("model down")

    result = await run_pass(World(), history(4), Flaky(boom))
    assert applied(result.ops) == [] and any("model down" in n for n in result.notes)
    assert result.ops  # MarkProcessed is still there


async def test_wrong_counts_and_empty_digests_are_skipped():
    result = await run_pass(World(), history(4), Flaky(lambda r: ["only one"]))
    assert applied(result.ops) == [] and any("expected 3" in n for n in result.notes)
    result = await run_pass(World(), history(4), Flaky(lambda r: ["ok", "  ", "fine " * 400]))
    got = applied(result.ops)
    assert [d.turn for d in got] == [2, 4] and got[1].text.endswith("…") and len(got[1].text) <= 700


async def test_the_service_stores_digests_on_the_session():
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, {"setting": "x"})
    session.messages = history(6)
    svc = CuratorService(ScriptedCurator(), every_pages=1, page_chars=10)
    assert await svc.run_if_due(session)
    assert sorted(d.turn for d in session.state.world.digests.values()) == [2, 3, 4, 5, 6]
    for t in turns(session.messages)[1:]:
        assert session.state.world.digests[t.start].end == t.end
