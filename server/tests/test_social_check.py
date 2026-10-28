"""Spoken role play, step 3: the words gate, the reward table, motives in the dice (docs/ROLEPLAY.md 3 to 7)."""

import pytest

from aigm import roleplay, rulesets
from aigm.prompts import PromptLibrary
from aigm.rulesets import RULESETS
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch, tool_schemas
from aigm.world import Motive
from aigm.world.model import WorldTime
from tests.conftest import chat, reply_text

SPEECH = "Easy, friend. Captain Ness sent me for the tally books. She said you would be sour about it."
FEAR = "Fears the Thorn Guild will learn he sold them a false tally."


@pytest.fixture
def state():
    s = GameState(Phase.ADVENTURE, {"setting": "x", "party": [{"name": "Mira", "sheet": "Rogue"}]})
    w = s.world
    inn = w.add_entity("The Rusty Flagon", "location")
    harlan = w.add_entity("Harlan Voss", "npc")
    w.add_entity("Wren", "npc")
    w.set_scene(inn.id, [harlan.id])
    s.turn = 4
    s.player_text = SPEECH
    return s


def check(state, **over):
    args = {"character": "Mira", "skill": "Deception", "target": "Harlan Voss", "spoken": "Captain Ness sent me for the tally books",
            "quality": "ordinary", "modifier": 5, "dc": 15, "narration": "You lean on the counter and smile."}
    args.update(over)
    return dispatch("social_check", "t1", args, state)


def motive(strength, scope="underlying", **kw):
    return Motive("m001", "e003", "x y z", scope=scope, strength=strength, **kw)


# ---- the words ---------------------------------------------------------------------------------


@pytest.mark.parametrize("spoken, ok", [
    ("Captain Ness sent me for the tally books", True),
    ("captain ness sent me for the tally books!", True),                    # case and punctuation do not matter
    ("Captain Ness sent me, the tally books, she said", True),            # trimmed and reordered a little
    ("I convince the guard with a lie about the duke", False),               # not what was typed
    ("tally books", False),                                                  # too short
    ("", False),
    (None, False),
])
def test_the_quoted_words_must_be_the_players(spoken, ok):
    assert (roleplay.words_problem(spoken, SPEECH) is None) is ok


def test_a_bare_intention_is_too_short_to_be_words():
    assert roleplay.words_problem("I bluff him", "I bluff him.") is not None
    # Beyond the length the server cannot read meaning: telling an intention from speech is the prompt's job.
    assert roleplay.words_problem("I try to bluff the guard", "I try to bluff the guard") is None


def test_a_call_without_the_players_words_is_refused_and_nothing_is_rolled(state):
    state.player_text = "I bluff the guard."
    out = check(state, spoken="Captain Ness sent me for the tally books")
    assert out.is_error and out.event is None and "has not said anything for the character to say" in out.content
    assert "end your turn" in out.content
    assert not state.social_done  # the refusal does not use up the try
    state.player_text = SPEECH
    assert not check(state).is_error


def test_one_check_per_message_and_person(state):
    assert not check(state).is_error
    again = check(state)
    assert again.is_error and "needs new words" in again.content
    state.turn += 1  # the next player message
    assert not check(state).is_error
    state.world.set_scene(state.world.scene.location, [state.world.find("Harlan Voss").id, state.world.find("Wren").id])
    assert not check(state, target="Wren").is_error  # another person, same message


@pytest.mark.parametrize("over, fragment", [
    ({"character": "Nobody"}, "not a party member"),
    ({"target": "Nobody"}, "not a recorded person"),
    ({"target": "The Rusty Flagon"}, "not a recorded person"),
    ({"target": "Wren"}, "not with the party"),
    ({"quality": "great"}, "`quality` must be one of"),
    ({"skill": ""}, "`skill`"),
    ({"modifier": "5"}, "`modifier` must be a whole number"),
    ({"dc": None}, "`dc` must be"),
    ({"dc": 99}, "`dc` must be"),
    ({"engages": [{"motive": "m099", "effect": "aligned"}]}, "give a motive id"),
    ({"engages": [{"motive": "m001", "effect": "sideways"}]}, "give a motive id"),
    ({"narration": "Hi"}, "narration"),
])
def test_bad_calls_are_refused(state, over, fragment):
    state.world.add_motive(state.world.find("Wren").id, FEAR)  # m001 belongs to Wren, not the target
    out = check(state, **over)
    assert out.is_error and out.event is None and fragment in out.content
    assert not state.social_done


