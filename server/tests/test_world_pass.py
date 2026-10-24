import pytest

from aigm.world.model import ARRIVAL_ASPECTS

from aigm.world import World, WorldTime
from aigm.world.curator import (
    EntityProposal,
    Extraction,
    FactProposal,
    Label,
    ReconcileResult,
)
from aigm.world.ops import AddFact, Reveal, apply_ops
from aigm.world.passes import (
    PassConfig,
    frontier,
    narration_chars,
    narration_pages,
    player_turns,
    run_pass,
    transcript,
)
from aigm.world.scripted import ScriptedCurator


def convo(*gm_texts):
    messages = []
    for i, text in enumerate(gm_texts):
        messages.append({"role": "user", "content": [{"type": "text", "text": f"action {i}"}]})
        messages.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
    return messages


class FakeCurator:
    """Answers with whatever the test hands it."""

    def __init__(self, extraction=None, labels=None, expansions=None, same_as=None):
        self.extraction = extraction or Extraction()
        self.labels = labels
        self.expansions = list(expansions or [])
        self.same_as = same_as or {}
        self.requests = []

    async def extract(self, request):
        self.requests.append(request)
        return self.extraction

    async def reconcile(self, request):
        self.requests.append(request)
        labels = self.labels(request) if callable(self.labels) else [Label(i.index, "new") for i in request.items]
        return ReconcileResult(labels, self.same_as)

    async def expand(self, request):
        self.requests.append(request)
        return self.expansions.pop(0) if self.expansions else Extraction()


@pytest.fixture
def world():
    w = World()
    town = w.add_entity("Ashby", "location")
    mine = w.add_entity("Harrow Mine", "location", aliases=["the old mine"])
    w.add_fact("The Harrow Mine lies east of Ashby.", [mine.id, town.id], aspect="approach", disclosure="known")
    w.add_fact("The mine's lower gallery joins a cellar under Ashby.", [mine.id], aspect="secret")
    w.add_fact("Ashby is a market town on a river.", [town.id], aspect="layout", disclosure="known")
    w.set_scene(town.id)
    return w


def extraction(*facts, **kw):
    return Extraction(facts=list(facts), **kw)


def fp(text, about, disclosure="known", **kw):
    return FactProposal(text, about, None, disclosure, **kw)


# ---- reading the history ------------------------------------------------------------------


def test_narration_counts_only_gm_text():
    msgs = convo("a" * 100, "b" * 50)
    msgs.append({"role": "assistant", "content": [{"type": "thinking", "thinking": "x" * 999}]})
    msgs[0]["content"][0]["text"] = "p" * 5000
    assert narration_chars(msgs) == 150 and narration_chars(msgs, 2) == 50
    assert narration_pages(msgs, page_chars=75) == 2.0 and narration_pages(msgs, 2, 100) == 0.5
    assert player_turns(msgs) == 2


def test_transcript_has_speakers_and_world_tool_calls_but_no_dice_or_system_notes():
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "[System: The adventure begins.]"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "You wake."}]},
        {"role": "user", "content": [{"type": "text", "text": "I roll."}]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t", "name": "roll_dice", "input": {"expression": "1d20"}},
            {"type": "tool_use", "id": "u", "name": "set_scene", "input": {"elapsed_hours": 2}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "7"}]},
    ]  # fmt: skip
    text = transcript(msgs)
    assert text == "GM: You wake.\n\nPLAYER: I roll.\n\n[GM called set_scene: {'elapsed_hours': 2}]"


# ---- extract and apply --------------------------------------------------------------------


async def test_pass_extracts_entities_facts_scene_and_time(world):
    cur = ScriptedCurator()
    msgs = convo("[[fact: Wren:npc | Wren pours drinks at the Rusty Flagon.]] [[at: Rusty Flagon]] [[present: Wren]] [[elapsed: 3]]")
    before = world.to_dict()
    result = await run_pass(world, msgs, cur)
    assert world.to_dict() == before  # the pass works on a snapshot
    assert cur.calls[:2] == ["extract", "reconcile"]
    live = world.copy()
    applied = apply_ops(live, result.ops)
    assert not applied.skipped
    wren = live.find("Wren")
    assert wren.kind == "npc" and live.find("Rusty Flagon").kind == "location"
    (fact,) = [f for f in live.facts_about(wren.id) if f.source == "play"]
    assert (fact.disclosure, fact.turn) == ("known", 1)
    assert live.scene.location == live.find("Rusty Flagon").id and live.scene.present == [wren.id]
    assert live.time == WorldTime(1, 11) and live.processed_through == 2


