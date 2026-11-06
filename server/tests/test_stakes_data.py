"""Stakes, step 1 (docs/STAKES.md 2, 3, 9, 10): the failure fields, the chapter table, due failures, saves."""

import pytest

from aigm import sheets
from aigm import story as st
from aigm.errors import CorruptSave
from aigm.story import Deadline, Doom, Story
from aigm.world import World, WorldTime
from tests.test_story import short_story


def at(day, hour=0):
    return WorldTime(day, hour)


def staged(chapter=1):
    s = short_story()
    s.chapter = chapter
    st.settle_ready(s)
    return s


def test_failure_response_by_chapter():
    s = staged()
    one, two, three = (st.failure_response(s, c) for c in (1, 2, 3))
    assert (one.quest, one.deadline, one.doom) == ("repair", "move", "none")
    assert one.cost_kinds == ("time", "resource") and one.cost_required and not one.backup_quest
    assert (two.quest, two.deadline, two.doom) == ("repair", "repair", "end")
    assert two.backup_quest and "ally" in two.cost_kinds
    assert (three.quest, three.deadline, three.doom) == ("end", "end", "end")
    assert not three.cost_required


def test_failure_response_defaults_to_the_current_chapter():
    assert st.failure_response(staged(2)).quest == "repair" and st.failure_response(staged(3)).quest == "end"


def test_endless_and_concluded_stories_have_no_stakes():
    endless = Story(st.ENDLESS)
    assert st.failure_response(endless).quest == "none"
    done = staged()
    st.conclude(done, "e1", "It is over.")
    assert st.failure_response(done) == st.failure_response(endless)


def test_due_failures_finds_a_passed_quest_deadline():
    s = staged(2)
    m = s.milestone("m3")
    m.deadline = Deadline(at(6, 18), "the second sun", fixed=True)
    w = World()
    w.time = at(6, 17)
    assert st.due_failures(s, w) == []
    w.time = at(6, 18)
    [due] = st.due_failures(s, w)
    assert (due.kind, due.id, due.action, due.fixed) == ("quest", "m3", "repair", True)


def test_a_settled_quest_is_not_due():
    s = staged(2)
    s.milestone("m3").deadline = Deadline(at(2))
    s.milestone("m3").status = "done"
    w = World()
    w.time = at(9)
    assert st.due_failures(s, w) == []


def test_chapter_one_deadlines_move_and_dooms_are_not_used():
    s = staged(1)
    s.milestone("m1").deadline = Deadline(at(2))
    s.dooms = [Doom("d1", "The ritual completes", [2, 3], Deadline(at(2)), "e2")]
    w = World()
    w.time = at(5)
    [due] = st.due_failures(s, w)
    assert (due.kind, due.action) == ("quest", "move")


def test_a_doom_deadline_ends_the_game_in_its_chapters_only():
    s = staged(2)
    s.dooms = [Doom("d1", "Vane's ritual completes", [2, 3], Deadline(at(20)), "e2"), Doom("d2", "Late", [3], Deadline(at(1)))]
    w = World()
    w.time = at(21)
    [due] = st.due_failures(s, w)
    assert (due.kind, due.id, due.action, due.ending) == ("doom", "d1", "end", "e2")


def test_chapter_three_passed_deadline_ends_the_game():
    s = staged(3)
    s.milestone("m3").chapter = 3
    s.milestone("m3").status = "active"
    s.milestone("m3").deadline = Deadline(at(3))
    w = World()
    w.time = at(4)
    assert [d.action for d in st.due_failures(s, w)] == ["end"]


def test_the_stakes_fields_survive_a_round_trip():
    s = staged(2)
    m = s.milestone("m3")
    m.fails_if, m.ending = ["Vane burns the ledger"], "e2"
    m.deadline = Deadline(at(6, 18), "the sun", True)
    s.dooms = [Doom("d1", "The party abandons the vale", [2, 3], None, "e2")]
    s.costs = [{"turn": 5, "chapter": 2, "milestone": "m3", "kind": "resource", "text": "80 gold"}]
    s.wipes = 2
    back = Story.from_dict(s.to_dict())
    assert back.to_dict() == s.to_dict()
    assert back.milestone("m3").deadline == Deadline(at(6, 18), "the sun", True)
    assert back.dooms[0].chapters == [2, 3] and back.wipes == 2 and back.costs[0]["kind"] == "resource"
    assert back.copy().to_dict() == s.to_dict()


def test_an_old_save_loads_with_no_stakes():
    raw = staged().to_dict()
    for key in ("dooms", "costs", "wipes"):
        del raw[key]
    for m in raw["milestones"]:
        for key in ("fails_if", "deadline", "ending"):
            del m[key]
    s = Story.from_dict(raw)
    assert s.dooms == [] and s.costs == [] and s.wipes == 0
    assert all(not m.fails_if and m.deadline is None and m.ending is None for m in s.milestones)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["dooms"].append({"id": "d", "when": "x", "chapters": [1]}),
        lambda raw: raw["dooms"].extend([{"id": "d", "when": "x"}, {"id": "d", "when": "y"}]),
        lambda raw: raw["costs"].append({"turn": 1, "chapter": 1, "kind": "gold", "text": "x"}),
        lambda raw: raw["milestones"][0].update(deadline={"at": {"day": 0, "hour": 1}}),
        lambda raw: raw["milestones"][0].update(fails_if="burns"),
        lambda raw: raw.update(wipes=-1),
    ],
)
def test_bad_stakes_data_is_a_corrupt_save(mutate):
    raw = staged().to_dict()
    mutate(raw)
    with pytest.raises(CorruptSave):
        Story.from_dict(raw)


def test_a_sheet_keeps_its_fate_and_old_sheets_have_none():
    sec = {"title": "Stats", "lines": ["STR 10"]}
    sheet = sheets.clean(
        {"headline": "Rogue 3", "conditions": [], "sections": [sec], "fate": "dead", "remains": "left", "died_turn": 12,
         "died_at": {"day": 2, "hour": 9, "minute": 0}}
    )  # fmt: skip
    assert (sheet.fate, sheet.remains, sheet.died_turn, sheet.died_at["day"]) == ("dead", "left", 12, 2)
    back = sheets.clean(sheet.copy().to_dict())
    assert back.to_dict() == sheet.to_dict()
    plain = sheets.clean({"headline": "Rogue 3", "conditions": [], "sections": [sec]})
    assert plain.fate is None and plain.remains is None and plain.died_at is None
    assert sheets.clean({"conditions": [], "sections": [sec], "remains": "left"}).remains is None  # remains need a death
