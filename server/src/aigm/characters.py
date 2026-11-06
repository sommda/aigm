"""The party's character pages (docs/STATUS.md 3, 7): each player character's sheet, ready to draw.

A character with a structured sheet shows its sections; one without (the sheet step failed, or the game began before
sheets existed) shows the free text the GM wrote, so there is always something to read."""

import re
from typing import Any

from aigm.session.state import GameState
from aigm.world import WorldTime
from aigm.world.model import duration_text


def hp_text(hp: int | None, max_hp: int | None) -> str:
    return f"{hp}/{max_hp}" if hp is not None and max_hp is not None else ""


def progress_text(state: GameState, name: str) -> str:
    hero = state.hero(name)
    classes = ", ".join(f"{c} {n}" for c, n in hero.classes.items())
    return f"Level {hero.level}" + (f" ({classes})" if classes else "") + f", {hero.xp} XP"


def headline_of(state: GameState, name: str) -> str:
    """The sheet's headline ("Human Fighter 1", or "Human Fighter, level 1") with each class's level made current. The GM writes the headline once,
    and a level gained later (`award` with `level_up`) changes `Hero.classes`, not the text, so the number in it is
    read from `classes` every time it is shown. A class the headline does not name is left alone."""
    sheet = state.sheets.get(name)
    if sheet is None:
        return ""
    text = sheet.headline
    for cls, level in state.hero(name).classes.items():
        # "Fighter 1", "Fighter, level 1" and "Fighter level 1" all become "Fighter 2"
        pattern = rf"(?<!\w)({re.escape(cls)})(?:\s*,)?\s+(?:(?:level|lvl\.?)\s*)?\d+(?!\w)"
        text = re.sub(pattern, rf"\g<1> {level}", text, flags=re.I)
    return text


def _sheet_text(state: GameState, name: str) -> str:
    for member in (state.campaign or {}).get("party", []):
        if isinstance(member, dict) and member.get("name") == name:
            return str(member.get("sheet", ""))
    return ""


def is_dead(state: GameState, name: str) -> bool:
    sheet = state.sheets.get(name)
    return sheet is not None and sheet.fate == "dead"


def living(state: GameState) -> list[str]:
    """The party members who are not dead (docs/STAKES.md 7.2)."""
    return [n for n in state.party_names if not is_dead(state, n)]


def roster(state: GameState) -> list[dict[str, Any]]:
    """One row per party member, for the tabs. The dead come last, marked."""
    out = []
    for name in state.party_names:
        sheet = state.sheets.get(name)
        row = {
            "name": name,
            "headline": headline_of(state, name),
            "level": state.hero(name).level,
            "hp": hp_text(sheet.hp, sheet.max_hp) if sheet else "",
            "conditions": list(sheet.conditions) if sheet else [],
        }
        if sheet is not None and sheet.fate:
            row.update(fate=sheet.fate, remains=sheet.remains)
            row["conditions"] = ["dead", *row["conditions"]]
        out.append(row)
    return sorted(out, key=lambda r: "fate" in r)  # a stable sort: the living keep their order


LEAVE_TURNS = 20  # player turns after which an unresolved death is taken as the body being left (docs/STAKES.md 7.3)
REMAINS_WORDS = {
    "carried": "the party carries the body",
    "left": "the body was left where it fell",
    "buried": "the body was laid to rest",
    "lost": "nothing is left to recover",
}


def settle_remains(state: GameState, leave_turns: int = LEAVE_TURNS) -> list[str]:
    """A death the player never settled becomes `left` once the party has gone on for `leave_turns` player turns and at
    least one member is alive to go on. Returns the names changed."""
    changed = []
    if not living(state):
        return changed
    for name in state.party_names:
        sheet = state.sheets.get(name)
        if sheet and sheet.fate == "dead" and sheet.remains is None and sheet.died_turn is not None:
            if state.turn - sheet.died_turn >= leave_turns:
                sheet.remains = "left"
                changed.append(name)
    return changed


def fallen_notes(state: GameState) -> str:
    """The briefing's block on the dead: who, when, where the body is, and what the player must be asked (7.2, 7.3)."""
    lines, open_ = [], []
    for name in state.party_names:
        sheet = state.sheets.get(name)
        if sheet is None or sheet.fate != "dead":
            continue
        ago = ""
        if sheet.died_at:
            ago = ", died " + duration_text(max(0, state.world.time.total_minutes - WorldTime.from_dict(sheet.died_at).total_minutes)) + " ago"
        lines.append(f"- {name}{ago}: " + (REMAINS_WORDS[sheet.remains] if sheet.remains else "the body's fate is not decided"))
        if sheet.remains is None:
            open_.append(name)
    if not lines:
        return ""
    out = ["Fallen (they are out of the party's actions: do not have them speak or act):", *lines]
    if open_:
        out.append(
            f"The player has not yet decided what to do with the body of {', '.join(open_)}. Put the choice to them in "
            "the fiction within the next scene or two, not in the middle of a fight: leave it, carry it (slows the "
            "party, draws trouble), bury it, or try to bring the character back (revival costs something, and many "
            "rulesets limit how long a body can be raised). The choice is theirs, not yours; record it with "
            "update_character `remains`. If they ignore it, raise it again at the next natural pause."
        )
    return "\n".join(out)


def _look_page(look: Any) -> dict[str, str] | None:
    """The player's own character's Look, which they wrote (docs/LOOKS.md 9)."""
    return {"summary": look.summary, "description": look.description} if look is not None else None


def detail(state: GameState, name: str) -> dict[str, Any] | None:
    """One character's whole page, or None if there is no such party member."""
    found = state.find_hero(name)
    if found is None:
        return None
    sheet = state.sheets.get(found)
    hero = state.hero(found)
    page: dict[str, Any] = {
        "name": found,
        "level": hero.level,
        "xp": hero.xp,
        "progress": progress_text(state, found),
        "headline": headline_of(state, found),
        "hp": hp_text(sheet.hp, sheet.max_hp) if sheet else "",
        "conditions": list(sheet.conditions) if sheet else [],
        "fate": sheet.fate if sheet else None,
        "remains": sheet.remains if sheet else None,
        "sections": [{"title": s.title, "lines": list(s.lines)} for s in sheet.sections] if sheet else [],
        "text": None if sheet else _sheet_text(state, found),
        "look": _look_page(state.looks.get(found)),
    }
    return page


SHEET_CHARS = 1500  # per character; the sheets travel with every request, so they are kept short


def sheet_notes(state: GameState) -> str:
    """The party's sheets as the GM should see them each turn, so `update_character` can rewrite a section from them."""
    out = []
    for name in state.party_names:
        sheet = state.sheets.get(name)
        if sheet is None:
            continue
        head = [f"{name}: {headline_of(state, name)}".rstrip(": ")]
        hp = hp_text(sheet.hp, sheet.max_hp)
        head.append(f"HP {hp}" if hp else "")
        head.append(f"conditions: {', '.join(sheet.conditions)}" if sheet.conditions else "")
        lines = ["; ".join(h for h in head if h)]
        for section in sheet.sections:
            lines.append(f"  {section.title}: " + " | ".join(section.lines))
        text = "\n".join(lines)
        out.append(text if len(text) <= SHEET_CHARS else text[: SHEET_CHARS - 1] + "…")
    return "\n".join(out)


def look_notes(state: GameState) -> str:
    """How the party's members look, one line each, for the GM's notes (docs/LOOKS.md 9)."""
    return "\n".join(
        f"- {name}: {look.summary}" for name in state.party_names if (look := state.looks.get(name)) is not None
    )
