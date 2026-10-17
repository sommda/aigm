"""Cheap server-side checks on fact text (docs/WORLD.md 5.4).

Generated facts must describe a world that exists without the party; extracted facts must stand
on their own. These regexes catch the obvious violations; a model-based check (the curator's
`judge_independence`) catches the subtle ones."""

import re

_SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself|yourselves)\b", re.I)
_PARTY = re.compile(
    r"\b(the party|the adventurers?|our heroes|the heroes|the player characters?|the players?|player characters?)\b", re.I
)
_RECENT = re.compile(r"\b(recently|just now|a moment ago|earlier today|this morning|last night|moments ago)\b", re.I)


def standalone_problem(text: str) -> str | None:
    """Why a fact is not self-contained (it speaks to the player or the party), or None."""
    if _SECOND_PERSON.search(text):
        return "addresses the player ('you')"
    if _PARTY.search(text):
        return "mentions the party"
    return None


def independence_problem(text: str, party_names: list[str]) -> str | None:
    """Why a generated fact breaks the independence rules, or None if it passes."""
    problem = standalone_problem(text)
    if problem:
        return problem
    for name in party_names:
        if name.strip() and re.search(rf"\b{re.escape(name.strip())}\b", text, re.I):
            return f"mentions the player character {name.strip()}"
    if _RECENT.search(text):
        return "places its cause recently instead of before the game"
    return None
