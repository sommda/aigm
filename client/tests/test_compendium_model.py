"""The compendium model: lists, cursor, read marks, links and the lines drawn (pure, no terminal)."""

from aigm_client.compendium_model import CompendiumModel
from aigm_client.commands import parse_command
from aigm_client.session import ChatSession
from aigm_client.transcript import Transcript
from aigm_client import events as ev
from rich.text import Text


def row(i, name, status=None, depth=0, parent=None, summary=""):
    return {"id": i, "name": name, "status": status, "depth": depth, "parent": parent, "summary": summary, "kind": "x"}


def loaded(ascii_only=False, hidden=False) -> CompendiumModel:
    m = CompendiumModel(ascii_only, hidden)
    m.load_summary({"categories": [
        {"id": "locations", "count": 3, "new": 1, "updated": 1},
        {"id": "characters", "count": 1, "new": 0, "updated": 0},
        {"id": "other", "count": 1, "new": 1, "updated": 0},
    ]})
    m.load_list("locations", {"entries": [
        row("e001", "Ashby Vale"), row("e003", "Thornwood", "updated", 1, summary="A dark forest."),
        row("e007", "Harrow Mine", "new", 2),
    ]})
    m.load_list("characters", {"entries": [row("e010", "Wren")]})
    m.load_list("other", {"entries": [row("e020", "Thorn Guild", "new")]})
    return m


def plain(texts):
    return [t.plain for t in texts]


def test_the_tabs_show_counts_and_unread():
    text = loaded().tabs_text().plain
    assert "1 Locations (3) ✦2" in text and "2 Characters (1)" in text and "3 Other (1) ✦1" in text
    assert "*2" in loaded(True).tabs_text().plain


def test_list_lines_show_only_names_with_the_mark_tag_and_indent():
    m = loaded()
    m.move(1)
    lines, cursor = m.list_lines(40)
    text = plain(lines)
    assert cursor == 1 and len(text) == 3  # one line per entry: no description under the cursor
    assert text[1].startswith("✦   Thornwood") and text[1].endswith("updated")
    assert text[2].startswith("✦     Harrow Mine")
    assert "forest" not in " ".join(text)
    assert all(len(t) == 40 for t in text)


def test_ascii_mode_uses_plain_marks():
    m = loaded(True)
    m.move(1)
    assert plain(m.list_lines(40)[0])[1].startswith("*   Thornwood")


def test_long_names_are_cut_to_the_width():
    m = loaded()
    m.lists["locations"][0]["name"] = "A" * 80
    assert all(len(t) <= 30 for t in plain(m.list_lines(30)[0]))


def test_moving_stays_inside_the_list_and_tabs_wrap():
    m = loaded()
    m.move(-5)
    assert m.current_id == "e001"
    m.move(99)
    assert m.current_id == "e007"
    m.move_to(False)
    assert m.current_id == "e001"
    m.switch_tab(step=-1)
    assert m.tab == "other"
    m.switch_tab("characters")
    assert m.current_id == "e010"


def test_an_empty_tab_says_so():
    m = CompendiumModel()
    assert plain(m.list_lines(30)[0]) == ["Nothing is known yet."]
    m.query = "zzz"
    assert plain(m.list_lines(30)[0]) == ["No entries match."]


def test_reading_marks_keep_the_row_on_screen_but_drop_the_count():
    m = loaded()
    assert m.unread_count() == 3
    assert m.mark_read("e007") is True and m.mark_read("e007") is False
    assert m.mark_read("e001") is False  # nothing unread there
    assert m.unread_count() == 2
    assert plain(m.list_lines(40)[0])[2].startswith("✦")  # the mark stays until the screen closes
    assert m.take_pending() == ["e007"] and m.take_pending() == []
    m.requeue(["e007"])
    assert m.pending == ["e007"]


def test_all_read():
    m = loaded()
    m.mark_all_read()
    assert m.unread_count() == 0 and m.pending == []


def test_next_unread_walks_across_tabs_and_ends():
    m = loaded()
    assert m.next_unread() and m.current_id == "e003"
    m.mark_read("e003")
    assert m.next_unread() and m.current_id == "e007"
    m.mark_read("e007")
    assert m.next_unread() and (m.tab, m.current_id) == ("other", "e020")
    m.mark_read("e020")
    assert m.next_unread() is False


