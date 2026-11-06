"""The prompts that teach the GM about attempts (docs/ATTEMPTS.md 8)."""

import pytest

from aigm.game import Game
from aigm.prompts import PromptLibrary
from aigm.rulesets import RULESETS
from aigm.session.state import GameState, Phase
from aigm.tools import tool_schemas

LIB = PromptLibrary()


@pytest.mark.parametrize("ruleset", [r.id for r in RULESETS])
def test_every_ruleset_has_an_attempts_file_for_the_adventure_only(ruleset):
    adventure = [p.source for p in LIB.system_parts("adventure", ruleset)]
    session_zero = [p.source for p in LIB.system_parts("session_zero", ruleset)]
    assert f"rulesets/{ruleset}/04_attempts.md" in adventure
    assert f"rulesets/{ruleset}/04_attempts.md" not in session_zero
    assert adventure.index(f"rulesets/{ruleset}/04_attempts.md") > adventure.index(f"rulesets/{ruleset}/03_roleplay.md")
    text = next(p.text for p in LIB.system_parts("adventure", ruleset) if p.source.endswith("04_attempts.md"))
    assert text.startswith("### Failed attempts") and ("DC" in text or "`dc`" in text) and "changed approach" in text


@pytest.mark.parametrize("r", [r for r in RULESETS if r.social_style == "reaction"], ids=lambda r: r.id)
def test_the_old_editions_roll_under(r):
    text = next(p.text for p in LIB.system_parts("adventure", r.id) if p.source.endswith("04_attempts.md"))
    assert "`dc_mode: under`" in text


@pytest.mark.parametrize("r", [r for r in RULESETS if r.social_style != "reaction"], ids=lambda r: r.id)
def test_the_later_editions_roll_over(r):
    text = next(p.text for p in LIB.system_parts("adventure", r.id) if p.source.endswith("04_attempts.md"))
    assert "**over**" in text and "dc_mode" not in text


def test_the_base_prompt_gives_the_reasoning():
    prompt = Game().system(GameState(Phase.ADVENTURE, {"setting": "x"}))
    assert "### Failed attempts" in prompt and "Three questions" in prompt and "No free retries" in prompt
    assert "A closed attempt stays closed" in prompt


def test_the_tool_descriptions_explain_the_attempt():
    tools = {t["name"]: t for t in tool_schemas()}
    assert "`attempt` says what the roll is for" in tools["roll_dice"]["description"]
    assert "`failure`" in tools["social_check"]["description"]
    assert "attempt" in tools["roll_dice"]["input_schema"]["properties"]
    assert "failure" in tools["social_check"]["input_schema"]["properties"]


def test_playtest_mode_leaves_the_attempt_rules_out():
    state = GameState(Phase.ADVENTURE, {"setting": "x"})
    state.playtest = True
    prompt = Game().system(state)
    assert "### Failed attempts" not in prompt
