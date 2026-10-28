"""Motives, step 2: shift/resolve/disclose, the set_motive tool, recall, and the curator (docs/ROLEPLAY.md 7.3)."""

import json
from types import SimpleNamespace

import pytest

from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch, tool_schemas
from aigm.world import World, WorldError
from aigm.world.anthropic_curator import EXPAND_SCHEMA, EXTRACT_SCHEMA, STORY_EXTRACT_SCHEMA, AnthropicCurator
from aigm.world.curator import (
    ExpandRequest,
    ExtractRequest,
    Extraction,
    MotiveProposal,
    MotiveReport,
)
from aigm.world.ops import AddMotive, ResolveMotive, apply_ops
from aigm.world.passes import PassConfig, frontier, run_pass
from aigm.world.render import render_expand, render_extract
from aigm.world.scripted import ScriptedCurator
from tests.test_world_curator import curator as model_curator
from tests.test_world_curator import walk

FEAR = "Fears the Thorn Guild will learn he sold them a false tally."
WANT = "Wants the party gone before the captain returns at noon."


@pytest.fixture
def state():
    s = GameState(Phase.ADVENTURE, {"setting": "x"})
    w = s.world
    inn = w.add_entity("The Rusty Flagon", "location")
    yard = w.add_entity("The Yard", "location")
    harlan = w.add_entity("Harlan Voss", "npc")
    w.add_entity("Wren", "npc")
    w.add_entity("Thorn Guild", "faction")
    w.add_fact("Harlan Voss keeps the tally books.", [harlan.id, inn.id], aspect="role", disclosure="known")
    w.add_fact("Wren pours drinks at the Rusty Flagon.", [w.find("Wren").id, inn.id], aspect="role")
    w.set_scene(inn.id, [harlan.id, w.find("Wren").id])
    s.turn = 5
    s.ids = SimpleNamespace(inn=inn.id, yard=yard.id, harlan=harlan.id, wren=w.find("Wren").id)
    return s


def call(state, *changes):
    return dispatch("set_motive", "t", {"changes": list(changes)}, state)


# ---- the model: shift, resolve, disclose -------------------------------------------------------


def test_shifting_a_motive_keeps_the_old_one_and_the_moment(state):
    w = state.world
    old = w.add_motive(state.ids.harlan, WANT, scope="scene", kind="want", strength="driven", tells=["Checks the clock."])
    w.disclose_motive(old.id)
    w.advance_time(1)
    new = w.shift_motive(old.id, text="Wants to ask who sent the party here.", strength="leaning", turn=9)
    assert (old.status, old.superseded_by) == ("superseded", new.id) and new.id != old.id
    assert (new.owner, new.scope, new.kind, new.strength) == (old.owner, "scene", "want", "leaning")
    assert new.tells == old.tells and new.disclosure == "hinted" and new.turn == 9
    assert (new.scene_location, new.set_at) == (old.scene_location, old.set_at)  # the same moment, so it lapses together
    assert w.motives_of(state.ids.harlan) == [new]
    w.advance_time(1)
    assert not w.motive_live(new)


def test_shift_rules(state):
    w = state.world
    m = w.add_motive(state.ids.harlan, FEAR)
    for kwargs, message in [
        ({}, "would not change"),
        ({"text": FEAR}, "would not change"),
        ({"strength": "absolute", "text": "Now sworn to the Guild forever."}, "cannot become absolute"),
        ({"kind": "hunger"}, "kind must be one of"),
        ({"text": "Short."}, "at least 3 words"),
    ]:
        with pytest.raises(WorldError, match=message):
            w.shift_motive(m.id, **kwargs)
    with pytest.raises(WorldError, match="unknown motive"):
        w.shift_motive("m099", text=WANT)
    assert w.next_id["m"] == 2 and len(w.motives) == 1  # failed shifts leave no trace


def test_an_absolute_motive_can_never_be_shifted_or_resolved(state):
    w = state.world
    m = w.add_motive(state.ids.harlan, "Would die before breaking his oath to Lord Ashby.", kind="loyalty", strength="absolute")
    with pytest.raises(WorldError, match="absolute.*nothing the party does changes it"):
        w.shift_motive(m.id, text="Now he does not care about his oath at all.", strength="leaning")
    with pytest.raises(WorldError, match="absolute"):
        w.resolve_motive(m.id, "satisfied")
    assert m.status == "active" and m.strength == "absolute"
    assert w.disclose_motive(m.id) is True and m.disclosure == "hinted"  # disclosure works on every motive