async def test_applying_the_ops_to_the_unchanged_world_matches_the_pass_snapshot(world):
    cur = ScriptedCurator()
    msgs = convo("[[fact: Wren | Wren pours drinks at the Rusty Flagon.]] [[at: Harrow Mine]]")
    result = await run_pass(world, msgs, cur)
    a, b = world.copy(), world.copy()
    apply_ops(a, result.ops)
    apply_ops(b, result.ops)
    apply_ops(b, result.ops)  # replaying is harmless
    assert a.to_dict()["facts"] == b.to_dict()["facts"] and a.to_dict()["entities"] == b.to_dict()["entities"]


async def test_only_unprocessed_messages_are_read(world):
    cur = FakeCurator()
    world.mark_processed(2)
    await run_pass(world, convo("old", "new"), cur)
    assert cur.requests[0].transcript == "PLAYER: action 1\n\nGM: new"
    cur2 = FakeCurator()
    world.mark_processed(4)
    result = await run_pass(world, convo("old", "new"), cur2)
    assert cur2.requests == [] or all(not hasattr(r, "transcript") for r in cur2.requests)
    assert result.ops[-1].count == 4


async def test_nothing_to_extract_still_advances_the_marker_and_can_expand(world):
    result = await run_pass(world, convo("quiet"), FakeCurator())
    assert [type(o).__name__ for o in result.ops][-2:] == ["SettleTime", "MarkProcessed"]


async def test_reveals_turn_hidden_facts_known(world):
    cur = ScriptedCurator()
    result = await run_pass(world, convo("[[reveal: f0002]]"), cur)
    assert Reveal("f0002", 1) in result.ops
    live = world.copy()
    apply_ops(live, result.ops)
    assert live.fact("f0002").disclosure == "known" and live.fact("f0002").revealed_turn == 1


async def test_a_known_proposal_that_repeats_a_hidden_fact_reveals_it_without_a_model_call(world):
    cur = FakeCurator(extraction(fp("The mine's lower gallery joins a cellar under Ashby", ["Harrow Mine"])))
    result = await run_pass(world, convo("x"), cur)
    assert Reveal("f0002", 1) in result.ops and not any(isinstance(o, AddFact) for o in result.ops)
    assert not any(type(r).__name__ == "ReconcileRequest" for r in cur.requests)


async def test_a_repeated_known_fact_is_dropped(world):
    cur = FakeCurator(extraction(fp("Ashby is a market town on a river.", ["Ashby"])))
    result = await run_pass(world, convo("x"), cur)
    assert not any(isinstance(o, (AddFact, Reveal)) for o in result.ops)


async def test_unknown_subjects_are_skipped_not_fatal(world):
    cur = FakeCurator(extraction(fp("Gorr guards the old bridge.", ["Gorr"]), fp("Ashby has a stone bridge.", ["Ashby"])))
    result = await run_pass(world, convo("x"), cur)
    live = world.copy()
    assert not apply_ops(live, result.ops).skipped
    assert any("unknown entity 'Gorr'" in n for n in result.notes)
    assert any(f.text == "Ashby has a stone bridge." for f in live.facts_about("e001"))


# ---- precedence ---------------------------------------------------------------------------


async def test_a_clash_with_a_known_fact_is_rejected_and_queues_a_correction(world):
    cur = ScriptedCurator()
    result = await run_pass(world, convo("[[contradict: f0003 | Ashby | Ashby is a ruined village with no market.]]"), cur)
    live = world.copy()
    apply_ops(live, result.ops)
    assert live.fact("f0003").active and live.fact("f0003").text == "Ashby is a market town on a river."
    assert not [f for f in live.facts.values() if f.source == "play"]
    (note,) = live.corrections
    assert "Ashby is a market town on a river." in note["text"] and note["turn"] == 1
    assert any("rejected" in n for n in result.notes)


