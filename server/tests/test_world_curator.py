import json
from types import SimpleNamespace

import pytest

from aigm.app import create_app
from aigm.config import Settings
from aigm.prompts import PromptLibrary
from aigm.world import World, WorldTime
from aigm.world.anthropic_curator import (
    EXPAND_SCHEMA,
    EXTRACT_SCHEMA,
    JUDGE_SCHEMA,
    RECONCILE_SCHEMA,
    AnthropicCurator,
    CuratorError,
)
from aigm.world.curator import (
    EntityProposal,
    EntityQuestion,
    ExpandRequest,
    ExtractRequest,
    Extraction,
    FactProposal,
    ReconcileItem,
    ReconcileRequest,
)
from aigm.world.independence import independence_problem, standalone_problem
from aigm.world.ops import AddFact, apply_ops
from aigm.world.passes import PassConfig, run_pass
from aigm.world.render import render_expand, render_extract, render_reconcile
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService
from tests.test_world_pass import FakeCurator, convo, fp, graph  # noqa: F401  (graph is a fixture)

# ---- independence rules -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,party,expected",
    [
        ("The mine was abandoned forty years ago after a collapse.", [], None),
        ("A party of bandits camps by the ford.", [], None),  # "party" alone is fine
        ("You will find the key under the stone.", [], "addresses the player"),
        ("The hut is where your guide lives.", [], "addresses the player"),
        ("Wren is wary of the party.", [], "mentions the party"),
        ("The adventurers are expected at dusk.", [], "mentions the party"),
        ("Wren hates Test Hero for an old debt.", ["Test Hero"], "mentions the player character Test Hero"),
        ("Wren hates test hero for an old debt.", ["Test Hero"], "mentions the player character"),
        ("Wren hates Heroic Ned for an old debt.", ["Hero"], None),  # whole words only
        ("The mine collapsed recently, killing six miners.", [], "recently"),
        ("Dawn is when the ferry leaves.", [], None),
    ],
)
def test_independence_problems(text, party, expected):
    got = independence_problem(text, party)
    assert (got is None) if expected is None else (got is not None and expected in got)


def test_standalone_ignores_names_and_recency():
    assert standalone_problem("Wren hates Test Hero.") is None
    assert standalone_problem("Wren said you are late.") is not None


# ---- rules in the pass --------------------------------------------------------------------


async def test_a_violating_expansion_is_retried_once_with_feedback(graph):
    bad = Extraction(facts=[
        FactProposal("Wren has been waiting for the party to arrive.", ["Wren"], "motivation"),
        FactProposal("Wren was born in Karth thirty years ago.", ["Wren"], "role"),
    ])  # fmt: skip
    good = Extraction(facts=[FactProposal("Wren saves coins to buy back her family's ferry.", ["Wren"], "motivation")])
    cur = FakeCurator(expansions=[bad, good])
    result = await run_pass(graph, convo("x"), cur, config=PassConfig(max_expand_entities=1))
    expansions = [r for r in cur.requests if hasattr(r, "tier")]
    assert len(expansions) == 2 and expansions[0].feedback == []
    assert expansions[1].feedback == ["'Wren has been waiting for the party to arrive.': mentions the party"]
    texts = [o.text for o in result.ops if isinstance(o, AddFact)]
    assert texts == ["Wren saves coins to buy back her family's ferry."]


async def test_facts_that_still_violate_after_the_retry_are_dropped_and_party_names_count(graph):
    bad = Extraction(facts=[
        FactProposal("Wren owes Test Hero a favour.", ["Wren"], "relationships"),
        FactProposal("Wren keeps a ledger of every debt owed to her.", ["Wren"], "knowledge"),
    ])  # fmt: skip
    cur = FakeCurator(expansions=[bad, bad])
    result = await run_pass(graph, convo("x"), cur, party_names=["Test Hero"], config=PassConfig(max_expand_entities=1))
    assert [o.text for o in result.ops if isinstance(o, AddFact)] == ["Wren keeps a ledger of every debt owed to her."]
    assert any("mentions the player character Test Hero" in n for n in result.notes)