def test_motives_of_someone_else_or_that_have_lapsed_cannot_be_engaged(state):
    w = state.world
    other = w.add_motive(w.find("Wren").id, FEAR)
    out = check(state, engages=[{"motive": other.id, "effect": "aligned"}])
    assert out.is_error and "not a live motive of the person being addressed" in out.content
    scene = w.add_motive(w.find("Harlan Voss").id, "Wants the party gone before noon.", scope="scene")
    w.advance_time(2)
    out = check(state, engages=[{"motive": scene.id, "effect": "aligned"}])
    assert out.is_error and "not a live motive" in out.content


# ---- boons: quality and motives ---------------------------------------------------------------


@pytest.mark.parametrize("quality, boon", [("weak", -1), ("ordinary", 0), ("strong", 1), ("brilliant", 2)])
def test_quality_is_the_boon_without_motives(quality, boon):
    assert roleplay.boon_for(quality, roleplay.MotiveEffect()) == boon


@pytest.mark.parametrize("engaged, expected", [
    ([("leaning", "aligned")], dict(boon=1)),
    ([("driven", "aligned")], dict(boon=2)),
    ([("leaning", "against")], dict(boon=-1)),
    ([("driven", "against")], dict(boon=-2)),
    ([("absolute", "aligned")], dict(auto_success=True)),
    ([("absolute", "against")], dict(barred=True)),
    ([("leaning", "aligned"), ("driven", "aligned")], dict(boon=2)),                # the strongest on a side counts
    ([("leaning", "aligned"), ("leaning", "aligned")], dict(boon=1)),                # small motives do not stack
    ([("driven", "aligned"), ("leaning", "against")], dict(boon=2)),                # the stronger side decides
    ([("leaning", "aligned"), ("driven", "against")], dict(boon=-2)),
    ([("driven", "aligned"), ("driven", "against")], dict()),                       # equal strength cancels
    ([("absolute", "aligned"), ("driven", "against")], dict(auto_success=True)),
    ([("driven", "aligned"), ("absolute", "against")], dict(barred=True)),
    ([("absolute", "aligned"), ("absolute", "against")], dict()),
    ([], dict()),
])
def test_motive_effects(engaged, expected):
    effect = roleplay.motive_effect([(motive(s), e) for s, e in engaged])
    assert (effect.boon, effect.auto_success, effect.barred) == (
        expected.get("boon", 0), expected.get("auto_success", False), expected.get("barred", False))


def test_the_moment_beats_a_lasting_motive_of_the_same_strength_but_not_an_absolute_one():
    lasting_aligned, scene_against = motive("driven"), motive("driven", scope="scene")
    assert roleplay.motive_effect([(lasting_aligned, "aligned"), (scene_against, "against")]).boon == -2
    assert roleplay.motive_effect([(motive("absolute"), "aligned"), (scene_against, "against")]).auto_success


def test_quality_and_motive_add_but_cap_at_two():
    driven = roleplay.motive_effect([(motive("driven"), "aligned")])
    assert roleplay.boon_for("strong", driven) == 2 and roleplay.boon_for("brilliant", driven) == 2
    assert roleplay.boon_for("weak", driven) == 1
    against = roleplay.motive_effect([(motive("driven"), "against")])
    assert roleplay.boon_for("weak", against) == -2 and roleplay.boon_for("brilliant", against) == 0


# ---- the reward table --------------------------------------------------------------------------


@pytest.mark.parametrize("style, boon, expression, dc", [
    ("advantage", 0, "1d20+5", 15), ("advantage", 1, "2d20kh1+5", 15), ("advantage", 2, "2d20kh1+5", 10),
    ("advantage", -1, "2d20kl1+5", 15), ("advantage", -2, "2d20kl1+5", 20),
    ("bonus", 0, "1d20+5", 15), ("bonus", 1, "1d20+7", 15), ("bonus", 2, "1d20+9", 15), ("bonus", -2, "1d20+1", 15),
    ("circumstance", 0, "1d20+5", 15), ("circumstance", 1, "1d20+6", 15), ("circumstance", 2, "1d20+7", 15),
    ("circumstance", -1, "1d20+4", 15),
    ("reaction", 0, "2d6+5", None), ("reaction", 2, "2d6+7", None), ("reaction", -1, "2d6+4", None),
])
def test_the_reward_table(style, boon, expression, dc):
    plan = roleplay.plan_roll(style, boon, 5, 15 if style != "reaction" else None)
    assert (plan.expression, plan.dc) == (expression, dc)


