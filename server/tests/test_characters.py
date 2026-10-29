"""Character sheets (docs/STATUS.md 3): the record, the sheet step, the routes and the save."""

import json

import pytest
from fastapi.testclient import TestClient

from aigm.app import create_app
from aigm.config import Settings
from aigm.errors import CorruptSave
from aigm.llm.scripted import TEST_CAMPAIGN
from aigm.session.persistence import FORMAT_VERSION
from aigm.session.state import GameState, Hero, Phase
from aigm.sheets import MAX_LINES, Section, Sheet, clean, read_sheets
from aigm.world.passes import run_sheets
from aigm.world.scripted import ScriptedCurator
from tests.conftest import chat

SHEET = {
    "headline": "Human Rogue 3",
    "hp": 11,
    "max_hp": 15,
    "conditions": ["prone"],
    "sections": [{"title": "Abilities", "lines": ["STR 10 (+0)", "DEX 16 (+3)"]}, {"title": "Gear", "lines": ["Dagger"]}],
}


# ---- the record -----------------------------------------------------------------------------


def test_clean_keeps_a_good_sheet_as_it_is():
    sheet = clean(SHEET)
    assert sheet.to_dict() == SHEET


def test_clean_trims_to_the_limits_and_drops_what_is_empty():
    sheet = clean(
        {
            "headline": "  Elf   Wizard  ",
            "sections": [
                {"title": "Spells", "lines": ["Magic missile", "", 7, "x" * 500] + [f"s{i}" for i in range(100)]},
                {"title": "Empty", "lines": []},
                "junk",
                {"title": "", "lines": ["no title"]},
            ],
            "conditions": ["blind", "blind", " "],
        }
    )
    assert sheet.headline == "Elf Wizard" and [s.title for s in sheet.sections] == ["Spells"]
    assert len(sheet.sections[0].lines) == MAX_LINES and len(sheet.sections[0].lines[1]) == 240
    assert sheet.conditions == ["blind"]


def test_hit_points_are_shown_only_with_a_maximum_and_default_to_it():
    assert clean({**SHEET, "hp": None}).hp == 15
    unknown = clean({**SHEET, "max_hp": None})
    assert unknown.hp is None and unknown.max_hp is None
    assert clean({**SHEET, "hp": -4}).hp == 15 and clean({**SHEET, "hp": True}).hp == 15


def test_a_sheet_with_no_sections_is_refused():
    with pytest.raises(ValueError):
        clean({"headline": "Nobody", "sections": []})
    with pytest.raises(ValueError):
        clean("text")


def test_sheets_survive_a_save_and_a_copy():
    state = GameState(Phase.ADVENTURE, {"party": [{"name": "Toby"}], "level": 1})
    state.sheets["Toby"] = clean(SHEET)
    again = GameState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert again.sheets["Toby"].to_dict() == SHEET
    copy = state.copy()
    copy.sheets["Toby"].conditions.append("blind")
    assert state.sheets["Toby"].conditions == ["prone"]


def test_an_old_save_has_no_sheets_and_a_bad_one_is_refused():
    assert GameState.from_dict({"phase": "adventure", "campaign": None}).sheets == {}
    assert read_sheets(None) == {}
    with pytest.raises(CorruptSave):
        read_sheets({"Toby": {"sections": []}})
    with pytest.raises(CorruptSave):
        read_sheets([])


def test_the_format_is_eight():
    assert FORMAT_VERSION == 10


# ---- the sheet step -------------------------------------------------------------------------


class Flaky(ScriptedCurator):
    async def sheet(self, request):
        if request.name == "Galvin":
            raise RuntimeError("boom")
        return await super().sheet(request)


CAMPAIGN = {
    "party": [
        {"name": "Toby", "sheet": "Human Rogue. HP 11/15. Dagger and rope.", "background": "x"},
        {"name": "Galvin", "sheet": "Dwarf Fighter. HP 30. Axe.", "background": "y"},
    ]
}


async def test_the_step_writes_one_sheet_per_member_with_hit_points_read_from_the_text():
    sheets, notes = await run_sheets(CAMPAIGN, "D&D 5.5e", {"Toby": 3, "Galvin": 2}, ScriptedCurator())
    assert notes == [] and set(sheets) == {"Toby", "Galvin"}
    assert (sheets["Toby"].hp, sheets["Toby"].max_hp) == (11, 15) and sheets["Toby"].headline == "Toby, level 3"
    assert (sheets["Galvin"].hp, sheets["Galvin"].max_hp) == (30, 30)