async def test_a_clean_expansion_is_not_asked_twice(graph):
    cur = ScriptedCurator()
    await run_pass(graph, convo("x"), cur, config=PassConfig(max_expand_entities=2))
    assert cur.calls.count("expand") == 2


async def test_the_model_judge_can_drop_subtle_dependence(graph):
    class Judge(FakeCurator):
        async def judge_independence(self, texts):
            return [i for i, t in enumerate(texts) if "stranger" in t]

    exp = Extraction(facts=[
        FactProposal("A stranger arrives whenever heroes come asking questions.", ["Wren"], "knowledge"),
        FactProposal("Wren keeps a ledger of every debt owed to her.", ["Wren"], "motivation"),
    ])  # fmt: skip
    result = await run_pass(graph, convo("x"), Judge(expansions=[exp]), config=PassConfig(max_expand_entities=1))
    assert [o.text for o in result.ops if isinstance(o, AddFact)] == ["Wren keeps a ledger of every debt owed to her."]
    assert any("judged" in n for n in result.notes)


async def test_a_failing_judge_does_not_fail_the_pass(graph):
    class Judge(FakeCurator):
        async def judge_independence(self, texts):
            raise RuntimeError("down")

    exp = Extraction(facts=[FactProposal("Wren keeps a ledger of every debt owed to her.", ["Wren"], "motivation")])
    result = await run_pass(graph, convo("x"), Judge(expansions=[exp]), config=PassConfig(max_expand_entities=1))
    assert any(isinstance(o, AddFact) for o in result.ops)


async def test_extracted_facts_that_address_the_player_are_dropped(graph):
    cur = FakeCurator(Extraction(facts=[fp("You find that Ashby has a stone bridge.", ["Ashby"]), fp("Ashby has a stone bridge.", ["Ashby"])]))
    result = await run_pass(graph, convo("x"), cur, config=PassConfig(max_expand_entities=0))
    assert [o.text for o in result.ops if isinstance(o, AddFact)] == ["Ashby has a stone bridge."]


async def test_the_extractor_is_shown_the_gm_only_facts_near_the_scene(graph):
    graph.add_fact("The inn's cellar hides a smugglers' door.", [graph.find("Rusty Flagon").id])
    graph.add_fact("Karth has a harbour full of ships.", [graph.find("Karth").id])
    cur = FakeCurator()
    await run_pass(graph, convo("x"), cur, config=PassConfig(max_expand_entities=0))
    req = [r for r in cur.requests if hasattr(r, "transcript")][0]
    texts = [f.text for f in req.hidden_facts]
    assert "The inn's cellar hides a smugglers' door." in texts and "Wren pours drinks at the Rusty Flagon." in texts
    assert "Karth has a harbour full of ships." not in texts


# ---- rendering ----------------------------------------------------------------------------


def test_render_extract_has_all_sections(graph):
    secret = graph.add_fact("The inn's cellar hides a smugglers' door.", [graph.find("Rusty Flagon").id])
    req = ExtractRequest("GM: Hello.", "A grim land.", WorldTime(2, 9), "Rusty Flagon", ["Wren"], ["Wren", "Ashby"], [secret])
    text = render_extract(req)
    assert "A grim land." in text and "Day 2, 09:00" in text and "The party was at: Rusty Flagon" in text
    assert "Wren; Ashby" in text and f"- {secret.id}: The inn's cellar hides" in text and text.endswith("GM: Hello.")


