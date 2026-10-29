"""The status screen's model: how a status page is laid out (docs/STATUS.md 8)."""

from aigm_client.status_model import NO_LOCATION, StatusModel
from tests.fake_server import sample_characters, sample_status


def text_of(model: StatusModel, width: int = 80) -> str:
    return "\n".join(t.plain for t in model.lines(width))


def loaded(width: int = 80, ascii_only: bool = False, **changes) -> StatusModel:
    model = StatusModel(ascii_only)
    model.load("status", {**sample_status(), **changes})
    return model


def test_the_page_names_and_describes_the_place_then_lists_what_is_there():
    text = text_of(loaded())
    lines = text.splitlines()
    assert lines[0] == "The Docks" and lines[1] == "in Port Veyra  ·  Day 1, 18:00 · evening"
    assert "Gulls wheel over wet planks" in text
    for heading in ("Here", "Key items", "Inside", "Ways out", "Everyone here"):
        assert heading in lines
    assert "· Elian —" in text and "A barred cargo hatch." in text
    assert "· Customs House —" in text and "Up Dock Street from the Docks." in text


def test_the_table_has_a_header_and_a_row_each():
    lines = text_of(loaded()).splitlines()
    at = lines.index("Everyone here")
    assert lines[at + 1].split() == ["Name", "HP", "Conditions", "Who"]
    assert lines[at + 2].split() == ["Toby", "11/15", "prone", "Party,", "level", "3"]
    assert lines[at + 3].startswith("Galvin")


def test_a_long_cell_wraps_under_its_column():
    narrow = text_of(loaded(), width=40).splitlines()
    at = narrow.index("Everyone here")
    elian = [i for i, line in enumerate(narrow) if i > at and line.startswith("Elian")][0]
    assert narrow[elian + 1].startswith(" " * 18) and all(len(line) <= 42 for line in narrow)


def test_a_section_with_nothing_in_it_is_left_out():
    text = text_of(loaded(items=[], inside=[], exits=[]))
    assert "Key items" not in text and "Inside" not in text and "Ways out" not in text and "Here" in text


def test_a_place_without_a_description_still_shows():
    page = sample_status()
    page["location"]["overview"] = None
    model = StatusModel()
    model.load("status", page)
    assert text_of(model).startswith("The Docks")


def test_no_location_still_shows_the_party():
    text = text_of(loaded(location=None, here=[], items=[], inside=[], exits=[]))
    assert text.startswith(NO_LOCATION) and "Toby" in text


def test_ascii_marks_for_plain_terminals():
    text = text_of(loaded(ascii_only=True))
    assert "- Elian -" in text and "·" not in text and "—" not in text


def test_nothing_loaded_draws_nothing_and_the_tab_bar_names_the_status():
    model = StatusModel()
    assert model.lines(80) == [] and "Status" in model.tabs_text().plain
    assert model.switch(step=1) is False  # one tab only for now


def with_party() -> StatusModel:
    model = loaded()
    model.load_roster({"characters": [{"name": "Toby"}, {"name": "Galvin Stonehand"}]})
    return model


def test_each_party_member_gets_a_tab_named_by_first_name():
    model = with_party()
    assert [t for _, t in model.tabs] == ["Status", "Toby", "Galvin"]
    assert model.find_tab("toby") == "c:Toby" and model.find_tab("gal") == "c:Galvin Stonehand"
    assert model.find_tab("") is None and model.find_tab("zed") is None
    assert model.switch(step=1) and model.character == "Toby"
    assert model.switch(step=-1) and model.character is None


def test_a_character_page_shows_vitals_progress_and_sections():
    model = with_party()
    model.switch("c:Toby")
    model.load("c:Toby", sample_characters()["Toby"])
    lines = text_of(model).splitlines()
    assert lines[:4] == ["Toby", "Human Rogue 3", "HP 11/15  prone", "Level 3 (Rogue 3), 900 XP"]
    assert "Abilities" in lines and "  STR 10 (+0)   DEX 16 (+3)" in lines and "  12 gp, 4 sp" in lines


def test_a_long_line_on_a_sheet_wraps_with_a_hanging_indent():
    model = with_party()
    model.switch("c:Toby")
    page = sample_characters()["Toby"]
    page["sections"] = [{"title": "Features", "lines": ["Sneak Attack: " + "once per turn deal extra damage " * 3]}]
    model.load("c:Toby", page)
    lines = text_of(model, width=40).splitlines()
    at = lines.index("Features")
    assert lines[at + 1].startswith("  Sneak Attack") and lines[at + 2].startswith("    ")


def test_a_character_with_only_free_text_shows_it_with_a_note():
    model = with_party()
    model.switch("c:Galvin Stonehand")
    model.load("c:Galvin Stonehand", sample_characters()["Galvin Stonehand"])
    text = text_of(model)
    assert "No tidy version" in text and "  Dwarf Fighter with an axe." in text and "HP" not in text


def test_a_party_that_shrinks_returns_to_the_status_tab():
    model = with_party()
    model.switch("c:Galvin Stonehand")
    model.load_roster({"characters": [{"name": "Toby"}]})
    assert model.tab == "status"


def test_a_fight_retitles_the_table_and_shows_its_columns():
    table = {
        "columns": ["Name", "Side", "Health", "Conditions"],
        "rows": [["Toby", "Party", "11/15", "prone"], ["Wolf x3", "Foe", "bloodied", "-"]],
    }
    lines = text_of(loaded(combat={"foes": 3}, table=table)).splitlines()
    assert "Everyone here" not in lines
    at = lines.index("The fight")
    assert lines[at + 1].split() == ["Name", "Side", "Health", "Conditions"]
    assert lines[at + 2].split() == ["Toby", "Party", "11/15", "prone"]
    assert lines[at + 3].split() == ["Wolf", "x3", "Foe", "bloodied", "-"]


def test_a_character_page_shows_the_appearance_when_there_is_one():
    model = with_party()
    model.switch("c:Toby")
    page = {**sample_characters()["Toby"], "look": {"summary": "A lean man.", "description": "Toby is lean and tall."}}
    model.load("c:Toby", page)
    lines = text_of(model).splitlines()
    assert lines[lines.index("Appearance") + 1] == "  Toby is lean and tall."
    model.load("c:Toby", {**page, "look": None})
    assert "Appearance" not in text_of(model)