def test_a_negative_modifier_and_zero_are_written_correctly():
    assert roleplay.plan_roll("advantage", 1, -1, 10).expression == "2d20kh1-1"
    assert roleplay.plan_roll("advantage", 0, 0, 10).expression == "1d20"


def test_degrees_of_success():
    d = roleplay.degree
    assert d(25, 15, 10, True) == "critical success" and d(15, 15, 10, True) == "success"
    assert d(14, 15, 10, True) == "failure" and d(5, 15, 10, True) == "critical failure"
    assert d(14, 15, 20, True) == "success"      # a natural 20 moves it up a step
    assert d(15, 15, 1, True) == "failure"       # and a natural 1 down
    assert d(25, 15, 20, True) == "critical success" and d(5, 15, 1, True) == "critical failure"


def test_every_ruleset_has_a_known_social_style_and_a_roleplay_prompt():
    assert {r.social_style for r in RULESETS} <= set(roleplay.SOCIAL_STYLES)
    assert rulesets.get("dnd55e").social_style == "advantage" and rulesets.get("pf2e").social_style == "circumstance"
    assert rulesets.get("basic").social_style == "reaction" and rulesets.get("dnd35e").social_style == "bonus"
    lib = PromptLibrary()
    for r in RULESETS:
        (part,) = lib.roleplay_part(r.id)
        assert part.source == f"rulesets/{r.id}/03_roleplay.md" and part.text.startswith("### Role play") and len(part.text) > 300
        sources = [p.source for p in lib.system_parts(Phase.ADVENTURE, r.id)]
        assert part.source in sources and part.source not in [p.source for p in lib.system_parts(Phase.SESSION_ZERO, r.id)]
        assert sources.index(f"rulesets/{r.id}/02_era.md") < sources.index(part.source) < sources.index("system/adventure/01_role.md")


# ---- rolling -----------------------------------------------------------------------------------


def test_a_social_check_rolls_with_the_rulesets_dice_and_shows_the_narration(state):
    out = check(state, quality="strong")
    assert not out.is_error and out.say == "You lean on the counter and smile."
    assert out.event.expression.startswith("2d20kh1+5") and out.event.comment == "deception, well played"
    assert "The words earned advantage." in out.content and "Against DC 15:" in out.content
    assert "Never state their motive or the DC" in out.content
    assert (state.turn, state.world.find("Harlan Voss").id) in state.social_done
    plain = check(state, spoken="Captain Ness sent me for the tally", target="Harlan Voss")
    assert plain.is_error  # the same message and person


def test_ordinary_words_roll_one_die_with_no_comment_note(state):
    out = check(state)
    assert out.event.expression.startswith("1d20+5") and out.event.comment == "deception"
    assert "earned" not in out.content


@pytest.mark.parametrize("ruleset, quality, start, note", [
    ("dnd3e", "strong", "1d20+7", "+2"), ("pf1e", "brilliant", "1d20+9", "+4"), ("dnd4e", "weak", "1d20+3", "-2"),
    ("pf2e", "strong", "1d20+6", "+1 circumstance"), ("adnd2e", "brilliant", "2d6+7", "+2 to the reaction roll"),
])
def test_each_style_builds_its_dice(state, ruleset, quality, start, note):
    state.ruleset = ruleset
    out = check(state, quality=quality, **({"dc": None} if ruleset == "adnd2e" else {}))
    assert not out.is_error, out.content
    assert out.event.expression.startswith(start) and note in out.content


def test_reaction_rolls_need_no_dc_and_report_the_total(state):
    state.ruleset = "basic"
    out = check(state, dc=None)
    assert "Reaction total" in out.content and "reaction table" in out.content and "DC" not in out.content.split("Never")[0]


def test_pathfinder_reports_a_degree(state):
    state.ruleset = "pf2e"
    out = check(state, quality="strong")
    assert any(f"Against DC 15: {d}." in out.content for d in roleplay.DEGREES)


