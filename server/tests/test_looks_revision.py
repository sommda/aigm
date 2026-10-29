import pytest

from aigm.looks import Look
from aigm.session.state import GameState, Phase
from aigm.session.store import Session
from aigm.world import World
from aigm.world.anthropic_curator import REVISE_SCHEMA
from aigm.world.curator import CuratorError, LookRevision, ReviseRequest, ReviseSubject
from aigm.world.describe import (
    about,
    describing,
    revision_candidates,
    run_looks,
    run_revisions,
    sentences,
)
from aigm.world.ops import ReviseLook, apply_ops
from aigm.world.render import render_looks, render_revise
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService
from tests.test_looks import make_look
from tests.test_world_curator import curator as model_curator, walk

CAMPAIGN = {"setting": "A river town.", "party": [{"name": "Toby Reed", "sheet": "Rogue."}]}


def edited(name="Marta Venn", **over):
    look = make_look(name)
    look.description += " A silver ring gleams on her thumb."
    look.tags["marks"] = [*look.tags["marks"], "silver thumb ring"]
    for key, value in over.items():
        setattr(look, key, value)
    return look


def town(state="provisional"):
    world = World()
    marta = world.add_entity("Marta Venn", "npc", aliases=["Old Marta"])
    look = make_look()
    look.state = state
    world.set_look(marta.id, look)
    return world


class Answering:
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    async def revise_looks(self, request):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


NARRATION = "Marta Venn wipes the bar. A silver ring gleams on her thumb, and her hair is tied back. The rain keeps falling."


# ---- finding the sentences ------------------------------------------------------------------


def test_sentences_split_on_stops_and_lines():
    assert sentences("One. Two!  Three?\nFour") == ["One.", "Two!", "Three?", "Four"]


def test_titles_and_first_words_do_not_identify_a_person():
    assert about("Lord Corvin Vance turned away.", "Lord Steward Hadrian Morlowe") == []
    assert about("Old road, long road.", "Old Tam") == []
    assert about("Reeve walked on.", "Reeve Tamsin Cobb") == []
    assert about("Tamsin walked on.", "Reeve Tamsin Cobb") == ["Tamsin walked on."]
    assert about("Hobb grinned.", "Gaffer Hobb") == ["Hobb grinned."]


def test_about_matches_the_name_or_a_capitalised_part_of_it():
    text = "Marta Venn wipes the bar. Then Venn laughs. The old road is long. Marta grins. Rain falls. It is cold. Dark."
    assert about(text, "Marta Venn") == [
        "Marta Venn wipes the bar.", "Then Venn laughs.", "The old road is long.", "Marta grins.", "Rain falls.",
        "It is cold.",
    ]  # fmt: skip
    assert about("Along the old road he walks.", "Old Tam") == []  # lower-case "old" is not Old Tam
    assert about("They call her Old Marta.", "Marta Venn", ["Old Marta"]) == ["They call her Old Marta."]
    assert about("Marta nods. She has grey eyes. Her hair is white. Far off, thunder. Wren waves.", "Marta Venn") == [
        "Marta nods.", "She has grey eyes.", "Her hair is white.",
    ]  # fmt: skip


@pytest.mark.parametrize(
    "sentence,expected",
    [
        ("Her hair is tied back with a ribbon.", True),
        ("A dark corridor, a white door, a red lamp, a short climb.", False),
        ("Marta Venn has green eyes.", True),
        ("She wore a dark cloak.", True),
        ("Marta Venn laughs and pours the ale.", False),
        ("[[look: adds | a limp]]", True),
    ],
)
def test_describing_is_a_cheap_gate(sentence, expected):
    assert describing(sentence) is expected


def test_only_described_people_with_a_look_are_candidates():
    world = town()
    world.add_entity("Wren", "npc")  # no look
    got = revision_candidates(world, ["Toby Reed"], {"Toby Reed": make_look("Toby Reed")}, NARRATION + " Wren has red hair.")
    assert [(c.name, c.party, c.fixed) for c in got] == [("Marta Venn", False, False)]
    assert "silver ring" in " ".join(got[0].narration)
    assert revision_candidates(world, [], {}, "Marta Venn laughs and pours the ale.") == []


# ---- the rules -----------------------------------------------------------------------------