def test_resolving_and_disclosing(state):
    w = state.world
    m = w.add_motive(state.ids.harlan, FEAR)
    assert w.disclose_motive(m.id) is True and w.disclose_motive(m.id) is False
    with pytest.raises(WorldError, match="hinted for now"):
        w.disclose_motive(m.id, "known")
    with pytest.raises(WorldError, match="satisfied or frustrated"):
        w.resolve_motive(m.id, "done")
    w.resolve_motive(m.id, "frustrated")
    assert m.status == "frustrated" and w.motives_of(state.ids.harlan) == []
    for action in (lambda: w.resolve_motive(m.id, "satisfied"), lambda: w.shift_motive(m.id, text=WANT),
                   lambda: w.disclose_motive(m.id)):
        with pytest.raises(WorldError, match="already frustrated"):
            action()


# ---- the tool ----------------------------------------------------------------------------------


def test_set_motive_is_offered_in_the_adventure_and_has_a_description():
    names = [t["name"] for t in tool_schemas(phase=Phase.ADVENTURE)]
    assert "set_motive" in names and "set_motive" not in [t["name"] for t in tool_schemas(phase=Phase.SESSION_ZERO)]
    description = next(t for t in tool_schemas() if t["name"] == "set_motive")["description"]
    assert "absolute" in description and "scene" in description
    schema = next(t for t in tool_schemas() if t["name"] == "set_motive")["input_schema"]
    item = schema["properties"]["changes"]["items"]["properties"]
    assert item["strength"]["enum"] == ["leaning", "driven"]  # absolute is never offered


def test_add_records_an_improvised_scene_motive(state):
    out = call(state, {"op": "add", "owner": "Harlan Voss", "text": WANT, "kind": "want", "strength": "driven",
                       "tells": ["Checks the clock."], "moved_by": ["a favor"]})
    assert not out.is_error and "m001: Harlan Voss, want (driven, scene)" in out.content
    m = state.world.motives["m001"]
    assert (m.scope, m.source, m.turn, m.tells) == ("scene", "improvised", 5, ("Checks the clock.",))
    assert m.scene_location == state.ids.inn


def test_changes_are_all_or_nothing(state):
    before = state.world.to_dict()
    out = call(state, {"op": "add", "owner": "Harlan Voss", "text": WANT},
               {"op": "add", "owner": "Nobody", "text": WANT},
               {"op": "add", "owner": "Thorn Guild", "text": WANT},
               {"op": "add", "owner": "Wren", "text": WANT, "strength": "absolute"},
               {"op": "resolve", "id": "m099", "outcome": "satisfied"}, "nope")
    assert out.is_error and state.world.to_dict() == before
    for fragment in ("change 2:", "not a recorded person", "only people have motives", "cannot be created in play",
                     "unknown motive", "must be an object", "Nothing was recorded"):
        assert fragment in out.content, fragment
    assert "op must be one of" in call(state, {"op": "bogus"}).content


def test_party_members_motives_are_not_the_gms(state):
    state.campaign = {"party": [{"name": "Toby", "sheet": "x"}]}
    out = call(state, {"op": "add", "owner": "Toby", "text": WANT})
    assert out.is_error and "belong to the player" in out.content


def test_shift_resolve_and_disclose_through_the_tool(state):
    state.world.add_motive(state.ids.harlan, FEAR, kind="fear", strength="driven")
    state.world.add_motive(state.ids.wren, "Wants the quiet life back.", scope="underlying", kind="want")
    out = call(state, {"op": "shift", "id": "m001", "text": "Is no longer afraid now that the tally is burned.",
                       "strength": "leaning"}, {"op": "disclose", "id": "m002"},
               {"op": "resolve", "id": "m002", "outcome": "satisfied"})
    assert not out.is_error, out.content
    assert "m001 replaced by m003" in out.content and "m002 satisfied" in out.content
    assert state.world.motives["m003"].strength == "leaning" and state.world.motives["m002"].status == "satisfied"
    assert state.world.motives["m002"].disclosure == "hinted"


def test_the_tool_refuses_to_change_an_absolute_motive(state):
    state.world.add_motive(state.ids.harlan, "Holds a sacred vow of silence.", strength="absolute")
    for change in ({"op": "shift", "id": "m001", "text": "No longer holds any vow at all."},
                   {"op": "resolve", "id": "m001", "outcome": "satisfied"}):
        out = call(state, change)
        assert out.is_error and "absolute" in out.content and state.world.motives["m001"].status == "active"


