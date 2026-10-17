"""Optional smoke test against the real Anthropic API. Costs a little money, so it only runs
when explicitly enabled:  AIGM_LIVE_TESTS=1 ANTHROPIC_API_KEY=... uv run pytest tests/test_live.py -s"""

import os

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from tests.conftest import chat, names, reply_text

pytestmark = pytest.mark.skipif(
    os.environ.get("AIGM_LIVE_TESTS") != "1", reason="set AIGM_LIVE_TESTS=1 (and ANTHROPIC_API_KEY) to run"
)


def test_live_turn_with_dice(tmp_path):
    client = TestClient(create_app(Settings(test_mode=False, save_dir=tmp_path)))
    events = chat(client, "Start a quick game. I'm a human fighter. As my first action, I attack a nearby rat: roll my attack now.")
    print(reply_text(events))
    assert names(events)[-1] == "message_end"
    assert "dice_roll" in names(events)
    assert len(client.get("/chat/history").json()["messages"]) >= 4


async def test_live_curator_grows_an_independent_world():
    from aigm.prompts import PromptLibrary
    from aigm.world.anthropic_curator import AnthropicCurator
    from aigm.world.independence import independence_problem
    from aigm.world.ops import apply_ops
    from aigm.world.passes import PassConfig, run_pass
    from aigm.world.sample import SETTING, render, seed

    s = Settings(test_mode=False)
    curator = AnthropicCurator(
        api_key=s.anthropic_api_key, prompts=PromptLibrary(), model=s.world_model, expand_model=s.world_expand_model
    )
    world = seed()
    result = await run_pass(world, [], curator, setting=SETTING, party_names=["Test Hero"], config=PassConfig())
    applied = apply_ops(world, result.ops)
    print(render(world), "\n", result.notes, applied.skipped)
    generated = [f for f in world.facts.values() if f.source == "generated"]
    assert len(generated) >= 5 and all(f.disclosure == "hidden" for f in generated)
    assert all(independence_problem(f.text, ["Test Hero"]) is None for f in generated)
    for ent in world.entities.values():  # everything is connected to the seeded world
        assert ent.id in world.distances(world.scene.location)
