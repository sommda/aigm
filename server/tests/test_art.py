"""Art styles and the portrait prompt (docs/PORTRAITS.md 5 and 7)."""

import re

import pytest

from aigm import art
from aigm.looks import Look
from aigm.rulesets import RULESETS

LOOK = Look(
    "A stocky dwarven marshal in a navy coat with a stern, watchful stare.",
    "Marshal Edda Fenn stands in the guardroom, short and stocky. Edda's broad face is ruddy, with a thin white scar. "
    "She wears a navy coat. Her dark eyes are sharp. Fenn clasps her hands behind her back. " * 2,
    {"ancestry": "dwarf", "age": "middle-aged", "gender": "feminine", "build": "sturdy", "hair": "grey"},
)
NAMES = ["Marshal Edda Fenn"]


def test_every_ruleset_has_a_default_style_and_it_exists():
    for ruleset in RULESETS:
        style = art.resolve_style(None, ruleset.id)
        assert style is art.BY_ID[art.RULESET_STYLE[ruleset.id]]


def test_the_four_independent_styles_belong_to_no_ruleset():
    free = {"storybook", "sketch", "anime", "illustration"}
    assert free <= set(art.BY_ID)
    assert not free & set(art.RULESET_STYLE.values())


def test_a_chosen_style_beats_the_ruleset_and_none_means_no_portraits():
    assert art.resolve_style("anime", "odnd").id == "anime"
    assert art.resolve_style(art.NO_PORTRAITS, "odnd") is None
    assert art.resolve_style(None, "adnd1e").id == "ink"


def test_styles_name_no_people_products_or_settings():
    banned = re.compile(r"dungeons|d&d|pathfinder|forgotten|greyhawk|golarion|wizards of the coast|paizo|"
                        r"elmore|easley|brom|reynolds|trampier|\bby [A-Z]", re.I)
    for style in art.STYLES:
        assert not banned.search(style.direction), style.id
        assert 20 <= len(style.direction.split()) <= 70, style.id


def test_style_ids_are_unique_and_the_catalog_lists_them_all():
    assert len({s.id for s in art.STYLES}) == len(art.STYLES) == 12
    assert [c["id"] for c in art.catalog()] == [s.id for s in art.STYLES]


def test_the_prompt_has_the_style_then_the_framing_then_the_character_then_a_reminder():
    style = art.BY_ID["moody"]
    prompt = art.build_prompt(LOOK, style, NAMES)
    assert prompt.startswith(style.direction)
    assert prompt.index(art.FRAMING) > prompt.index(style.direction)
    assert prompt.index("The character:") > prompt.index(art.FRAMING)
    assert "(dwarf, middle-aged, feminine, sturdy)" in prompt
    assert prompt.rstrip().endswith("moody painting.")


def test_the_name_never_reaches_the_prompt_but_titles_may_stay_as_roles():
    prompt = art.build_prompt(LOOK, art.BY_ID["ink"], NAMES)
    for word in ("Edda", "Fenn", "Marshal Edda"):
        assert word not in prompt
    assert "The character stands in the guardroom" in prompt
    assert "the character's broad face" in prompt.lower()
    assert "marshal in a navy coat" in prompt  # the role in the summary is kept


def test_scrub_name_handles_possessives_aliases_and_doubles():
    assert art.scrub_name("Fenn's coat. Fenn Edda grins.", ["Marshal Edda Fenn"]) == "The character's coat. The character grins."
    assert art.scrub_name("Old Tam waves.", ["Tam Orrin", "Old Tam"]) == "The character waves."
    assert art.scrub_name("A tamarind tree.", ["Tam"]) == "A tamarind tree."  # whole words only


def test_only_the_look_is_used():
    prompt = art.build_prompt(LOOK, art.BY_ID["ink"], NAMES)
    assert "hair" not in prompt.split("The character:")[0]
    assert "secret" not in prompt.lower()


def test_a_long_look_is_cut_to_the_limit_at_a_sentence():
    long = Look("A man.", "He is tall. " * 1000, {"ancestry": "human"})
    prompt = art.build_prompt(long, art.BY_ID["ink"], ["Zed"])
    assert len(prompt) <= art.MAX_PROMPT_CHARS + 120  # the reminder line follows the cut text
    assert "(human)" not in prompt  # the tags go first


def test_the_softened_prompt_keeps_the_tags_and_the_first_sentence_only():
    prompt = art.build_prompt(LOOK, art.BY_ID["ink"], NAMES, softened=True)
    assert "(dwarf, middle-aged, feminine, sturdy)" in prompt
    assert "guardroom" in prompt and "scar" not in prompt