def test_render_reconcile_lists_neighbors_and_identity_questions(graph):
    fact = graph.facts_about(graph.find("Wren").id)[0]
    req = ReconcileRequest(
        [ReconcileItem(0, FactProposal("Wren owns the inn.", ["Wren"], None, "known"), [fact]),
         ReconcileItem(1, FactProposal("Ashby is old.", ["Ashby"]), [])],
        [EntityQuestion(EntityProposal("Old Shaft", "location"), [graph.find("Harrow Mine")])],
    )  # fmt: skip
    text = render_reconcile(req)
    assert "[0] about Wren (known): Wren owns the inn." in text and f"- {fact.id} [hidden] {fact.text}" in text
    assert "Related existing facts: none" in text and 'Proposed location "Old Shaft"' in text and "Harrow Mine (location)" in text


def test_render_expand_includes_the_aspect_guide_and_feedback(graph):
    guides = PromptLibrary().aspect_guides()
    inn = graph.find("Rusty Flagon")
    req = ExpandRequest(inn, "full", ["approach", "secret"], graph.facts_about(inn.id), graph.parent_chain(inn.id),
                        [], [], "A grim land.", WorldTime(1, 8), ["Ashby", "Wren"], ["'x': mentions the party"])  # fmt: skip
    text = render_expand(req, guides)
    assert "- approach: where it is and how to get there" in text and "- secret: something hidden" in text
    assert "Located in: Thornwood > Ashby" in text and "## Tier\nfull" in text
    assert "Your previous answer was rejected" in text and "- 'x': mentions the party" in text
    assert "## Names already used" in text and "Ashby; Wren" in text


# ---- prompt files -------------------------------------------------------------------------


def test_world_prompts_and_aspect_guides_cover_every_aspect():
    from aigm.world.model import ASPECTS

    lib = PromptLibrary()
    for name in ("extract", "reconcile", "expand", "independence"):
        assert len(lib.world_prompt(name)) > 300
    guides = lib.aspect_guides()
    for kind, aspects in ASPECTS.items():
        assert set(aspects) <= set(guides[kind]), kind


def test_world_prompts_can_be_overridden(tmp_path):
    (tmp_path / "world").mkdir()
    (tmp_path / "world" / "extract.md").write_text("<!-- note -->My extractor.")
    lib = PromptLibrary(tmp_path)
    assert lib.world_prompt("extract") == "My extractor." and "world" in lib.world_prompt("expand").lower()
    with pytest.raises(ValueError):
        lib.world_prompt("nope")


# ---- the model-backed curator -------------------------------------------------------------


class FakeMessages:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def create(self, **params):
        self.calls.append(params)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        stop = "end_turn"
        if isinstance(reply, tuple):
            reply, stop = reply
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking="hm"), SimpleNamespace(type="text", text=text)],
            stop_reason=stop,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def curator(*replies, **kw):
    fake = SimpleNamespace(messages=FakeMessages(*replies))
    return AnthropicCurator(api_key="k", prompts=PromptLibrary(), client=fake, **kw), fake.messages


def extract_request():
    return ExtractRequest("GM: Wren waves.", "", WorldTime(), None, [], [], [])