def test_a_driven_motive_the_words_serve_gives_advantage_even_to_ordinary_words(state):
    m = state.world.add_motive(state.world.find("Harlan Voss").id, FEAR, kind="fear", strength="driven",
                               tells=["Glances at the cellar door."])
    out = check(state, engages=[{"motive": m.id, "effect": "aligned"}])
    assert out.event.expression.startswith("2d20kh1+5") and out.event.comment == "deception"  # the reason is not shown
    assert "Glances at the cellar door." in out.content


def test_a_driven_motive_the_words_cross_gives_disadvantage_and_a_higher_dc(state):
    m = state.world.add_motive(state.world.find("Harlan Voss").id, FEAR, kind="fear", strength="driven")
    out = check(state, quality="weak", engages=[{"motive": m.id, "effect": "against"}])
    assert out.event.expression.startswith("2d20kl1+5") and "DC 20" in out.content and "disadvantage and DC +5" in out.content


def test_an_absolute_motive_the_words_cross_bars_the_roll(state):
    m = state.world.add_motive(state.world.find("Harlan Voss").id, "Would die before breaking his oath to Lord Ashby.",
                               kind="loyalty", strength="absolute", tells=["His jaw sets."])
    out = check(state, quality="brilliant", engages=[{"motive": m.id, "effect": "against"}])
    assert not out.is_error and out.event is None and out.say == ""
    assert out.content.startswith("No roll.") and "will not be moved" in out.content and "His jaw sets." in out.content
    assert "The player is not told why" in out.content
    assert (state.turn, state.world.find("Harlan Voss").id) in state.social_done  # it used the try


def test_an_absolute_motive_the_words_serve_succeeds_without_a_roll(state):
    m = state.world.add_motive(state.world.find("Harlan Voss").id, "Would never refuse a request in the duke's name.",
                               kind="loyalty", strength="absolute")
    out = check(state, quality="weak", engages=[{"motive": m.id, "effect": "aligned"}])
    assert out.event is None and out.content.startswith("No roll.") and "so it works" in out.content


def test_a_missing_narration_does_not_use_up_the_try(state):
    assert check(state, narration="").is_error
    assert not state.social_done and not check(state).is_error


# ---- offered where it should be, and the roll_dice guard ---------------------------------------


def test_social_check_is_offered_in_the_adventure_only():
    assert "social_check" in [t["name"] for t in tool_schemas(phase=Phase.ADVENTURE)]
    assert "social_check" not in [t["name"] for t in tool_schemas(phase=Phase.SESSION_ZERO)]
    tool = next(t for t in tool_schemas() if t["name"] == "social_check")
    assert "eager_input_streaming" not in tool and "The player must say it" in tool["description"]
    assert set(tool["input_schema"]["required"]) >= {"character", "target", "spoken", "quality", "narration"}


@pytest.mark.parametrize("comment", ["persuasion check", "Deception vs. Insight", "intimidating the guard",
                                     "bluff", "diplomacy", "haggling over the price", "reaction roll"])
def test_roll_dice_refuses_social_checks(state, comment):
    out = dispatch("roll_dice", "t", {"expression": f"1d20+5 # {comment}", "narration": "You try your luck."}, state)
    assert out.is_error and "social_check" in out.content and out.event is None


def test_roll_dice_still_rolls_everything_else(state):
    for comment in ("insight check", "stealth", "attack", "perception", "sense motive", "athletics"):
        out = dispatch("roll_dice", "t", {"expression": f"1d20+5 # {comment}", "narration": "You try your luck."}, state)
        assert not out.is_error, comment


# ---- end to end in test mode -------------------------------------------------------------------


def test_persuade_in_test_mode_asks_for_words_and_then_rolls(client):
    chat(client, "begin")
    chat(client, "establish Wren")
    asked = reply_text(chat(client, "persuade Wren"))
    assert "What do you say?" in asked and "social_check" not in asked
    ev = chat(client, "persuade Wren Please lend us the back room, for the captain owes me a favour")
    kinds = [n for n, _ in ev]
    assert "dice_roll" in kinds, kinds
    text = reply_text(ev)
    assert "`social_check`" in text and "Persuasion for Test Hero on Wren" in text and "The words earned advantage." in text
    again = reply_text(chat(client, "persuade Wren Please lend us the back room, for the captain owes me a favour"))
    assert "Persuasion for Test Hero" in again  # a new message is a new try
