"""Choosing the ruleset in Session 0 (docs/RULESETS.md)."""

import json

import pytest

from aigm import rulesets
from aigm.game import Game
from aigm.prompts import PromptLibrary
from aigm.rulesets import BY_ID, DEFAULT_RULESET, RULESETS
from aigm.session.persistence import HistoryRepository
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch, tool_schemas
from tests.conftest import chat, names, reply_text

IDS = [r.id for r in RULESETS]
DESCENDING_AC = {"odnd", "basic", "becmi", "adnd1e", "adnd2e"}


# ---- the catalog and its prompts -------------------------------------------------------------------


def test_catalog_has_dnd_editions_and_pathfinder_with_5_5e_as_default():
    assert DEFAULT_RULESET == "dnd55e" and len(set(IDS)) == len(IDS)
    assert {r.family for r in RULESETS} == {"D&D", "Pathfinder"}
    dnd_years = sorted(r.year for r in RULESETS if r.family == "D&D")
    assert dnd_years[0] == 1974 and dnd_years[-1] == 2024
    assert {"pf1e", "pf2e"} <= set(IDS)
    assert rulesets.get("adnd1e").short == "AD&D 1e"
    with pytest.raises(ValueError):
        rulesets.get("nope")


@pytest.mark.parametrize("ruleset", IDS)
def test_every_ruleset_has_rules_and_period_feel(ruleset):
    parts = PromptLibrary().ruleset_parts(ruleset)
    assert [p.source for p in parts] == [f"rulesets/{ruleset}/01_rules.md", f"rulesets/{ruleset}/02_era.md"]
    rules, era = (p.text for p in parts)
    assert rules.startswith("## Ruleset: ") and len(rules) > 1500
    assert era.startswith("### Period feel") and len(era) > 800
    assert "<!--" not in rules + era


@pytest.mark.parametrize("ruleset", IDS)
def test_armor_class_convention_is_stated(ruleset):
    rules = PromptLibrary().ruleset_parts(ruleset)[0].text.lower()
    if ruleset in DESCENDING_AC:
        assert "descending" in rules and "lower is better" in rules
    else:
        assert "ascending" in rules or "higher" in rules


def test_first_edition_leans_on_the_late_seventies_and_early_eighties():
    era = PromptLibrary().ruleset_parts("adnd1e")[1].text
    assert "late 1970s and early 1980s" in era and "Gygaxian" in era
    assert "backward AC" in PromptLibrary().ruleset_parts("adnd1e")[0].text


def test_system_prompt_swaps_the_ruleset_between_common_and_mode_parts():
    lib = PromptLibrary()
    for phase in Phase:
        text = lib.system_prompt(phase, "adnd1e")
        assert "## Ruleset: Advanced D&D, 1st Edition" in text and "Ruleset: D&D 5.5e" not in text
        mode = "## Current mode: Adventure" if phase is Phase.ADVENTURE else "## Current mode: Session 0"
        assert text.index("## Dice") < text.index("## Ruleset: ") < text.index(mode)
    assert lib.system_prompt(Phase.ADVENTURE) == lib.system_prompt(Phase.ADVENTURE, DEFAULT_RULESET)


def test_the_session_zero_choice_text_lists_every_ruleset():
    text = PromptLibrary().system_prompt(Phase.SESSION_ZERO)
    assert "## Choosing the ruleset" in text and "set_ruleset" in text
    for needle in ("Original D&D (1974)", "B/X", "BECMI", "AD&D 1st Edition", "AD&D 2nd Edition", "3rd Edition",
                   "3.5 Edition", "4th Edition", "5th Edition (2014)", "5.5e (2024)", "Pathfinder: 1st Edition",
                   "2nd Edition (2019"):
        assert needle in text, needle


def test_generic_prompts_name_no_edition_specifics():
    lib = PromptLibrary()
    for phase in Phase:
        generic = "\n\n".join(p.text for p in lib.system_parts(phase) if not p.source.startswith("rulesets/"))
        for stale in ("Hit Dice", "death saving", "Weapon Mastery", "2024 way"):
            assert stale not in generic, stale


# ---- the tool --------------------------------------------------------------------------------------


def test_set_ruleset_is_offered_only_in_session_zero_with_every_id():
    zero = {t["name"]: t for t in tool_schemas(PromptLibrary(), Phase.SESSION_ZERO)}
    assert "set_ruleset" in zero and "set_ruleset" not in {t["name"] for t in tool_schemas(PromptLibrary(), Phase.ADVENTURE)}
    assert zero["set_ruleset"]["input_schema"]["properties"]["ruleset"]["enum"] == IDS
    assert "Choose the ruleset" in zero["set_ruleset"]["description"]


def test_set_ruleset_changes_state_and_says_what_changed():
    state = GameState()
    out = dispatch("set_ruleset", "t1", {"ruleset": "adnd1e"}, state)
    assert not out.is_error and state.ruleset == "adnd1e" and "Advanced D&D, 1st Edition" in out.content
    assert "rebuilt" in out.content
    again = dispatch("set_ruleset", "t2", {"ruleset": "adnd1e"}, state)
    assert not again.is_error and "nothing changed" in again.content


@pytest.mark.parametrize("bad", [{"ruleset": "nope"}, {}, {"ruleset": 5}, {"ruleset": None}])
def test_set_ruleset_rejects_unknown_ids(bad):
    state = GameState()
    out = dispatch("set_ruleset", "t", bad, state)
    assert out.is_error and state.ruleset == DEFAULT_RULESET and "dnd55e" in out.content