def test_bad_calls(state):
    assert dispatch("set_motive", "t", {}, state).is_error
    assert dispatch("set_motive", "t", {"changes": []}, state).is_error
    assert "at most 6" in dispatch("set_motive", "t", {"changes": [{"op": "disclose", "id": "m1"}] * 7}, state).content
    assert dispatch("set_motive", "t", {"changes": [{"op": "disclose", "id": "m1"}]}, GameState(Phase.SESSION_ZERO)).is_error


def test_recall_shows_a_persons_motives_to_the_gm(state):
    state.world.add_motive(state.ids.harlan, FEAR, kind="fear", strength="driven", tells=["Glances at the door."])
    out = dispatch("recall", "t", {"about": "Harlan Voss"}, state)
    assert "Motives (GM only, never state them):" in out.content
    assert f"Harlan Voss: fear (driven, underlying): {FEAR}" in out.content and "Tells: Glances at the door." in out.content
    assert "Motives" not in dispatch("recall", "t", {"about": "Wren"}, state).content


# ---- ops ---------------------------------------------------------------------------------------


def test_add_motive_op_skips_a_repeat_and_unknown_people(state):
    w = state.world
    ops = [AddMotive("Harlan Voss", FEAR, kind="fear"), AddMotive("Harlan Voss", FEAR.upper()), AddMotive("Nobody", FEAR),
           ResolveMotive("m099", "satisfied")]
    applied = apply_ops(w, ops)
    assert len(applied.ops) == 1 and len(w.motives) == 1 and len(applied.skipped) == 2


# ---- the curator: expansion --------------------------------------------------------------------


class FakeCurator:
    def __init__(self, extraction=None, expansions=()):
        self.extraction, self.expansions, self.requests = extraction or Extraction(), list(expansions), []

    async def extract(self, request):
        self.requests.append(request)
        return self.extraction

    async def reconcile(self, request):
        from aigm.world.curator import Label, ReconcileResult

        return ReconcileResult([Label(i.index, "new") for i in request.items], {})

    async def expand(self, request):
        self.requests.append(request)
        return self.expansions.pop(0) if self.expansions else Extraction()


def convo(text="quiet"):
    return [
        {"role": "user", "content": [{"type": "text", "text": "I look around."}]},
        {"role": "assistant", "content": [{"type": "text", "text": text}]},
    ]


def test_a_person_with_no_lasting_motive_has_a_motives_slot_on_the_frontier(state):
    w = state.world
    wanted = {e.name: missing for e, _, missing in frontier(w, 20)}
    assert "motives" in wanted["Harlan Voss"] and "motivation" not in wanted["Harlan Voss"] and "role" not in wanted["Harlan Voss"]
    w.add_motive(state.ids.harlan, FEAR)
    assert "motives" not in {e.name: m for e, _, m in frontier(w, 20)}["Harlan Voss"]
    w.resolve_motive("m001", "satisfied")  # finished motives do not count as covering the slot
    assert "motives" in {e.name: m for e, _, m in frontier(w, 20)}["Harlan Voss"]
    scene_only = state.world.add_motive(state.ids.wren, WANT, scope="scene")
    assert scene_only and "motives" in {e.name: m for e, _, m in frontier(w, 20)}["Wren"]  # only lasting motives count


async def test_the_scripted_curator_gives_each_person_a_lasting_motive(state):
    cur = ScriptedCurator()
    result = await run_pass(state.world, convo(), cur, config=PassConfig(max_expand_entities=4))
    live = state.world.copy()
    applied = apply_ops(live, result.ops)
    assert not applied.skipped, applied.skipped
    for name in ("Harlan Voss", "Wren"):
        (m,) = live.motives_of(live.find(name).id)
        assert (m.scope, m.source, m.disclosure, m.strength) == ("underlying", "generated", "hidden", "driven")
        assert f"Wants to keep {name}'s place" in m.text and m.tells
    assert not state.world.motives  # the pass worked on a snapshot


async def test_expansion_requests_carry_a_persons_recorded_motives(state):
    state.world.add_motive(state.ids.harlan, FEAR, kind="fear")
    cur = FakeCurator()
    await run_pass(state.world, convo(), cur, config=PassConfig(max_expand_entities=6))
    reqs = {r.entity.name: r for r in cur.requests if isinstance(r, ExpandRequest)}
    assert [m.id for m in reqs["Harlan Voss"].motives] == ["m001"] and reqs["Wren"].motives == []
    assert reqs["The Rusty Flagon"].motives == []


