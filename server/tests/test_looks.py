import json

import pytest

from aigm.errors import CorruptSave
from aigm.looks import (
    CONTROLLED_TAGS,
    SEARCH_TEXT_VERSION,
    Look,
    LookError,
    problems,
    read_looks,
    validate,
)
from aigm.session.persistence import HistoryRepository
from aigm.session.state import GameState, Phase
from aigm.world import World, WorldError
from aigm.world.dump import dump_world

MESSAGES = [
    {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
]
BODY = (
    "{name} is a woman of about seventy, short and stooped, with thin white hair pulled back into a tight knot at the "
    "nape of her neck. Her left eye is clouded milky white while the right is a sharp grey, and her skin is pale and "
    "creased like old paper from years beside the hearth. She wears a slate grey wool shawl pinned with a bone "
    "brooch over a patched brown dress, and a ring of iron keys hangs at her belt. A tremor runs through her right "
    "hand, which grips a worn blackthorn walking stick. Her expression is wary, lips pressed thin."
)


def make_look(name="Marta Venn", **over):
    look = Look(
        "A stooped old woman with a milky left eye and a shawl the color of wet slate.",
        BODY.format(name=name),
        {
            "ancestry": "human", "age": "elderly", "gender": "feminine", "build": "slight", "height": "short",
            "hair": "white, thin, tied back", "eyes": "left clouded, right grey",
            "marks": ["clouded left eye", "tremor in the right hand"], "archetype": "innkeeper",
            "clothing": "slate grey wool shawl", "carries": ["walking stick", "ring of keys"],
        },
    )  # fmt: skip
    for key, value in over.items():
        setattr(look, key, value)
    return look


def test_a_good_look_has_no_problems():
    assert problems(make_look(), "Marta Venn") == []
    validate(make_look(), "Marta Venn")


def test_the_description_needs_the_right_length_and_the_name():
    short = make_look(description="Marta Venn is old.")
    assert any("words" in p for p in problems(short, "Marta Venn"))
    assert any("name" in p for p in problems(make_look(name="Someone Else"), "Marta Venn"))
    assert any("words" in p for p in problems(make_look(description=BODY.format(name="Marta Venn") * 3), "Marta Venn"))


def test_the_summary_is_short_and_present():
    assert any("summary" in p for p in problems(make_look(summary=""), "Marta Venn"))
    assert any("summary" in p for p in problems(make_look(summary="word " * 26), "Marta Venn"))


@pytest.mark.parametrize("tag", list(CONTROLLED_TAGS))
def test_controlled_tags_must_come_from_their_lists(tag):
    look = make_look()
    look.tags[tag] = "banana"
    assert any(f"'{tag}'" in p for p in problems(look, "Marta Venn"))
    del look.tags[tag]
    assert any(f"'{tag}'" in p for p in problems(look, "Marta Venn"))


def test_other_tag_rules():
    look = make_look()
    look.tags["shoe size"] = "9"
    look.tags["marks"] = ["a"] * 6
    look.tags["hair"] = "very " * 13
    found = " ".join(problems(look, "Marta Venn"))
    assert "unknown tags: shoe size" in found and "'marks'" in found and "'hair'" in found


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("You see a woman with grey hair.", "you"),
        ("The party notices her shawl.", "the party"),
        ("A level 5 rogue with a scar.", "level"),
        ("She has 14 HP and a scar.", "hp"),
        ("A drow with pale hair.", "drow"),
        ("A tavern in the Forgotten Realms.", "forgotten realms"),
    ],
)
def test_second_person_game_terms_and_product_names_are_refused(text, fragment):
    found = problems(make_look(summary=text), "Marta Venn")
    assert any(fragment in p.lower() for p in found)


def test_ordinary_words_that_look_like_game_terms_are_fine():
    ok = make_look(summary="A woman of the upper class with a youthful face and eye-level scar.")
    assert problems(ok, "Marta Venn") == []


def test_validate_lists_every_problem():
    with pytest.raises(LookError) as err:
        validate(make_look(summary="", description="short"), "Marta Venn")
    assert str(err.value).count("\n- ") >= 3


def test_search_text_is_fixed_order_and_skips_what_is_missing():
    assert make_look().search_text() == (
        "human | elderly | feminine | slight | short | hair: white, thin, tied back | eyes: left clouded, right grey"
        " | marks: clouded left eye; tremor in the right hand | archetype: innkeeper"
        " | A stooped old woman with a milky left eye and a shawl the color of wet slate."
    )
    bare = Look("A man.", "x", {"ancestry": "dwarf"})
    assert bare.search_text() == "dwarf | A man."
    assert SEARCH_TEXT_VERSION == 1


def test_round_trip_and_copy_are_independent():
    look = make_look(rev=3, state="fixed", source="session_zero")
    assert Look.from_dict(json.loads(json.dumps(look.to_dict()))) == look
    twin = look.copy()
    twin.tags["marks"].append("x")
    assert "x" not in look.tags["marks"]


@pytest.mark.parametrize(
    "raw",
    [
        None, [], {"summary": 1, "description": "", "tags": {}}, {"summary": "", "description": "", "tags": []},
        {"summary": "", "description": "", "tags": {"a": 3}}, {"summary": "", "description": "", "tags": {}, "rev": 0},
        {"summary": "", "description": "", "tags": {}, "state": "weird"},
    ],
)  # fmt: skip
def test_malformed_looks_are_rejected_when_read(raw):
    with pytest.raises(ValueError):
        Look.from_dict(raw)