def test_unread_only_hides_what_is_read():
    m = loaded()
    m.unseen_only = True
    assert [e["id"] for e in m.entries] == ["e003", "e007"]
    m.mark_read("e003")
    assert [e["id"] for e in m.entries] == ["e007"]


def test_focus_by_name():
    m = loaded()
    assert m.focus_name("harrow mine") == "found" and m.current_id == "e007"
    assert m.focus_name("wr") == "found" and (m.tab, m.current_id) == ("characters", "e010")
    assert m.focus_name("nothing here") == "none"
    m.load_list("locations", {"entries": [row("e001", "Ashby Vale"), row("e002", "Ashby Hall")]})
    assert m.focus_name("ashby") == "filtered" and m.tab == "locations" and m.query == "ashby"
    assert m.focus_name("thorn") == "found"  # Thornwood was reloaded away: only the Guild is left


def test_a_reload_keeps_the_cursor_on_the_same_entry():
    m = loaded()
    m.move(2)
    m.load_list("locations", {"entries": [row("e000", "Aaa"), row("e001", "Ashby Vale"), row("e007", "Harrow Mine")]})
    assert m.current_id == "e007"


def detail(**kw):
    base = {
        "id": "e007", "name": "Harrow Mine", "kind": "location", "status": "new", "aliases": ["the old mine"],
        "path": [{"id": "e001", "name": "Ashby Vale"}, {"id": "e003", "name": "Thornwood"}],
        "parent": {"id": "e003", "name": "Thornwood"},
        "children": [{"id": "e012", "name": "Lower Gallery", "kind": "location", "status": "new"}],
        "facts": [
            {"id": "f1", "text": "It was abandoned forty years ago after a collapse.", "label": "History", "new": True},
            {"id": "f2", "text": "It lies east of Ashby.", "label": "Approach", "new": False},
            {"id": "f3", "text": "Wren mentioned it.", "label": None, "new": False},
        ],
        "related": [{"id": "e020", "name": "Thorn Guild", "kind": "faction", "category": "other"}],
    }
    return {**base, **kw}


def test_detail_lines_group_facts_by_label_and_mark_new_ones():
    m = loaded()
    m.move(2)
    assert plain(m.detail_lines(60)[0]) == ["Loading..."]
    m.load_detail(detail())
    text = plain(m.detail_lines(60)[0])
    assert text[0].startswith("Harrow Mine") and text[1] == "in Ashby Vale › Thornwood"
    assert "also called: the old mine" in text
    assert "History" in text and "  ✦ It was abandoned forty years ago after a collapse." in text
    assert "  It lies east of Ashby." in text and "Also" not in text
    assert "Wren mentioned it." in text  # the description has no heading and no indent
    assert text.index("Wren mentioned it.") < text.index("History")
    assert "Places inside" in text and "See also" in text and "  → Thorn Guild  faction" in text
    m.mark_read("e007")
    assert not any("✦ It was" in t for t in plain(m.detail_lines(60)[0]))  # read: the mark is gone


def test_long_facts_wrap_to_the_width():
    m = loaded()
    m.move(2)
    m.load_detail(detail())
    assert all(len(t) <= 30 for t in plain(m.detail_lines(30)[0]))


def test_links_can_be_selected_and_followed_and_the_way_back_is_remembered():
    m = loaded()
    m.move(2)
    m.load_detail(detail())
    assert [h for h, _ in m.links()] == ["Inside", "Places inside", "See also"]
    assert m.enter_links() and m.link_mode
    m.move(1)  # onto Lower Gallery, which is not in the lists
    assert m.follow() is None
    m.move(1)  # onto Thorn Guild, in "other"
    _, selected = m.detail_lines(60)
    assert selected > 0
    assert m.follow() == "e020" and (m.tab, m.current_id) == ("other", "e020") and not m.link_mode
    assert m.back() and (m.tab, m.current_id) == ("locations", "e007")
    assert m.back() is False


def test_no_links_means_no_link_mode():
    m = loaded()
    m.load_detail({**detail(id="e001"), "parent": None, "children": [], "related": []})
    assert m.enter_links() is False


def test_the_command_has_aliases():
    assert parse_command("/compendium").name == "compendium"
    assert parse_command("/journal").name == "compendium"
    c = parse_command("/c locations")
    assert c.name == "compendium" and c.args == ("locations",)


