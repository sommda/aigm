"""The party's character pages (docs/STATUS.md 3, 7): each player character's sheet, ready to draw.

A character with a structured sheet shows its sections; one without (the sheet step failed, or the game began before
sheets existed) shows the free text the GM wrote, so there is always something to read."""

from typing import Any

from aigm.session.state import GameState


def hp_text(hp: int | None, max_hp: int | None) -> str:
    return f"{hp}/{max_hp}" if hp is not None and max_hp is not None else ""


def progress_text(state: GameState, name: str) -> str:
    hero = state.hero(name)
    classes = ", ".join(f"{c} {n}" for c, n in hero.classes.items())
    return f"Level {hero.level}" + (f" ({classes})" if classes else "") + f", {hero.xp} XP"


def _sheet_text(state: GameState, name: str) -> str:
    for member in (state.campaign or {}).get("party", []):
        if isinstance(member, dict) and member.get("name") == name:
            return str(member.get("sheet", ""))
    return ""


def roster(state: GameState) -> list[dict[str, Any]]:
    """One row per party member, for the tabs."""
    out = []
    for name in state.party_names:
        sheet = state.sheets.get(name)
        out.append(
            {
                "name": name,
                "headline": sheet.headline if sheet else "",
                "level": state.hero(name).level,
                "hp": hp_text(sheet.hp, sheet.max_hp) if sheet else "",
                "conditions": list(sheet.conditions) if sheet else [],
            }
        )
    return out


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
        "headline": sheet.headline if sheet else "",
        "hp": hp_text(sheet.hp, sheet.max_hp) if sheet else "",
        "conditions": list(sheet.conditions) if sheet else [],
        "sections": [{"title": s.title, "lines": list(s.lines)} for s in sheet.sections] if sheet else [],
        "text": None if sheet else _sheet_text(state, found),
    }
    return page