async def revise(world, answer, party_looks=None, campaign=CAMPAIGN, narration=NARRATION):
    cur = Answering(answer)
    return await run_revisions(world, campaign, party_looks or {}, cur, narration, turn=7), cur


async def test_a_provisional_look_takes_new_detail_and_the_op_applies_once():
    world = town()
    result, cur = await revise(world, {0: LookRevision("adds", edited())})
    (op,) = result.ops
    assert isinstance(op, ReviseLook) and op.look.rev == 2 and op.look.source == "narration"
    assert cur.requests[0].subjects[0].fixed is False
    assert len(apply_ops(world, [op]).ops) == 1 and "silver ring" in world.find("Marta Venn").look.description
    assert apply_ops(world, [op]).ops == []  # stale: the rev moved on


async def test_a_fixed_look_ignores_a_minor_addition_but_takes_a_lasting_change():
    world = town("fixed")
    result, _ = await revise(world, {0: LookRevision("adds", edited())})
    assert result.ops == [] and "ignored" in result.notes[0]
    result, _ = await revise(world, {0: LookRevision("lasting", edited())})
    (op,) = result.ops
    assert op.look.rev == 2 and op.look.state == "fixed"


async def test_a_contradiction_rewrites_a_provisional_look_but_corrects_the_gm_for_a_fixed_one():
    result, _ = await revise(town(), {0: LookRevision("contradicts", edited(), "grey eyes, but the story said green")})
    assert isinstance(result.ops[0], ReviseLook)
    world = town("fixed")
    result, _ = await revise(world, {0: LookRevision("contradicts", edited(), "grey eyes, but the story said green")})
    (op,) = result.ops
    assert "Marta Venn's look is settled: grey eyes, but the story said green" in op.text and op.turn == 7
    apply_ops(world, result.ops)
    assert world.corrections and "settled" in world.corrections[0]["text"]
    assert world.find("Marta Venn").look.rev == 1


async def test_party_members_are_revised_through_the_party_map():
    look = make_look("Toby Reed")
    result, _ = await revise(
        World(), {0: LookRevision("lasting", edited("Toby Reed"))}, {"Toby Reed": look},
        narration="Toby Reed has a new scar across his cheek.",
    )  # fmt: skip
    assert result.ops == [] and result.party["Toby Reed"].rev == 2


@pytest.mark.parametrize(
    "answer,fragment",
    [
        (LookRevision("adds", edited(summary="")), "revision refused"),
        (LookRevision("adds", None), "without a look"),
        (LookRevision("sideways", edited()), "unknown verdict"),
    ],
)
async def test_bad_answers_are_refused_and_noted(answer, fragment):
    result, _ = await revise(town(), {0: answer})
    assert result.ops == [] and fragment in result.notes[0]


async def test_same_and_missing_answers_and_unchanged_looks_do_nothing():
    for answer in ({0: LookRevision("same")}, {}, {0: LookRevision("adds", make_look())}):
        result, _ = await revise(town(), answer)
        assert result.ops == [] and result.party == {}


async def test_failures_never_raise_and_a_curator_without_the_method_does_nothing():
    for error in (CuratorError("boom"), RuntimeError("down")):
        result, _ = await revise(town(), error)
        assert result.ops == [] and "look revisions skipped" in result.notes[0]

    class Bare:
        pass

    assert (await run_revisions(town(), CAMPAIGN, {}, Bare(), NARRATION)).ops == []
    assert (await run_revisions(town(), CAMPAIGN, {}, Answering(), "  ")).ops == []


# ---- the service -----------------------------------------------------------------------------


def played(text, turn=4):
    session = Session("s")
    session.state = GameState(Phase.ADVENTURE, dict(CAMPAIGN))
    session.state.world = town()
    session.state.set_look("Toby Reed", make_look("Toby Reed"))
    session.state.turn = turn
    session.messages = [
        {"role": "user", "content": [{"type": "text", "text": "I look around"}]},
        {"role": "assistant", "content": [{"type": "text", "text": text}]},
    ]
    return session