def test_the_session_tracks_the_unread_total():
    s = ChatSession(Transcript())
    s.apply(ev.MessageEnd(compendium={"new": 2, "updated": 1}))
    assert s.compendium_unread == 3
    s.apply(ev.MessageEnd())  # an older server says nothing: keep what we know
    assert s.compendium_unread == 3
    s.load_history([], compendium={"new": 0, "updated": 4})
    assert s.compendium_unread == 4
    s.new_game()
    assert s.compendium_unread == 0
    s.set_unread({"new": True, "updated": "x"})  # junk counts as nothing
    assert s.compendium_unread == 0


def test_message_end_parses_the_counts():
    from aigm_client.events import parse_event

    e = parse_event("message_end", '{"compendium": {"new": 1, "updated": 0}}')
    assert e.compendium == {"new": 1, "updated": 0}
    assert parse_event("message_end", "{}").compendium is None


def test_text_is_a_rich_text():
    assert isinstance(loaded().tabs_text(), Text)


def test_a_fact_says_whose_starting_knowledge_it_is():
    m = loaded()
    m.move(2)
    d = detail()
    d["facts"].append({"id": "f9", "text": "The mine road is watched.", "aspect": None, "label": None,
                       "learned_turn": 0, "new": False, "via": ["Toby", "Galvin"]})
    m.load_detail(d)
    assert "The mine road is watched.  · Toby, Galvin" in plain(m.detail_lines(60)[0])
    narrow = plain(m.detail_lines(30)[0])
    assert "· Toby, Galvin" in narrow and all(len(t) <= 30 for t in narrow)
    ascii_m = loaded(True)
    ascii_m.move(2)
    ascii_m.load_detail(d)
    assert "The mine road is watched.  - Toby, Galvin" in plain(ascii_m.detail_lines(60)[0])
    d["facts"][-1].pop("via")
    m.load_detail(d)
    assert "The mine road is watched." in plain(m.detail_lines(60)[0])  # an older server sends no via


# ---- the hidden tab (debug servers) -----------------------------------------------------------


def hidden_row(i, name, kind="npc", hidden=1, hinted=0, motives=0):
    return {"id": i, "name": name, "kind": kind, "discovered": True, "hidden_count": hidden,
            "hinted_count": hinted, "motive_count": motives, "parent": None}


def hidden_loaded() -> CompendiumModel:
    m = loaded(hidden=True)
    m.load_list("hidden", {"entries": [hidden_row("e010", "Wren", hidden=2, hinted=1, motives=1),
                                       hidden_row("e007", "Harrow Mine", "location")]})
    return m


def test_the_hidden_tab_exists_only_when_asked_for():
    assert CompendiumModel().tabs == ("locations", "characters", "other")
    m = CompendiumModel(hidden=True)
    assert m.tabs[-1] == "hidden"
    m.switch_tab(step=-1)  # tabs wrap, so the hidden tab is last
    assert m.tab == "hidden"
    plain_model = CompendiumModel()
    plain_model.switch_tab("hidden")
    assert plain_model.tab == "locations"


def test_the_hidden_tab_is_in_the_tab_line_with_its_count():
    m = CompendiumModel(hidden=True)
    m.load_list("hidden", {"entries": [hidden_row("e010", "Wren")]})
    assert "4 Hidden (1)" in m.tabs_text().plain
    assert "Hidden" not in CompendiumModel().tabs_text().plain


def test_hidden_rows_say_their_kind_and_how_many_secrets():
    m = CompendiumModel(hidden=True)
    m.load_list("hidden", {"entries": [hidden_row("e010", "Wren", hidden=2, hinted=1, motives=1)]})
    m.switch_tab("hidden")
    lines, cursor = m.list_lines(40)
    assert cursor == 0 and lines[0].plain.startswith("  Wren") and lines[0].plain.endswith("npc 4")


def test_hidden_details_do_not_collide_with_the_compendium_details():
    m = CompendiumModel(hidden=True)
    m.load_list("locations", {"entries": [row("e007", "Harrow Mine")]})
    m.load_list("hidden", {"entries": [hidden_row("e007", "Harrow Mine", "location")]})
    m.load_detail(detail(id="e007", name="Harrow Mine"))
    m.switch_tab("hidden")
    assert not m.has_detail("e007") and m.current_detail is None
    m.load_detail({"id": "e007", "name": "Harrow Mine", "kind": "location", "facts": [], "motives": []}, hidden=True)
    assert m.has_detail("e007") and m.current_detail["motives"] == []
    m.switch_tab("locations")
    assert m.current_detail["id"] == "e007" and "motives" not in m.current_detail  # the compendium's own