def walk(schema, path="$"):
    """Every object in a schema must be closed and require all its properties."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            assert schema["additionalProperties"] is False, path
            assert set(schema["required"]) == set(schema["properties"]), path
        assert not {"minimum", "maximum", "minLength", "maxLength", "$ref"} & set(schema), path
        for k, v in schema.items():
            walk(v, f"{path}.{k}")
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            walk(v, f"{path}[{i}]")


@pytest.mark.parametrize("schema", [EXTRACT_SCHEMA, RECONCILE_SCHEMA, EXPAND_SCHEMA, JUDGE_SCHEMA])
def test_schemas_are_closed_and_use_only_supported_features(schema):
    walk(schema)


async def test_extract_request_and_parsing():
    reply = {
        "entities": [{"name": "Wren", "kind": "npc", "aliases": ["the barmaid"], "parent": None}],
        "facts": [{"text": "Wren pours drinks at the Rusty Flagon.", "about": ["Wren"], "aspect": "role",
                   "disclosure": "known", "evidence": "Wren waves."}],
        "reveals": ["f0002"], "location": "Rusty Flagon", "present": ["Wren"], "elapsed_hours": 2,
    }  # fmt: skip
    cur, calls = curator(reply)
    ex = await cur.extract(extract_request())
    (params,) = calls.calls
    assert params["model"] == "claude-haiku-5-5"
    assert params["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": EXTRACT_SCHEMA}}
    assert params["system"][0]["text"] == PromptLibrary().world_prompt("extract")
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in params and "tool_choice" not in params and "temperature" not in params
    assert params["messages"][0]["content"].endswith("GM: Wren waves.")
    assert ex.entities == [EntityProposal("Wren", "npc", ["the barmaid"], None)]
    assert ex.facts[0] == FactProposal("Wren pours drinks at the Rusty Flagon.", ["Wren"], "role", "known", "Wren waves.", None)
    assert (ex.reveals, ex.location, ex.present, ex.elapsed_hours) == (["f0002"], "Rusty Flagon", ["Wren"], 2)


async def test_extract_parsing_is_defensive():
    cur, _ = curator({"entities": "x", "facts": [{"text": 5}, {"text": "A fact.", "about": ["A"], "disclosure": "weird"}],
                      "reveals": [1, "f1"], "location": 3, "present": None, "elapsed_hours": True})  # fmt: skip
    ex = await cur.extract(extract_request())
    assert ex.entities == [] and ex.reveals == ["f1"] and ex.location is None and ex.present is None
    assert ex.elapsed_hours == 0 and [f.disclosure for f in ex.facts] == ["hidden"]


async def test_reconcile_parsing(graph):
    reply = {
        "labels": [{"index": 0, "label": "contradicts", "existing_id": "f0001", "with_proposal": None},
                   {"index": 1, "label": "contradicts", "existing_id": None, "with_proposal": 0},
                   {"index": 2, "label": "bogus", "existing_id": None, "with_proposal": None}],
        "same_as": [{"name": "Old Shaft", "entity_id": "e002"}],
    }  # fmt: skip
    cur, calls = curator(reply)
    out = await cur.reconcile(ReconcileRequest([ReconcileItem(0, fp("A fact here now.", ["Ashby"]), [])], []))
    assert [(l.index, l.label, l.existing_id, l.with_proposal) for l in out.labels] == [
        (0, "contradicts", "f0001", None), (1, "contradicts", None, 0)]  # fmt: skip
    assert out.same_as == {"Old Shaft": "e002"} and calls.calls[0]["model"] == "claude-haiku-5-5"


async def test_expand_uses_the_stronger_model_and_forces_hidden_defaults(graph):
    reply = {"entities": [{"name": "Hut", "kind": "location", "aliases": [], "parent": "Thornwood"}],
             "facts": [{"text": "The Hut stands empty.", "about": ["Hut"], "aspect": None, "replaces": None}]}  # fmt: skip
    cur, calls = curator(reply, expand_model="claude-sonnet-5-5", expand_effort="high")
    inn = graph.find("Rusty Flagon")
    req = ExpandRequest(inn, "full", ["approach"], [], [], [], [], "", WorldTime(), [], [])
    ex = await cur.expand(req)
    params = calls.calls[0]
    assert params["model"] == "claude-sonnet-5-5" and params["output_config"]["effort"] == "high"
    assert params["output_config"]["format"]["schema"] == EXPAND_SCHEMA
    assert ex.entities[0].parent == "Thornwood" and ex.facts[0].disclosure == "hidden"


async def test_models_and_efforts_are_configurable():
    cur, calls = curator({"entities": [], "facts": [], "reveals": [], "location": None, "present": None, "elapsed_hours": 0},
                         model="claude-sonnet-5-5", effort="medium")  # fmt: skip
    await cur.extract(extract_request())
    assert calls.calls[0]["model"] == "claude-sonnet-5-5" and calls.calls[0]["output_config"]["effort"] == "medium"


async def test_judge_independence():
    cur, calls = curator({"violations": [{"index": 1, "reason": "x"}, {"index": "a", "reason": "y"}]})
    assert await cur.judge_independence(["one", "two"]) == [1]
    assert calls.calls[0]["messages"][0]["content"] == "[0] one\n[1] two"


@pytest.mark.parametrize(
    "reply,match",
    [("not json", "did not return JSON"), ("[1, 2]", "not an object"), (("{}", "refusal"), "refusal"),
     (("{}", "max_tokens"), "max_tokens")],
)  # fmt: skip
async def test_unusable_answers_raise_curator_error(reply, match):
    cur, _ = curator(reply)
    with pytest.raises(CuratorError, match=match):
        await cur.extract(extract_request())


async def test_an_api_error_propagates_so_the_pass_fails_harmlessly():
    cur, _ = curator(RuntimeError("503"))
    with pytest.raises(RuntimeError):
        await cur.extract(extract_request())


async def test_a_full_pass_with_the_model_curator(graph):
    extract = {"entities": [{"name": "Fenn", "kind": "npc", "aliases": [], "parent": None}],
               "facts": [{"text": "Fenn trades furs in Ashby.", "about": ["Fenn", "Ashby"], "aspect": None,
                          "disclosure": "known", "evidence": ""}],
               "reveals": [], "location": None, "present": None, "elapsed_hours": 1}  # fmt: skip
    reconcile = {"labels": [{"index": 0, "label": "new", "existing_id": None, "with_proposal": None}], "same_as": []}
    expand = {"entities": [], "facts": [{"text": "The Rusty Flagon was built by a retired sea captain.", "about": ["Rusty Flagon"],
                                         "aspect": "history", "replaces": None}]}  # fmt: skip
    judge = {"violations": []}
    cur, calls = curator(extract, reconcile, expand, judge)
    result = await run_pass(graph, convo("Fenn sells furs."), cur, config=PassConfig(max_expand_entities=1))
    live = graph.copy()
    assert not apply_ops(live, result.ops).skipped
    assert live.find("Fenn") and live.time == WorldTime(1, 9)
    gen = [f for f in live.facts.values() if f.source == "generated"]
    assert [f.text for f in gen][-1] == "The Rusty Flagon was built by a retired sea captain."
    assert [c["model"] for c in calls.calls] == ["claude-haiku-5-5", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]


# ---- wiring -------------------------------------------------------------------------------


def settings(tmp_path, **kw):
    return Settings(save_dir=tmp_path, anthropic_api_key="k", _env_file=None, **kw)


def test_real_mode_gets_a_model_curator_with_configured_models(tmp_path):
    app = create_app(settings(tmp_path, AIGM_WORLD_MODEL="m-small", AIGM_WORLD_EXPAND_MODEL="m-big", AIGM_WORLD_EVERY_PAGES=5))
    svc = app.state.curator
    assert isinstance(svc, CuratorService) and isinstance(svc.curator, AnthropicCurator)
    assert (svc.curator.model, svc.curator.expand_model, svc.every_pages) == ("m-small", "m-big", 5)


def test_the_curator_can_be_turned_off_and_test_mode_is_scripted(tmp_path):
    assert create_app(settings(tmp_path, AIGM_WORLD_CURATOR="false")).state.curator is None
    app = create_app(Settings(test_mode=True, save_dir=tmp_path, _env_file=None))
    assert isinstance(app.state.curator.curator, ScriptedCurator)


def test_a_curator_can_be_injected(tmp_path):
    svc = CuratorService(ScriptedCurator())
    assert create_app(settings(tmp_path), curator=svc).state.curator is svc


def test_world_dataclass_is_untouched_by_imports():
    assert World().is_empty