async def test_expanded_motives_are_underlying_generated_and_capped(state):
    cur = FakeCurator(expansions=[Extraction(motives=[
        MotiveProposal("Harlan Voss", FEAR, "fear", "driven", ["silence"], ["threats"], ["Glances at the door."]),
        MotiveProposal("Harlan Voss", "Hopes to be head clerk one day.", "want", "leaning"),
        MotiveProposal("Harlan Voss", "A third lasting motive over the limit.", "vice", "leaning"),
        MotiveProposal("Thorn Guild", "A group cannot have a motive here.", "want", "leaning"),
        MotiveProposal("Nobody", "Not a recorded person at all.", "want", "leaning"),
    ])])
    result = await run_pass(state.world, convo(), cur, config=PassConfig(max_expand_entities=1))
    live = state.world.copy()
    applied = apply_ops(live, result.ops)
    kept = live.motives_of(state.ids.harlan)
    assert [m.text for m in kept] == [FEAR, "Hopes to be head clerk one day."]
    assert all(m.scope == "underlying" and m.source == "generated" for m in kept)
    assert not applied.skipped and any("already has 2 underlying" in n for n in result.notes)
    assert any("not a recorded person" in n for n in result.notes)


async def test_motives_that_mention_the_party_are_asked_again_then_dropped(state):
    bad = Extraction(motives=[MotiveProposal("Harlan Voss", "Wants to be paid by the party for the tally.", "want", "driven")])
    good = Extraction(motives=[MotiveProposal("Harlan Voss", FEAR, "fear", "driven")])
    cur = FakeCurator(expansions=[bad, good])
    result = await run_pass(state.world, convo(), cur, config=PassConfig(max_expand_entities=1))
    asked = [r for r in cur.requests if isinstance(r, ExpandRequest)]
    assert len(asked) == 2 and "motive" in asked[1].feedback[0] and "mentions the party" in asked[1].feedback[0]
    live = state.world.copy()
    apply_ops(live, result.ops)
    assert [m.text for m in live.motives_of(state.ids.harlan)] == [FEAR]

    cur = FakeCurator(expansions=[bad, bad])
    result = await run_pass(state.world, convo(), cur, config=PassConfig(max_expand_entities=1))
    live = state.world.copy()
    apply_ops(live, result.ops)
    assert live.motives_of(state.ids.harlan) == [] and any("dropped generated motive" in n for n in result.notes)


async def test_a_curator_may_write_an_absolute_motive_ahead_of_play(state):
    cur = FakeCurator(expansions=[Extraction(motives=[
        MotiveProposal("Harlan Voss", "Would die before breaking his oath to Lord Ashby.", "loyalty", "absolute")])])
    result = await run_pass(state.world, convo(), cur, config=PassConfig(max_expand_entities=1))
    live = state.world.copy()
    apply_ops(live, result.ops)
    assert live.motives_of(state.ids.harlan)[0].strength == "absolute"


# ---- the curator: extraction -------------------------------------------------------------------


async def test_the_extract_request_lists_changeable_motives_of_people_present(state):
    w = state.world
    w.add_motive(state.ids.harlan, FEAR, kind="fear", strength="driven")
    w.add_motive(state.ids.harlan, "Would never betray Lord Ashby.", kind="loyalty", strength="absolute")
    w.add_motive(state.ids.wren, WANT, scope="scene")
    w.set_scene(state.ids.inn, [state.ids.harlan])  # Wren has left
    cur = FakeCurator()
    await run_pass(w, convo(), cur, config=PassConfig(max_expand_entities=0))
    req = next(r for r in cur.requests if isinstance(r, ExtractRequest))
    assert [(owner, m.id) for owner, m in req.motives] == [("Harlan Voss", "m001")]  # present, live, not absolute


async def test_reports_become_ops_and_the_rest_are_dropped(state):
    w = state.world
    w.add_motive(state.ids.harlan, FEAR, kind="fear", strength="driven")  # m001
    w.add_motive(state.ids.harlan, "Would never betray Lord Ashby.", kind="loyalty", strength="absolute")  # m002
    w.add_motive(state.ids.wren, WANT, scope="scene")  # m003
    ex = Extraction(motive_reports=[
        MotiveReport("m001", "shift", "Harlan Voss no longer fears the Guild now that the tally is burned.", "leaning"),
        MotiveReport("m002", "shift", "Harlan Voss has stopped caring about his oath.", None),
        MotiveReport("m003", "hint"),
        MotiveReport("m099", "resolve", outcome="satisfied"),
        MotiveReport("m003", "resolve", outcome="done"),
        MotiveReport("m001", "shift", "The party burned the tally, so Harlan Voss relaxes.", None),
    ])
    cur = FakeCurator(extraction=ex)
    result = await run_pass(w, convo("The tally burns."), cur, config=PassConfig(max_expand_entities=0))
    live = w.copy()
    applied = apply_ops(live, result.ops)
    assert not applied.skipped, applied.skipped
    assert live.motives["m001"].status == "superseded" and live.motives["m004"].strength == "leaning"
    assert live.motives["m004"].source == "play" and live.motives["m003"].disclosure == "hinted"
    assert live.motives["m002"].status == "active" and live.motives["m002"].strength == "absolute"
    notes = " | ".join(result.notes)
    assert "m002" in notes and "m099" in notes and "unusable motive report" in notes and "mentions the party" in notes