def test_a_hidden_detail_shows_motives_by_type_then_facts_by_disclosure():
    m = CompendiumModel(hidden=True)
    m.load_list("hidden", {"entries": [hidden_row("e010", "Wren")]})
    m.switch_tab("hidden")
    m.load_detail({
        "id": "e010", "name": "Wren", "kind": "npc", "discovered": False, "aliases": ["Wren Tallow"], "parent": None,
        "motives": [{"id": "m1", "kind": "fear", "scope": "underlying", "strength": "driven", "disclosure": "hidden",
                     "text": "Fears the Guild will learn of the false tally.", "tells": ["Glances at the door."],
                     "moved_by": ["a promise of silence"], "resists": ["open threats"]}],
        "facts": [
            {"id": "f41", "text": "Wren serves Vael.", "label": "Knowledge", "disclosure": "hidden", "source": "generated",
             "about": [{"id": "e010", "name": "Wren"}, {"id": "e030", "name": "Captain Vael"}]},
            {"id": "f42", "text": "Wren keeps a ledger.", "label": None, "disclosure": "hinted", "source": "play", "about": []},
        ],
    }, hidden=True)
    text = plain(m.detail_lines(60)[0])
    joined = "\n".join(text)
    assert "not discovered this" in joined and "also called: Wren Tallow" in joined
    assert text.index("Motives") < text.index("Hidden facts") < text.index("Hinted facts")
    assert "  fear  (driven, underlying, hidden)" in text
    assert "Moved by: a promise of silence" in joined and "Resists: open threats" in joined
    assert "Tells: Glances at the door." in joined
    assert "Knowledge: Wren serves Vael." in joined and "also about Captain Vael" in joined
    assert "Wren keeps a ledger." in joined


def test_hidden_rows_are_never_unread_and_the_unread_filter_ignores_the_tab():
    m = hidden_loaded()
    m.switch_tab("hidden")
    m.unseen_only = True
    assert len(m.entries) == 2
    assert m.unread_count() == 3  # the compendium's own marks only; the hidden rows add none
    assert not m.mark_read("e010") and m.pending == []


def test_a_lapsed_scene_motive_says_it_expired():
    m = CompendiumModel(hidden=True)
    m.load_list("hidden", {"entries": [hidden_row("e010", "Wren", motives=1)]})
    m.switch_tab("hidden")
    m.load_detail({"id": "e010", "name": "Wren", "kind": "npc", "discovered": True, "aliases": [], "parent": None,
                   "facts": [], "motives": [{"id": "m2", "kind": "want", "scope": "scene", "strength": "leaning",
                                             "disclosure": "hidden", "status": "expired", "text": "Wants a drink."}]},
                  hidden=True)
    assert "  want  (leaning, scene, hidden, expired)" in plain(m.detail_lines(60)[0])


def test_a_person_with_only_an_appearance_shows_it_and_no_facts():
    m = loaded()
    m.switch_tab("characters")
    m.load_detail(detail(id="e010", name="Wren", kind="npc", aliases=[], path=[], children=[], related=[], facts=[],
                         look={"summary": "A stout woman.", "description": "Wren is a stout woman with red hands."}))
    lines = plain(m.detail_lines(60)[0])
    assert "Appearance" in lines and "  Wren is a stout woman with red hands." in lines


def test_a_place_shows_its_description_under_the_heading_view_and_a_person_under_appearance():
    m = loaded()
    look = {"summary": "A yard.", "description": "A broad yard of grey gravel ringed by timber halls."}
    m.load_detail(detail(look=look))  # Harrow Mine, a location
    m.move(2)
    text = plain(m.detail_lines(60)[0])
    assert "View" in text and "Appearance" not in text and "  A broad yard of grey gravel ringed by timber halls." in text
    m2 = loaded()
    m2.switch_tab("characters")
    m2.load_detail(detail(id="e010", name="Wren", kind="npc", facts=[], look=look))
    text2 = plain(m2.detail_lines(60)[0])
    assert "Appearance" in text2 and "View" not in text2
