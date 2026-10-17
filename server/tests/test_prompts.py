import pytest

from aigm.prompts import PromptLibrary
from aigm.session.state import Phase


def test_adventure_prompt_is_assembled_in_order():
    prompt = PromptLibrary().system_prompt(Phase.ADVENTURE)
    assert prompt.startswith("You are the Game Master")
    assert prompt.index("## Using the rules") < prompt.index("## Dice") < prompt.index("## Ruleset: ")
    assert prompt.index("## Ruleset: ") < prompt.index("## Current mode: Adventure")
    assert prompt.index("## Current mode: Adventure") < prompt.index("## Running the game") < prompt.index("## Style")
    assert "<!--" not in prompt  # authoring comments are stripped


def test_session_zero_prompt_has_only_session_zero_material():
    prompt = PromptLibrary().system_prompt(Phase.SESSION_ZERO)
    assert prompt.startswith("You are the Game Master")
    assert "## Current mode: Session 0" in prompt and "begin_adventure" in prompt
    assert "## Matching the setting to the party" in prompt
    assert "## Current mode: Adventure" not in prompt and "## Running the game" not in prompt
    assert "## Using the rules" in prompt and "## Dice" in prompt  # shared parts


def test_adventure_prompt_has_no_session_zero_material():
    prompt = PromptLibrary().system_prompt(Phase.ADVENTURE)
    assert "## Finishing Session 0" not in prompt and "## The party" not in prompt


def test_phase_prompts_differ_by_string_or_enum():
    lib = PromptLibrary()
    assert lib.system_prompt("session_zero") == lib.system_prompt(Phase.SESSION_ZERO) != lib.system_prompt("adventure")
    with pytest.raises(ValueError):
        lib.system_prompt("nope")


def test_tool_description_comes_from_file():
    assert "Roll dice" in PromptLibrary().tool_description("roll_dice")
    assert "cannot be undone" in PromptLibrary().tool_description("begin_adventure")
    with pytest.raises(ValueError):
        PromptLibrary().tool_description("nope")


CAMPAIGN = {
    "setting": "Misty fens.",
    "opening": "At the inn.",
    "level": 3,
    "party": [
        {"name": "Ann", "sheet": "Rogue sheet."},
        {"name": "Bo", "sheet": "Cleric sheet."},
    ],
    "gm_notes": "The mist lies.",
}


def test_campaign_record_renders_setting_party_and_opening():
    text = PromptLibrary().campaign_record(CAMPAIGN)
    assert text.startswith("## Campaign record")
    assert text.index("Misty fens.") < text.index("Ann") < text.index("At the inn.")
    assert "#### Bo" in text and "Cleric sheet." in text
    assert "2 character(s), starting at level 3" in text
    assert "The mist lies." not in text and "{{" not in text


def test_gm_notes_section():
    lib = PromptLibrary()
    assert "The mist lies." in lib.gm_notes_section(CAMPAIGN)
    assert lib.gm_notes_section({**CAMPAIGN, "gm_notes": None}) == "" == lib.gm_notes_section(None)


def test_record_text_is_not_treated_as_a_template():
    text = PromptLibrary().campaign_record({**CAMPAIGN, "setting": "{{opening}}"})
    assert "{{opening}}" in text


def test_override_dir_replaces_and_adds(tmp_path):
    (tmp_path / "system" / "common").mkdir(parents=True)
    (tmp_path / "system" / "common" / "01_role.md").write_text("You are a PIRATE GM.")
    (tmp_path / "system" / "adventure").mkdir()
    (tmp_path / "system" / "adventure" / "05_extra.md").write_text("Extra rule.\n<!-- note -->")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "roll_dice.md").write_text("Custom dice text.")
    lib = PromptLibrary(tmp_path)
    prompt = lib.system_prompt(Phase.ADVENTURE)
    assert prompt.startswith("You are a PIRATE GM.") and "Game Master (GM)" not in prompt.split("\n\n")[0]
    assert "## Core rules" in prompt  # packaged parts that were not overridden remain
    assert prompt.endswith("Extra rule.")
    assert "Extra rule." not in lib.system_prompt(Phase.SESSION_ZERO)
    assert lib.tool_description("roll_dice") == "Custom dice text."


def test_empty_system_prompt_is_an_error(tmp_path, monkeypatch):
    import aigm.prompts as p

    monkeypatch.setattr(p, "PACKAGED_DIR", tmp_path)
    for phase in Phase:
        with pytest.raises(ValueError):
            p.PromptLibrary().system_prompt(phase)