def test_other_is_not_a_useful_tag():
    look = Look("A figure.", "A figure stands. " * 30, {"ancestry": "other", "age": "adult"})
    assert "(adult)" in art.build_prompt(look, art.BY_ID["ink"], ["Zed"])


def test_image_ids_follow_the_inputs():
    ink, moody = art.BY_ID["ink"], art.BY_ID["moody"]
    a = art.image_id("m", "1024x1024", ink, "prompt")
    assert a == art.image_id("m", "1024x1024", ink, "prompt") and a.startswith("p_") and len(a) == 18
    assert len({a, art.image_id("n", "1024x1024", ink, "prompt"), art.image_id("m", "512x512", ink, "prompt"),
                art.image_id("m", "1024x1024", moody, "prompt"), art.image_id("m", "1024x1024", ink, "other"),
                art.image_id("m", "1024x1024", ink, "prompt", "high")}) == 6


@pytest.mark.parametrize("style", art.STYLES, ids=lambda s: s.id)
def test_every_style_builds_a_prompt(style):
    assert style.direction in art.build_prompt(LOOK, style, NAMES)


# ---- views of places (docs/PLACES.md 8.2) ------------------------------------------------------

PLACE = Look(
    "A trampled gravel yard ringed by low turf-roofed halls, with a steaming stone well at its center.",
    "Icehold Square is a broad yard of grey gravel ringed by long timber halls. At the center stands a squat stone "
    "well. Beyond Icehold Square the mountains climb. The square is empty. " * 2,
    {"scale": "site", "setting": "urban", "climate": "cold", "hair": "ignored"},
)


def test_a_place_prompt_has_the_style_the_framing_of_a_view_the_place_and_a_reminder():
    style = art.BY_ID["moody"]
    prompt = art.build_place_prompt(PLACE, style, ["Icehold Square"])
    assert prompt.startswith(style.direction) and prompt.index(art.PLACE_FRAMING) > prompt.index(style.direction)
    assert prompt.index("The place:") > prompt.index(art.PLACE_FRAMING)
    assert "(site, urban, cold)" in prompt and "hair" not in prompt.split("The place:")[1]
    assert prompt.rstrip().endswith("moody painting.")
    assert "no people" in art.PLACE_FRAMING and "No text" in art.PLACE_FRAMING and "landscape" in art.PLACE_FRAMING


def test_styles_written_for_faces_use_their_place_variant_for_views_and_the_rest_do_not():
    for style in art.STYLES:
        prompt = art.build_place_prompt(PLACE, style, ["Icehold Square"])
        assert style.direction_for("place") in prompt
        assert style.direction_for("person") == style.direction
        if style.place:
            assert style.place != style.direction and style.direction not in prompt
    assert {s.id for s in art.STYLES if s.place} >= {"anime", "sketch", "illustration", "vivid", "clean"}
    assert not any(w in art.BY_ID["anime"].place.lower() for w in ("character", "eyes", "face"))
    assert "portrait" not in art.BY_ID["sketch"].place and "portrait" not in art.BY_ID["illustration"].place


def test_a_places_name_is_replaced_whole_but_its_ordinary_words_stay():
    prompt = art.build_place_prompt(PLACE, art.BY_ID["ink"], ["Icehold Square"])
    assert "Icehold" not in prompt and "the place" in prompt.lower()
    assert "A broad yard" not in prompt  # sanity: the description is still there in its own words
    assert "a broad yard of grey gravel" in prompt
    quarry = Look("An abandoned quarry.", "The Old Quarry is stepped grey stone. The quarry walls are cut in terraces.", {})
    text = art.build_place_prompt(quarry, art.BY_ID["ink"], ["Old Quarry"])
    assert "Old Quarry" not in text and "The the place" not in text  # the article goes with the name
    assert "The place is stepped grey stone. The quarry walls are cut" in text  # "quarry" alone is a plain word
    assert art.scrub_name("Gate Hold and the gate.", ["Gate Hold"], "the place") == "The place and the gate."


def test_a_long_place_is_cut_to_the_limit_and_the_view_is_not_the_portrait_prompt():
    long = Look("A hall.", "It is wide. " * 1000, {"scale": "room"})
    prompt = art.build_place_prompt(long, art.BY_ID["ink"], ["Hall"])
    assert len(prompt) <= art.MAX_PROMPT_CHARS + 120
    assert art.PLACE_FRAMING in prompt and art.FRAMING not in prompt
