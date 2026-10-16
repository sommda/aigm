import pytest

from aigm.prompts import PromptLibrary


def test_packaged_system_prompt_is_assembled_in_order():
    prompt = PromptLibrary().system_prompt()
    assert prompt.startswith("You are the Game Master")
    assert prompt.index("## Rules") < prompt.index("## Dice") < prompt.index("## Style")
    assert "<!--" not in prompt  # authoring comments are stripped


def test_tool_description_comes_from_file():
    assert "Roll dice" in PromptLibrary().tool_description("roll_dice")
    with pytest.raises(ValueError):
        PromptLibrary().tool_description("nope")


def test_override_dir_replaces_and_adds(tmp_path):
    (tmp_path / "system").mkdir()
    (tmp_path / "system" / "01_role.md").write_text("You are a PIRATE GM.")
    (tmp_path / "system" / "05_extra.md").write_text("Extra rule.\n<!-- note -->")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "roll_dice.md").write_text("Custom dice text.")
    lib = PromptLibrary(tmp_path)
    prompt = lib.system_prompt()
    assert prompt.startswith("You are a PIRATE GM.") and "Game Master" not in prompt.split("\n\n")[0]
    assert "## Rules" in prompt  # packaged parts that were not overridden remain
    assert prompt.endswith("Extra rule.")
    assert lib.tool_description("roll_dice") == "Custom dice text."


def test_empty_system_prompt_is_an_error(tmp_path, monkeypatch):
    import aigm.prompts as p

    monkeypatch.setattr(p, "PACKAGED_DIR", tmp_path)
    with pytest.raises(ValueError):
        p.PromptLibrary().system_prompt()
