from aigm_client.context_model import ContextModel
from tests.fake_server import sample_context


def model(**kw):
    return ContextModel(sample_context(), **kw)


def shown(m, width=80):
    lines, where = m.lines(width)
    return [t.plain for t in lines], where


def test_defaults_top_level_open_everything_else_collapsed():
    m = model()
    # the top-level groups, plus the text blocks of messages (shown as soon as their message is opened)
    assert m.expanded == {"system", "tools", "history", "next", "history/0/0", "history/1/0"}
    text, where = shown(m)
    joined = "\n".join(text)
    assert "System prompt" in joined and "system/common/01_role.md" in joined
    assert "You are the game master." not in joined  # prompt files start collapsed
    assert "Turn 1 · GM: You stand before the mine." in joined
    assert "It is cold." not in joined  # history messages start collapsed
    assert "«your next message goes here»" in joined  # the placeholder is always visible
    assert "Time: day 1" not in joined  # the briefing starts collapsed


def test_opening_a_message_shows_text_but_not_thinking_or_tool_calls():
    m = model()
    m.toggle("history/0")
    m.toggle("history/2")
    joined = "\n".join(shown(m)[0])
    assert "It is cold." in joined
    assert "Thinking" in joined and "Needs a check." not in joined  # collapsed inside an open message
    assert "Tool call: roll_dice" in joined and '"expression"' not in joined
    m.toggle("history/2/1")
    assert '"expression"' in "\n".join(shown(m)[0])


def test_toggle_twice_restores_and_input_cannot_collapse():
    m = model()
    before = shown(m)[0]
    m.toggle("history/0")
    assert shown(m)[0] != before
    m.toggle("history/0")
    assert shown(m)[0] == before
    m.toggle("input")
    assert "«your next message goes here»" in "\n".join(shown(m)[0])
    assert "input" not in m.expanded


def test_expand_all_and_reset():
    m = model()
    m.expand_all()
    joined = "\n".join(shown(m)[0])
    for expected in ("You are the game master.", "Roll dice.", "Needs a check.", "Time: day 1", "It is cold."):
        assert expected in joined
    m.toggle("system")
    m.collapse_all()
    assert m.expanded == {"system", "tools", "history", "next", "history/0/0", "history/1/0"}


def test_every_row_carries_its_kind_as_text_and_the_cache_breakpoint_shows():
    text, _ = shown(model())
    joined = "\n".join(text)
    assert "assistant · ~" in joined and "user · ~" in joined and "prompt · ~" in joined and "input · ~" in joined
    assert "prompt-cache breakpoint" in joined
    m = model(ascii_only=True)
    ascii_text = "\n".join(shown(m)[0])
    assert "▌" not in ascii_text and "▸" not in ascii_text and "|" in ascii_text and "-- prompt-cache" in ascii_text
    assert all(ord(c) < 128 or c in "·«»" for c in ascii_text)


def test_kinds_have_colors():
    lines, where = model().lines(80)
    styles = {}
    for node_id, at in where.items():
        styles[node_id] = {str(s.style) for s in lines[at].spans}
    assert "bright_blue" in str(styles["system"]) and "magenta" in str(styles["history/0"])
    assert "green" in str(styles["history/1"]) and "yellow" in str(styles["briefing"])
    assert "cyan" in str(styles["tools"]) and "bright_white" in str(styles["input"])


def test_expanded_text_has_a_bar_in_the_nodes_color():
    m = model()
    m.toggle("history/0")
    lines, where = m.lines(80)
    body = lines[where["history/0/0"] + 1]
    assert body.plain.strip().startswith("▌ You stand before the mine.")
    assert any("magenta" in str(s.style) for s in body.spans)


def test_long_text_is_wrapped_to_the_width():
    data = sample_context()
    data["sections"][0]["children"][0]["text"] = "word " * 60
    m = ContextModel(data)
    m.toggle("prompt/system/common/01_role.md")
    text, _ = shown(m, 40)
    assert max(len(t) for t in text) <= 40 and sum("word" in t for t in text) > 4


def test_refresh_keeps_collapse_state_by_id_and_defaults_new_nodes():
    m = model()
    m.toggle("history/0")
    m.toggle("tools")  # the user closed a default-open group
    new = sample_context()
    new["sections"][2]["children"].append(
        {"id": "history/3", "kind": "assistant", "title": "new", "tokens": 1, "children": [
            {"id": "history/3/0", "kind": "assistant", "title": "t", "tokens": 1, "text": "t"}]}
    )
    del new["sections"][2]["children"][1]  # history/1 disappears
    m.apply(new)
    assert "history/0" in m.expanded and "tools" not in m.expanded
    assert "history/1/0" not in m.expanded  # gone from the tree, so gone from the state
    assert "history/3/0" in m.expanded  # new nodes get their defaults (a message's text opens with it)
    assert "history/3" not in m.expanded


def test_cursor_moves_over_visible_rows_only():
    m = model()
    assert m.cursor == "system"
    m.move(1)
    assert m.cursor == "prompt/system/common/01_role.md"
    m.move(1)
    assert m.cursor == "tools"
    m.move(-99)
    assert m.cursor == "system"
    m.move_to(True)
    assert m.cursor == "briefing"
    m.toggle("briefing")
    m.move(1)
    assert m.cursor == "briefing/0"
    m.toggle("system")  # closing a group hides its rows from the cursor's path
    assert "prompt/system/common/01_role.md" not in m.visible_headers()


def test_header_text_and_unknown_kinds():
    m = model()
    assert "adventure" in m.header_text and "turn 2" in m.header_text and "~321" in m.header_text
    data = sample_context()
    data["sections"].append({"id": "x", "kind": "mystery", "title": "Something new", "tokens": 1, "text": "hi"})
    other = ContextModel(data)
    other.toggle("x")
    assert "Something new" in "\n".join(shown(other)[0]) and "hi" in "\n".join(shown(other)[0])