def test_set_ruleset_is_refused_once_the_adventure_has_begun():
    state = GameState(Phase.ADVENTURE, {"setting": "x"})
    out = dispatch("set_ruleset", "t", {"ruleset": "adnd1e"}, state)
    assert out.is_error and state.ruleset == DEFAULT_RULESET  # unknown to this phase: nothing changes


def test_the_game_builds_the_prompt_from_the_states_ruleset():
    game = Game()
    zero = GameState(ruleset="pf2e")
    assert "Ruleset: Pathfinder, 2nd Edition" in game.system(zero)
    assert [p.source for p in game.system_parts(zero) if p.source.startswith("rulesets/")][0] == "rulesets/pf2e/01_rules.md"
    adventure = GameState(Phase.ADVENTURE, {"setting": "x"}, ruleset="odnd")
    assert "Original D&D" in game.system(adventure) and "Pathfinder" not in game.system(adventure).split("## Ruleset")[1][:200]


def test_campaign_record_names_the_ruleset():
    lib = PromptLibrary()
    campaign = {"setting": "s", "opening": "o", "level": 1, "party": [{"name": "A", "sheet": "x"}]}
    assert "### Ruleset\n\nD&D 5.5 Edition (the 2024 revision)" in lib.campaign_record(campaign)
    assert "### Ruleset\n\nAdvanced D&D, 1st Edition" in lib.campaign_record(campaign, "adnd1e")


# ---- state and saves -------------------------------------------------------------------------------


def test_state_round_trips_and_copies_the_ruleset():
    state = GameState(ruleset="adnd2e")
    assert state.to_dict()["ruleset"] == "adnd2e"
    assert GameState.from_dict(state.to_dict()).ruleset == "adnd2e"
    assert state.copy().ruleset == "adnd2e"


def test_older_saves_without_a_ruleset_are_dnd_2024():
    assert GameState.from_dict({"phase": "adventure", "campaign": {"setting": "x"}}).ruleset == "dnd55e"
    assert GameState.from_dict({"messages": []}).ruleset == "dnd55e"


def test_a_save_with_an_unknown_ruleset_is_corrupt():
    from aigm.errors import CorruptSave

    with pytest.raises(CorruptSave):
        GameState.from_dict({"phase": "session_zero", "ruleset": "dnd9e"})


async def test_the_ruleset_survives_save_and_restore(tmp_path):
    repo = HistoryRepository(tmp_path)
    state = GameState(ruleset="pf1e")
    await repo.save("g", [], state, "m")
    assert json.loads((tmp_path / "g.json").read_text())["ruleset"] == "pf1e"
    _, loaded, _ = await repo.load("g")
    assert loaded.ruleset == "pf1e"


# ---- over HTTP, in test mode -----------------------------------------------------------------------


def current(client, sid="default"):
    return client.get("/chat/history", params={"session_id": sid}).json()


def test_a_new_game_defaults_to_5_5e(client):
    state = current(client)
    assert state["ruleset"] == "dnd55e" and state["ruleset_name"] == "D&D 5.5e"
    events = chat(client, "echo hi")
    assert events[0][1]["ruleset"] == "dnd55e" and events[-1][1]["ruleset_name"] == "D&D 5.5e"


def test_choosing_a_ruleset_mid_turn_is_reported_at_the_end_and_used_next(client, app):
    events = chat(client, "ruleset adnd1e")
    assert "set_ruleset" in [d["name"] for n, d in events if n == "tool_call"]
    assert events[0][1]["ruleset"] == "dnd55e"  # the turn started under the default
    assert events[-1][1]["ruleset"] == "adnd1e" and events[-1][1]["ruleset_name"] == "AD&D 1e"
    assert current(client)["ruleset"] == "adnd1e"
    assert app.state.sessions.get("default").state.ruleset == "adnd1e"
    assert chat(client, "echo again")[0][1]["ruleset_name"] == "AD&D 1e"


def test_a_failed_turn_does_not_keep_the_new_ruleset(client, app):
    session = app.state.sessions.get("default")
    session.state = GameState()
    chat(client, "ruleset nope")  # the tool reports an error and nothing changes
    assert session.state.ruleset == "dnd55e"


def test_the_ruleset_carries_into_the_adventure_and_cannot_change(client):
    chat(client, "ruleset pf2e")
    events = chat(client, "begin")
    assert "phase_change" in names(events)
    assert current(client)["ruleset"] == "pf2e"
    record = current(client)["messages"][1]["content"][0]["text"]
    assert "### Ruleset\n\nPathfinder, 2nd Edition (Remaster)" in record
    after = chat(client, "ruleset adnd1e")
    assert "cannot" in reply_text(after).lower() or "fixed" in reply_text(after).lower()
    assert current(client)["ruleset"] == "pf2e"


def test_new_game_goes_back_to_the_default(client):
    chat(client, "ruleset adnd2e")
    body = client.post("/chat/new").json()
    assert body["ruleset"] == "dnd55e" and current(client)["ruleset"] == "dnd55e"


def test_save_and_restore_over_http_keep_the_ruleset(client):
    chat(client, "ruleset becmi")
    assert client.put("/history/g/save").status_code == 200
    client.post("/chat/new")
    restored = client.post("/history/g/restore").json()
    assert restored["ruleset"] == "becmi" and current(client)["ruleset"] == "becmi"
