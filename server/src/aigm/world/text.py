"""Text helpers for matching names and facts."""

import re

STOPWORDS = frozenset(
    "a an and are as at be but by for from had has have in into is it its of on or that the their "
    "there these this those to was were which while who with not no".split()
)
_PUNCT = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Casefold, drop punctuation and a leading article: "The Old Mine!" -> "old mine"."""
    text = _SPACE.sub(" ", _PUNCT.sub(" ", name.casefold())).strip()
    for article in ("the ", "a ", "an "):
        if text.startswith(article):
            return text[len(article) :]
    return text


def normalize_text(text: str) -> str:
    """Casefold and drop punctuation, keeping every word: the key for spotting repeated text."""
    return _SPACE.sub(" ", _PUNCT.sub(" ", text.casefold())).strip()


def tokens(text: str) -> set[str]:
    """Searchable words of a text: lowercase, no stopwords, at least three characters."""
    words = _SPACE.split(_PUNCT.sub(" ", text.casefold()).strip())
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}


def word_count(text: str) -> int:
    return len(text.split())