async def test_a_clash_with_a_hidden_fact_supersedes_it(world):
    cur = ScriptedCurator()
    result = await run_pass(world, convo("[[contradict: f0002 | Harrow Mine | The mine's lower gallery is flooded and sealed.]]"), cur)
    live = world.copy()
    apply_ops(live, result.ops)
    old = live.fact("f0002")
    assert old.status == "superseded"
    new = live.fact(old.superseded_by)
    assert (new.text, new.source, new.disclosure, new.aspect) == ("The mine's lower gallery is flooded and sealed.", "play", "known", "secret")
    assert live.corrections == []


async def test_of_two_clashing_proposals_the_later_wins(world):
    cur = FakeCurator(
        extraction(fp("Ashby has a stone bridge over the river.", ["Ashby"]), fp("Ashby has a wooden bridge over the river.", ["Ashby"])),
        labels=lambda req: [Label(0, "new"), Label(1, "contradicts", with_proposal=0)],
    )
    result = await run_pass(world, convo("x"), cur)
    texts = [o.text for o in result.ops if isinstance(o, AddFact)]
    assert texts == ["Ashby has a wooden bridge over the river."]


async def test_entity_identity_adds_an_alias_instead_of_a_duplicate(world):
    cur = FakeCurator(
        Extraction(
            entities=[EntityProposal("Old Shaft", "location")],
            facts=[fp("The Old Shaft has a rusted lift cage.", ["Old Shaft"])],
        ),
        same_as={"Old Shaft": "e002"},
    )
    result = await run_pass(world, convo("x"), cur)
    live = world.copy()
    apply_ops(live, result.ops)
    assert len(live.entities) == 2 and live.find("old shaft").id == "e002"
    assert "rusted lift cage" in [f for f in live.facts_about("e002")][-1].text


async def test_lookalike_entities_are_put_to_the_curator_as_questions(world):
    cur = FakeCurator(Extraction(entities=[EntityProposal("Harrow Pit", "location")]))
    await run_pass(world, convo("x"), cur)
    req = [r for r in cur.requests if hasattr(r, "questions")][0]
    assert [c.name for c in req.questions[0].candidates] == ["Harrow Mine"]


# ---- time ---------------------------------------------------------------------------------


async def test_hours_the_gm_already_reported_are_not_counted_twice(world):
    world.advance_time(2, reported=True)
    result = await run_pass(world, convo("x"), FakeCurator(Extraction(elapsed_hours=5)))
    live = world.copy()
    apply_ops(live, result.ops)
    assert live.time == WorldTime(1, 8 + 2 + 3) and live.reported_hours == 0
    # narration that covered less than the GM reported adds nothing
    live2 = world.copy()
    apply_ops(live2, (await run_pass(world, convo("x"), FakeCurator(Extraction(elapsed_hours=1)))).ops)
    assert live2.time == WorldTime(1, 10)


# ---- expansion ----------------------------------------------------------------------------


@pytest.fixture
def graph():
    w = World()
    region = w.add_entity("Thornwood", "location")
    town = w.add_entity("Ashby", "location", parent=region.id)
    inn = w.add_entity("Rusty Flagon", "location", parent=town.id)
    wren = w.add_entity("Wren", "npc")
    mine = w.add_entity("Harrow Mine", "location", parent=region.id)
    guild = w.add_entity("Thorn Guild", "faction")
    far = w.add_entity("Karth", "location")
    farther = w.add_entity("Karth Docks", "location", parent=far.id)
    w.add_fact("Wren pours drinks at the Rusty Flagon.", [wren.id, inn.id])
    w.add_fact("The Thorn Guild controls the toll road through Thornwood.", [guild.id, region.id])
    w.add_fact("The road from Ashby to the mine is a day's walk.", [town.id, mine.id])
    w.add_fact("Karth lies far to the south.", [far.id])
    w.set_scene(inn.id, [wren.id])
    return w


def test_frontier_ranks_by_closeness_and_sets_depth(graph):
    names = {e.name: (tier, missing) for e, tier, missing in frontier(graph, 20)}
    order = [e.name for e, _, _ in frontier(graph, 20)]
    assert order[0] in ("Rusty Flagon", "Wren")  # the scene and who is present come first
    assert names["Rusty Flagon"][0] == "full" and names["Wren"][0] == "full"
    assert "interior" in names["Rusty Flagon"][1] and "secret" in names["Rusty Flagon"][1]
    assert names["Ashby"][0] == "most" and "interior" not in names["Ashby"][1]
    assert names["Harrow Mine"][0] == "sketch" and names["Harrow Mine"][1] == ["overview", "approach", "entry", "inhabitants"]
    assert "Karth" not in names and "Karth Docks" not in names  # too far away
    assert len(frontier(graph, 2)) == 2 and frontier(World(), 5) == []


