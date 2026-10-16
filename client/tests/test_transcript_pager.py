from aigm_client import events as ev
from aigm_client.blocks import SystemBlock, plain
from aigm_client.session import ChatSession
from aigm_client.transcript import Transcript


def make(height=5, width=40):
    t = Transcript(width=width, height=height)
    return t, ChatSession(t)


def fill(t, n):
    for i in range(n):
        t.add(SystemBlock(f"line {i}"))


def visible(t):
    return [s.strip() for s in plain(t.visible_lines())]


def test_page_fills_then_holds():
    t, _ = make(height=5)
    fill(t, 12)
    assert visible(t) == [f"line {i}" for i in range(5)]
    assert t.held == 7


def test_advance_keeps_three_lines_of_overlap_until_exhausted():
    t, _ = make(height=5)
    fill(t, 12)
    seen = set(range(5))
    prev = visible(t)
    guard = 0
    while t.held > 0 and guard < 20:
        assert t.advance() == "advanced"
        cur = visible(t)
        assert cur[:3] == prev[-3:]  # continuity: last three lines of the old page lead the new one
        seen |= {int(x.split()[1]) for x in cur}
        prev = cur
        guard += 1
    assert t.held == 0 and seen == set(range(12))
    assert visible(t)[-1] == "line 11"
    assert t.advance() == "none"


def test_overlap_shrinks_for_tiny_pages_and_always_progresses():
    t, _ = make(height=2)
    fill(t, 6)
    starts = [t.page_start]
    while t.held > 0:
        t.advance()
        starts.append(t.page_start)
    assert starts == sorted(set(starts)) and len(starts) > 1  # strictly increasing


def test_page_turn_animation_window_never_reveals_held_lines():
    t, _ = make(height=5)
    fill(t, 20)
    old = t.page_start
    t.advance()
    for top in range(old, t.page_start + 1):  # every frame of the slide
        t.view_top_override = top
        lo, hi = t.visible_range()
        assert hi <= t.revealed_end and hi - lo <= t.page_height
    t.view_top_override = None
    assert t.visible_range()[0] == t.page_start


def test_growth_while_held_never_blocks():
    t, s = make(height=4)
    s.begin_turn("hi")  # blank, "You: hi", blank = 3 lines
    s.apply(ev.Text("one\n\ntwo\n\nthree\n\nfour"))
    assert t.held > 0
    held_before = t.held
    s.apply(ev.Text("\n\nfive\n\nsix"))
    assert t.held > held_before  # buffering continued while the page was full
    assert len(visible(t)) == 4


def test_scrollback_cannot_enter_held_region():
    t, _ = make(height=5)
    fill(t, 20)
    t.advance()
    live = t.visible_range()
    t.scroll_by(-1)
    assert t.scrolled_back
    assert t.visible_range()[0] == live[0] - 1
    assert t.visible_range()[1] <= t.revealed_end  # cannot see held lines
    t.scroll_by(-100)
    assert t.visible_range()[0] == 0
    t.scroll_by(100)
    assert not t.scrolled_back  # scrolling down far enough returns to the live page
    assert t.visible_range() == live


def test_advance_while_scrolled_back_returns_first():
    t, _ = make(height=5)
    fill(t, 20)
    t.scroll_by(-1)  # nothing above page_start=0; still marks scrolled back
    t.advance()
    assert t.following
    assert t.page_start == 0
    assert t.advance() == "advanced"  # a second press advances


def test_send_on_full_page_starts_new_page():
    t, s = make(height=4)
    fill(t, 4)
    assert t.held == 0 and len(t.lines) == 4
    s.begin_turn("go")
    assert t.page_start == 4


def test_send_with_room_flows_on_same_page():
    t, s = make(height=10)
    fill(t, 3)
    s.begin_turn("go")
    assert t.page_start == 0
    assert any("You: go" in line for line in visible(t))


def test_new_user_message_appears_between_replies():
    t, s = make(height=50)
    s.begin_turn("first")
    s.apply(ev.Text("reply one"))
    s.apply(ev.MessageEnd())
    s.begin_turn("second")
    s.apply(ev.Text("reply two"))
    s.apply(ev.MessageEnd())
    text = [l.strip() for l in plain(t.lines) if l.strip()]
    assert text == ["You: first", "reply one", "You: second", "reply two"]


def test_resize_keeps_place():
    t, _ = make(height=5, width=40)
    for i in range(10):
        t.add(SystemBlock(f"block {i} " + "word " * 30))  # wraps to several lines
    t.advance()
    anchor_block = t._anchor()[0]
    t.set_size(80, 5)
    assert t._anchor()[0] == anchor_block


def test_show_last_page_after_load():
    t, _ = make(height=5)
    fill(t, 12)
    t.show_last_page()
    assert visible(t) == [f"line {i}" for i in range(7, 12)]
    assert t.held == 0


def test_partial_last_line_grows_in_place():
    t, s = make(height=10)
    s.begin_turn("hi")
    s.apply(ev.Text("The door **spl"))
    assert "The door spl" in " ".join(visible(t))
    s.apply(ev.Text("inters**"))
    assert "The door splinters" in " ".join(visible(t))
    assert "*" not in " ".join(visible(t))


def test_cleared_blocks_never_leak_into_new_ones():
    # Regression: the line cache was keyed by id(block); a new block reusing a freed id showed old text.
    t, _ = make(height=10)
    for round_ in range(200):
        t.clear()
        t.add(SystemBlock(f"message {round_}"))
        assert [s.strip() for s in plain(t.lines)] == [f"message {round_}"]