async def test_a_member_whose_sheet_fails_is_left_out_and_the_rest_are_kept():
    sheets, notes = await run_sheets(CAMPAIGN, "D&D 5.5e", {}, Flaky())
    assert set(sheets) == {"Toby"} and len(notes) == 1 and "Galvin" in notes[0]


async def test_the_step_can_be_limited_to_some_members_and_a_curator_without_it_is_fine():
    sheets, _ = await run_sheets(CAMPAIGN, "D&D 5.5e", {}, ScriptedCurator(), only=["Galvin"])
    assert set(sheets) == {"Galvin"}

    class Bare:
        pass

    assert await run_sheets(CAMPAIGN, "D&D 5.5e", {}, Bare()) == ({}, [])


async def test_the_model_curator_reads_the_sheet_answer():
    from aigm.prompts import PromptLibrary
    from aigm.world.anthropic_curator import AnthropicCurator
    from aigm.world.curator import SheetRequest

    class Reply:
        stop_reason = "end_turn"
        usage = None
        content = [type("B", (), {"type": "text", "text": json.dumps({**SHEET})})()]

    class Client:
        class messages:
            sent = []

            @staticmethod
            async def create(**kw):
                Client.messages.sent.append(kw)
                return Reply

    cur = AnthropicCurator(api_key="k", prompts=PromptLibrary(), client=Client)
    sheet = await cur.sheet(SheetRequest("AD&D 1e", 3, "Toby", "A rogue with a dagger and a coil of rope."))
    assert sheet.to_dict() == SHEET
    sent = Client.messages.sent[0]
    assert "AD&D 1e" in sent["messages"][0]["content"] and "Toby" in sent["messages"][0]["content"]
    assert "Copy it" in sent["system"][0]["text"]


# ---- the routes -----------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "saves", _env_file=None))
    client = TestClient(app)
    client.session = app.state.sessions.get("default")
    return client


def begin(api):
    chat(api, "begin")
    return api.session.state


def test_session_zero_has_no_sheets(api):
    assert api.get("/characters").status_code == 409
    assert api.get("/characters/Toby").status_code == 409


def test_beginning_the_adventure_writes_the_sheets(api):
    state = begin(api)
    name = state.party_names[0]
    assert name in state.sheets and state.sheets[name].sections
    roster = api.get("/characters").json()["characters"]
    assert [c["name"] for c in roster] == state.party_names and roster[0]["hp"] == "12/12"


def test_a_character_page_has_the_sections_and_progress(api):
    state = begin(api)
    name = state.party_names[0]
    state.heroes[name] = Hero(3, 900, {"Rogue": 3})
    body = api.get(f"/characters/{name.lower()}").json()
    assert body["name"] == name and body["text"] is None and body["sections"][0]["title"] == "Sheet"
    assert body["progress"] == "Level 3 (Rogue 3), 900 XP" and body["hp"] == "12/12"


def test_a_character_without_a_structured_sheet_shows_the_free_text(api):
    state = begin(api)
    name = state.party_names[0]
    del state.sheets[name]
    body = api.get(f"/characters/{name}").json()
    assert body["sections"] == [] and body["text"] == TEST_CAMPAIGN["party"][0]["sheet"].strip() and body["hp"] == ""


def test_an_unknown_name_is_not_found(api):
    begin(api)
    resp = api.get("/characters/Nobody")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "not_found"


def test_the_game_survives_a_sheet_step_that_fails(tmp_path, monkeypatch):
    async def boom(self, request):
        raise RuntimeError("no")

    monkeypatch.setattr(ScriptedCurator, "sheet", boom)
    app = create_app(Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "s", _env_file=None))
    client = TestClient(app)
    chat(client, "begin")
    state = app.state.sessions.get("default").state
    assert state.phase is Phase.ADVENTURE and state.sheets == {}
    assert client.get("/characters").json()["characters"][0]["hp"] == ""


def test_the_debug_route_writes_sheets_for_an_old_game(tmp_path):
    app = create_app(
        Settings(test_mode=True, test_delay=0, roll_pause=0, save_dir=tmp_path / "s", debug=True, _env_file=None)
    )
    client = TestClient(app)
    chat(client, "begin")
    state = app.state.sessions.get("default").state
    state.sheets.clear()
    body = client.post("/debug/sheets").json()
    assert body["written"] == state.party_names and state.sheets