def test_frontier_skips_covered_aspects_and_treats_known_entities_as_closer(graph):
    graph.add_fact("Wren is a barmaid with a quick wit.", [graph.find("Wren").id], aspect="role")
    wren = [m for e, t, m in frontier(graph, 20) if e.name == "Wren"][0]
    assert "role" not in wren and "motivation" in wren
    graph.add_fact("Karth is rumored to be rich.", [graph.find("Karth").id], disclosure="known")
    assert "Karth" in [e.name for e, _, _ in frontier(graph, 20)]


async def test_expansion_adds_hidden_generated_facts_for_the_frontier(graph):
    cur = ScriptedCurator()
    result = await run_pass(graph, convo("quiet"), cur, config=PassConfig(max_expand_entities=2))
    assert cur.calls.count("expand") == 2
    live = graph.copy()
    apply_ops(live, result.ops)
    new = [f for f in live.facts.values() if f.source == "generated"]
    here = live.scene.location
    assert new and all(
        f.disclosure == ("known" if f.aspect in ARRIVAL_ASPECTS and f.subject == here else "hidden") for f in new
    )
    assert live.find("Rusty Flagon Cellar").parent == live.find("Rusty Flagon").id
    assert live.coverage(live.find("Rusty Flagon").id) >= {"overview", "items"}


async def test_expansion_requests_carry_context(graph):
    cur = FakeCurator()
    await run_pass(graph, convo("quiet"), cur, setting="A grim border region.", config=PassConfig(max_expand_entities=1))
    req = cur.requests[-1]
    assert req.entity.name in ("Rusty Flagon", "Wren") and req.tier == "full" and req.setting == "A grim border region."
    assert req.missing and req.time == WorldTime(1, 8)


async def test_unconnected_new_entities_are_dropped_with_their_facts(graph):
    expansion = Extraction(
        entities=[
            EntityProposal("Marrow's Hut", "location", parent="Thornwood"),
            EntityProposal("Old Marrow", "npc"),  # linked only through the hut's fact: connected via the hut
            EntityProposal("Lost City", "location"),
            EntityProposal("Lost King", "npc"),
        ],
        facts=[
            fp("Old Marrow lives alone in Marrow's Hut.", ["Old Marrow", "Marrow's Hut"], "hidden"),
            fp("The Lost King sleeps beneath the Lost City.", ["Lost King", "Lost City"], "hidden"),
        ],
    )
    cur = FakeCurator(expansions=[expansion])
    result = await run_pass(graph, convo("x"), cur, config=PassConfig(max_expand_entities=1))
    live = graph.copy()
    apply_ops(live, result.ops)
    assert live.find("Marrow's Hut") and live.find("Old Marrow") and live.find("Lost City") is None
    assert not any("Lost King" in f.text for f in live.facts.values())
    assert any("unconnected entity" in n for n in result.notes)


async def test_expansion_is_forced_hidden_and_aspects_are_checked(graph):
    expansion = Extraction(
        facts=[
            FactProposal("Wren once served a king in exile.", ["Wren"], "motivation", "known"),
            FactProposal("The Rusty Flagon has a loose floorboard.", ["Rusty Flagon"], "nonsense", "known"),
        ]
    )
    cur = FakeCurator(expansions=[expansion])
    result = await run_pass(graph, convo("x"), cur, config=PassConfig(max_expand_entities=1))
    facts = [o for o in result.ops if isinstance(o, AddFact)]
    assert {f.disclosure for f in facts} == {"hidden"} and {f.source for f in facts} == {"generated"}
    assert [f.aspect for f in facts] == ["motivation", None]


async def test_expansion_caps(graph):
    many = Extraction(
        entities=[EntityProposal(f"Hut {i}", "location", parent="Thornwood") for i in range(9)],
        facts=[fp(f"Hut {i} stands empty and quiet.", [f"Hut {i}"], "hidden") for i in range(9)],
    )
    cfg = PassConfig(max_expand_entities=1, max_entities_per_call=4, max_facts_per_call=3)
    result = await run_pass(graph, convo("x"), FakeCurator(expansions=[many]), config=cfg)
    from aigm.world.ops import AddEntity

    assert sum(isinstance(o, AddEntity) for o in result.ops) == 4
    assert sum(isinstance(o, AddFact) for o in result.ops) == 3