# ---- the prompts and the model-backed curator ---------------------------------------------------


def test_schemas_are_closed_and_the_motive_parts_are_present():
    for schema in (EXTRACT_SCHEMA, STORY_EXTRACT_SCHEMA, EXPAND_SCHEMA):
        walk(schema)
    assert "motive_reports" in EXTRACT_SCHEMA["properties"] and "motive_reports" in STORY_EXTRACT_SCHEMA["properties"]
    assert "motives" in EXPAND_SCHEMA["properties"]


def test_render_sections(state):
    w = state.world
    m = w.add_motive(state.ids.harlan, FEAR, kind="fear", strength="driven", tells=["Glances at the door."])
    guides = PromptLibrary().aspect_guides()
    harlan = w.entity(state.ids.harlan)
    text = render_expand(ExpandRequest(harlan, "full", ["motives"], [], [], [], [], "", w.time, [], [], [m]), guides)
    assert "- motives: what they want, fear or hold to" in text
    assert f"- m001 (fear, driven, underlying, hidden) {FEAR} Tells: Glances at the door." in text
    assert "(none yet)" in render_expand(ExpandRequest(harlan, "full", ["motives"], [], [], [], [], "", w.time), guides)
    request = ExtractRequest("GM: x", "", w.time, None, [], [], [], motives=[("Harlan Voss", m)])
    assert "## GM-only motives of the people present" in render_extract(request)
    assert f"- m001 (Harlan Voss, fear, driven, underlying, hidden) {FEAR}" in render_extract(request)
    assert "motives" not in render_extract(ExtractRequest("GM: x", "", w.time, None, [], [], []))


def test_prompts_explain_the_motive_rules():
    lib = PromptLibrary()
    expand, extract = lib.world_prompt("expand"), lib.world_prompt("extract")
    assert "nothing the player does could change" in expand and "Use it rarely" in expand
    assert "motive_reports" in extract and "`hint`" in extract and "`shift`" in extract
    assert "never state a motive" in lib.system_prompt("adventure")


async def test_the_model_curator_parses_motives_and_reports():
    expand_reply = {"entities": [], "facts": [], "motives": [
        {"owner": "Harlan Voss", "text": FEAR, "kind": "fear", "strength": "driven", "moved_by": ["silence"],
         "resists": ["threats"], "tells": ["Glances at the door."]},
        {"owner": "Wren", "text": WANT, "kind": "nonsense", "strength": "huge", "moved_by": [], "resists": [], "tells": []},
        {"text": "no owner"}, "junk"]}
    extract_reply = {"entities": [], "facts": [], "reveals": [], "location": None, "present": None, "elapsed_hours": 0,
                     "motive_reports": [{"id": "m001", "action": "shift", "text": "x y z", "strength": "driven", "outcome": None},
                                        {"id": "m002", "action": "hint", "text": None, "strength": None, "outcome": None},
                                        {"action": "hint"}, 4]}
    cur, messages = model_curator(expand_reply, extract_reply)
    w = World()
    ent = w.add_entity("Harlan Voss", "npc")
    out = await cur.expand(ExpandRequest(ent, "full", ["motives"], [], [], [], [], "", w.time))
    assert out.motives[0] == MotiveProposal("Harlan Voss", FEAR, "fear", "driven", ["silence"], ["threats"], ["Glances at the door."])
    assert (out.motives[1].kind, out.motives[1].strength) == ("want", "leaning") and len(out.motives) == 2
    assert "motives" in messages.calls[0]["output_config"]["format"]["schema"]["properties"]
    ex = await cur.extract(ExtractRequest("GM: x", "", w.time, None, [], [], []))
    assert [(r.motive, r.action, r.strength) for r in ex.motive_reports] == [("m001", "shift", "driven"), ("m002", "hint", None)]
