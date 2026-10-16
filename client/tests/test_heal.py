import pytest

from aigm_client.blocks import plain, render_markdown
from aigm_client.heal import heal

# Complete, well-formed documents (no literal marker characters in the output).
CORPUS = [
    "The door **splinters** inward and the goblin *snarls* at you.",
    "A ***very*** loud noise, then ~~silence~~ and `code` appear.",
    "You find:\n\n- a **rusty** key\n- a *glowing* gem\n- 3 gold coins\n\nWhat do you do?",
    "# The Tavern\n\nSmoke hangs in the air.\n\n## Patrons\n\n1. A **dwarf** drinking\n2. An elf, *bored*",
    "> The innkeeper whispers: *beware the cellar*.\n\nYou nod.",
    "Read the [old map](https://example.com/map) carefully, or ![sigil](https://example.com/s.png) look.",
    "Run:\n\n```python\nx = 1 * 2\nprint('**not bold**')\n```\n\nThen rest.",
    "**Bold with `code` inside** and _underscored_ words, snake_case_name stays.",
    "Roll 2 * 3 = 6, and 5*3*2 is odd.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
    "Nested **bold and *italic* together** done. Émoji 🐉 and ünïcode **fine**.",
]


@pytest.mark.parametrize("doc", CORPUS)
def test_complete_documents_unchanged(doc):
    assert heal(doc) == doc


@pytest.mark.parametrize("doc", CORPUS)
def test_every_prefix_renders_without_error(doc):
    for i in range(len(doc) + 1):
        render_markdown(heal(doc[:i]), 40)


@pytest.mark.parametrize("doc", CORPUS)
def test_final_render_matches_one_shot(doc):
    assert plain(render_markdown(heal(doc), 60)) == plain(render_markdown(doc, 60))


@pytest.mark.parametrize(
    "partial, healed",
    [
        ("**bol", "**bol**"),
        ("**bold*", "**bold**"),
        ("some *ital", "some *ital*"),
        ("~~gone", "~~gone~~"),
        ("***both", "***both***"),
        ("**bold and *it", "**bold and *it***"),
        ("`cod", "`cod`"),
        ("a **b `c", "a **b `c`**"),
        ("```py\nx = 1", "```py\nx = 1\n```"),
        ("```py\nx = **1\n", "```py\nx = **1\n\n```".replace("\n\n```", "\n```")),
        ("see [the ma", "see the ma"),
        ("see [the map](http://exa", "see the map"),
        ("see ![img](http://x", "see img"),
        ("see [the map](http://x.com) and **bo", "see [the map](http://x.com) and **bo**"),
        ("word **", "word "),
        ("word *", "word "),
        ("word `", "word "),
        ("Hello\n\n#", "Hello\n\n"),
        ("Hello\n\n- ", "Hello\n\n"),
        ("Hello\n\n1.", "Hello\n\n"),
        ("Hello\n=", "Hello\n"),
        ("para one **x**\n\npara two **y", "para one **x**\n\npara two **y**"),
        ("- item **bol", "- item **bol**"),
        ("- item one **a\n- item two", "- item one **a\n- item two"),  # a stray ** in an earlier item
    ],
)
def test_heal_cases(partial, healed):
    assert heal(partial) == healed


@pytest.mark.parametrize(
    "text",
    ["2 * 3 = 6", "snake_case_name", "5 * 4 * 3", "* bullet item", "a_b_c and d", "```\n**x**\n```", "price is $5 * 2"],
)
def test_not_emphasis_left_alone(text):
    assert heal(text) == text


def test_markers_not_visible_while_streaming():
    doc = "The door **splinters** inward, *and* the ~~goblin~~ `snarls` at **you and *me* both**."
    for i in range(1, len(doc) + 1):
        shown = "\n".join(plain(render_markdown(heal(doc[:i]), 80)))
        for marker in ("**", "~~", "`"):
            assert marker not in shown, (i, doc[:i], shown)
        assert "*" not in shown, (i, doc[:i], shown)