async def test_the_service_revises_once_per_turn_and_applies_the_result():
    session, svc = played("Marta Venn wipes the bar. [[look: adds | a silver thumb ring]]"), CuratorService(ScriptedCurator())
    assert svc.revisions_due(session)
    assert await svc.run_revisions_if_due(session)
    look = session.state.world.find("Marta Venn").look
    assert look.rev == 2 and "silver thumb ring" in look.description and look.source == "narration"
    assert not svc.revisions_due(session) and not await svc.run_revisions_if_due(session)  # checked this turn
    assert not session.curating


async def test_a_fixed_party_look_gets_a_correction_not_a_rewrite():
    session, svc = played("Toby Reed squints. [[look: contradicts | Toby has green eyes]]"), CuratorService(ScriptedCurator())
    session.state.looks["Toby Reed"].state = "fixed"
    assert await svc.run_revisions_if_due(session)
    assert session.state.looks["Toby Reed"].rev == 1
    assert "Toby has green eyes" in session.state.world.corrections[0]["text"]


async def test_a_party_member_revision_lands_when_the_session_is_idle():
    session, svc = played("Toby Reed shows a new scar. [[look: lasting | a scar across the cheek]]"), CuratorService(ScriptedCurator())
    assert await svc.run_revisions_if_due(session)
    assert session.state.looks["Toby Reed"].rev == 2 and session.pending_revised == []


def test_not_due_without_a_described_person_in_session_zero_or_when_busy():
    svc = CuratorService(ScriptedCurator())
    assert not svc.revisions_due(played("Marta Venn laughs and pours the ale."))
    assert not svc.revisions_due(Session("z"))
    busy = played("Marta Venn has green eyes.")
    busy.busy = True
    assert not svc.revisions_due(busy)

    class NoRevise:
        pass

    assert not CuratorService(NoRevise()).revisions_due(played("Marta Venn has green eyes."))


def test_a_stale_waiting_revision_is_dropped():
    session = played("x")
    stale = make_look("Toby Reed")
    stale.rev = 3  # it was written against rev 2, but the look is at rev 1
    session.pending_revised.append({"Toby Reed": stale})
    session.drain_pending()
    assert session.state.looks["Toby Reed"].rev == 1


# ---- new people described from the story ------------------------------------------------------


async def test_a_new_person_is_described_with_the_story_sentences_that_name_them():
    world = World()
    world.add_entity("Old Tam", "npc")
    seen = []

    class Spy(ScriptedCurator):
        async def look(self, request):
            seen.append(request)
            return await super().look(request)

    result = await run_looks(world, CAMPAIGN, "r", {}, Spy(), recent_text="Old Tam limps in. He has a braided silver beard.")
    assert next(x for x in seen[0].subjects if x.name == "Old Tam").narration == ["Old Tam limps in.", "He has a braided silver beard."]
    assert result.ops[0].look.source == "narration"
    text = render_looks(seen[0])
    assert "The story has already said this about them" in text and "- He has a braided silver beard." in text


# ---- the model-backed curator ------------------------------------------------------------------


def test_the_revise_schema_is_closed():
    walk(REVISE_SCHEMA)


async def test_the_anthropic_curator_parses_revisions():
    new = edited()
    reply = {
        "revisions": [
            {"index": 0, "verdict": "adds", "note": "", "look": {"summary": new.summary, "description": new.description, "tags": new.tags}},
            {"index": 1, "verdict": "same", "note": "", "look": None},
            {"index": 2, "verdict": "bogus", "note": "", "look": None},
            {"index": 9, "verdict": "same", "note": "", "look": None},
        ]
    }
    cur, messages = model_curator(reply)
    request = ReviseRequest(
        [ReviseSubject("A", False, make_look("A"), ["x"], False), ReviseSubject("B", False, make_look("B"), ["y"], True),
         ReviseSubject("C", False, make_look("C"), ["z"], False)],
        "A town.",
    )  # fmt: skip
    got = await cur.revise_looks(request)
    assert messages.calls[0]["output_config"]["format"]["schema"] is REVISE_SCHEMA
    assert "continuity editor" in messages.calls[0]["system"][0]["text"]
    assert set(got) == {0, 1} and got[0].verdict == "adds" and "silver" in got[0].look.description and got[1].look is None
    text = render_revise(request)
    assert "### 1: B (person; look is fixed)" in text and "The story said:\n- y" in text
