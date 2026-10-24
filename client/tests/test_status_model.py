"""The status screen's model: how a status page is laid out (docs/STATUS.md 8)."""

from aigm_client.status_model import NO_LOCATION, StatusModel
from tests.fake_server import sample_status


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
    assert lines[at + 1].split() == ["Name", "Who"]
    assert lines[at + 2].split() == ["Toby", "Party,", "level", "3"]
    assert lines[at + 3].startswith("Galvin")


def test_a_long_cell_wraps_under_its_column():
    narrow = text_of(loaded(), width=40).splitlines()
    at = narrow.index("Everyone here")
    elian = [i for i, line in enumerate(narrow) if i > at and line.startswith("Elian")][0]
    assert narrow[elian + 1].startswith(" " * 8) and all(len(line) <= 42 for line in narrow)


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