def test_reading_does_not_apply_content_rules():
    assert Look.from_dict({"summary": "", "description": "short", "tags": {"build": "banana"}}).description == "short"


# ---- NPCs: the world ---------------------------------------------------------------------


def test_a_person_can_be_given_a_look_and_it_is_a_copy():
    world = World()
    marta = world.add_entity("Marta Venn", "npc")
    before = world.version
    look = make_look()
    world.set_look(marta.id, look)
    assert world.entity(marta.id).look == look and world.entity(marta.id).look is not look
    assert world.version > before


def test_only_people_have_looks_and_bad_looks_change_nothing():
    world = World()
    inn = world.add_entity("The Flagon", "location")
    marta = world.add_entity("Marta Venn", "npc")
    with pytest.raises(WorldError, match="not a person"):
        world.set_look(inn.id, make_look())
    with pytest.raises(WorldError, match="Invalid look"):
        world.set_look(marta.id, make_look(summary=""))
    assert world.entity(marta.id).look is None


def test_a_looks_survives_world_copy_and_round_trip_and_rolls_back():
    world = World()
    marta = world.add_entity("Marta Venn", "npc")
    world.add_entity("Ashby", "location")
    staged = world.copy()
    staged.set_look(marta.id, make_look())
    assert world.entity(marta.id).look is None  # the live world is untouched until the turn commits
    again = World.from_dict(json.loads(json.dumps(staged.to_dict())))
    assert again == staged and again.entity(marta.id).look == make_look()


def test_a_save_with_a_look_on_a_place_is_corrupt():
    world = World()
    inn = world.add_entity("The Flagon", "location")
    data = world.to_dict()
    data["entities"][0]["look"] = make_look().to_dict()
    with pytest.raises(CorruptSave, match="not a person"):
        World.from_dict(data)
    data["entities"][0]["look"] = {"summary": 1}
    with pytest.raises(CorruptSave, match="bad look"):
        World.from_dict(data)
    assert inn.look is None


def test_worlds_from_before_looks_load_without_them():
    world = World()
    world.add_entity("Marta Venn", "npc")
    data = world.to_dict()
    for ent in data["entities"]:
        del ent["look"]
    assert World.from_dict(data).find("Marta Venn").look is None


# ---- party members: the game state -------------------------------------------------------


def party_state():
    return GameState(Phase.ADVENTURE, {"setting": "x", "party": [{"name": "Toby Reed", "sheet": "s"}]})


def test_a_party_member_look_is_stored_by_name_and_copied():
    state = party_state()
    state.set_look("toby  reed", make_look("Toby Reed"))
    assert list(state.looks) == ["Toby Reed"]
    staged = state.copy()
    staged.looks["Toby Reed"].rev = 9
    assert state.looks["Toby Reed"].rev == 1


def test_only_party_members_get_looks_here_and_bad_ones_are_refused():
    state = party_state()
    with pytest.raises(LookError, match="not a party member"):
        state.set_look("Marta Venn", make_look())
    with pytest.raises(LookError):
        state.set_look("Toby Reed", make_look("Toby Reed", summary=""))
    assert state.looks == {}


async def test_looks_round_trip_through_a_save(tmp_path):
    repo = HistoryRepository(tmp_path / "saves")
    state = party_state()
    state.set_look("Toby Reed", make_look("Toby Reed", state="fixed", source="session_zero"))
    marta = state.world.add_entity("Marta Venn", "npc")
    state.world.set_look(marta.id, make_look())
    await repo.save("g", MESSAGES, state, "m")
    _, loaded, _ = await repo.load("g")
    assert loaded.looks == state.looks and loaded.world == state.world
    assert loaded.world.find("Marta Venn").look == make_look()


async def test_a_version_9_save_loads_with_no_looks(tmp_path):
    repo = HistoryRepository(tmp_path / "saves")
    await repo.save("g", MESSAGES, party_state(), "m")
    path = repo.dir / "g.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = 9
    del data["looks"]
    path.write_text(json.dumps(data), encoding="utf-8")
    _, loaded, _ = await repo.load("g")
    assert loaded.looks == {}


def test_a_malformed_looks_section_is_a_corrupt_save():
    with pytest.raises(CorruptSave):
        read_looks([])
    with pytest.raises(CorruptSave, match="Toby"):
        read_looks({"Toby": {"summary": 1}})
    assert read_looks(None) == {}


# ---- the world dump ----------------------------------------------------------------------


def test_the_dump_shows_looks_but_not_in_the_known_only_view():
    world = World()
    marta = world.add_entity("Marta Venn", "npc")
    world.add_fact("Marta Venn keeps the Flagon.", [marta.id], disclosure="known")
    world.set_look(marta.id, make_look())
    entry = dump_world(world)["entities"][0]
    assert entry["look"]["summary"].startswith("A stooped old woman") and entry["look"]["rev"] == 1
    assert "look" not in dump_world(world, known_only=True)["entities"][0]


def test_a_dropped_title_is_still_the_characters_name():
    look = make_look("Aggie Fenn")
    assert problems(look, "Saltwife Aggie Fenn") == []  # three words: the title may go
    assert any("name" in p for p in problems(make_look("Fenn"), "Saltwife Aggie Fenn"))
    assert any("name" in p for p in problems(make_look("Venn"), "Marta Venn"))  # two words: both are needed