async def test_a_correction_can_replace_a_hidden_fact_but_never_a_known_one(graph):
    hidden = graph.add_fact("The Rusty Flagon has no cellar at all.", [graph.find("Rusty Flagon").id])
    known = graph.add_fact("Wren is the owner of the Rusty Flagon.", [graph.find("Wren").id], disclosure="known")
    expansion = Extraction(
        facts=[
            FactProposal("The Rusty Flagon has a cellar full of casks.", ["Rusty Flagon"], None, "hidden", replaces=hidden.id),
            FactProposal("Wren is only a tenant of the Rusty Flagon.", ["Wren"], None, "hidden", replaces=known.id),
        ]
    )
    result = await run_pass(graph, convo("x"), FakeCurator(expansions=[expansion]), config=PassConfig(max_expand_entities=1))
    live = graph.copy()
    apply_ops(live, result.ops)
    assert live.fact(hidden.id).status == "superseded" and live.fact(known.id).active
    assert any(f.text == "Wren is only a tenant of the Rusty Flagon." and f.disclosure == "hidden" for f in live.facts.values())


async def test_a_curator_failure_leaves_everything_alone(world):
    class Boom(FakeCurator):
        async def extract(self, request):
            raise RuntimeError("model down")

    before = world.to_dict()
    with pytest.raises(RuntimeError):
        await run_pass(world, convo("x"), Boom())
    assert world.to_dict() == before


# ---- a new person must end up with a fact (the Elian case) ---------------------------------


class Sequenced(FakeCurator):
    """Extraction answers in turn, so a retry can be told apart from the first ask."""

    def __init__(self, *answers):
        super().__init__()
        self.answers = list(answers)

    async def extract(self, request):
        self.requests.append(request)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def elian(text, aspect=None):
    return Extraction(
        entities=[EntityProposal("Elian", "npc")], facts=[FactProposal(text, ["Elian"], aspect, "known")]
    )


async def test_a_fact_that_speaks_of_the_party_is_asked_for_again(world):
    cur = Sequenced(
        elian("Elian asked the party to move a crate."), elian("Elian needs a crate moved past the harbor guards.")
    )
    result = await run_pass(world, convo("Elian begs for help."), cur, config=PassConfig(digests=False, max_expand_entities=0))
    asks = [r for r in cur.requests if hasattr(r, "transcript")]
    assert len(asks) == 2 and "asked the party" in asks[1].feedback[0]
    apply_ops(world, result.ops)
    assert [f.text for f in world.facts_about(world.find("Elian").id)] == ["Elian needs a crate moved past the harbor guards."]


async def test_a_retry_that_is_no_better_keeps_the_first_answer_and_a_failed_retry_is_harmless(world):
    bad = elian("Elian asked the party to move a crate.")
    cur = Sequenced(bad)
    fresh = world.copy()
    result = await run_pass(world, convo("x"), cur, config=PassConfig(digests=False, max_expand_entities=0))
    assert world.find("Elian") is None and any(isinstance(o, type(result.ops[0])) for o in result.ops)
    apply_ops(world, result.ops)
    assert world.find("Elian") is not None and not world.facts_about(world.find("Elian").id)  # nothing better was offered

    class Flaky(Sequenced):
        async def extract(self, request):
            if request.feedback:
                raise RuntimeError("down")
            return await super().extract(request)

    again = await run_pass(fresh, convo("x"), Flaky(elian("Elian asked the party to move a crate.")), config=PassConfig(digests=False, max_expand_entities=0))
    assert any("retry failed" in n for n in again.notes)


async def test_a_misfiled_aspect_costs_the_label_not_the_fact(world):
    cur = FakeCurator(elian("Elian carries a crate that officials would seize on sight.", aspect="secret"))
    result = await run_pass(world, convo("Elian waits."), cur, config=PassConfig(digests=False, max_expand_entities=0))
    notes = apply_ops(world, result.ops).skipped
    assert not notes
    fact = world.facts_about(world.find("Elian").id)[0]
    assert fact.aspect is None and fact.disclosure == "known"
