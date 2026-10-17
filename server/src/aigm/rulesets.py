"""The rulesets a game can be played under, chosen in Session 0 (docs/RULESETS.md).

The prompts for each live in prompts/rulesets/<id>/ (01_rules.md and 02_era.md); this is the catalog
that names them. D&D 2024 ("5.5e") is the default."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Ruleset:
    id: str  # also the folder name under prompts/rulesets/
    name: str
    short: str  # for status lines
    family: str  # "D&D" or "Pathfinder"
    year: int  # when this edition first appeared
    era: str  # a few words on the period it comes from


RULESETS: tuple[Ruleset, ...] = (
    Ruleset("odnd", "Original D&D (the 1974 \"white box\")", "OD&D", "D&D", 1974, "mid-1970s wargame roots"),
    Ruleset("basic", "D&D Basic (Moldvay/Cook, \"B/X\")", "B/X", "D&D", 1981, "early 1980s"),
    Ruleset("becmi", "D&D BECMI (the Mentzer \"red box\" line and Rules Cyclopedia)", "BECMI", "D&D", 1983, "mid-1980s"),
    Ruleset("adnd1e", "Advanced D&D, 1st Edition", "AD&D 1e", "D&D", 1977, "late 1970s to early 1980s"),
    Ruleset("adnd2e", "Advanced D&D, 2nd Edition", "AD&D 2e", "D&D", 1989, "late 1980s and the 1990s"),
    Ruleset("dnd3e", "D&D 3rd Edition", "D&D 3e", "D&D", 2000, "around the year 2000"),
    Ruleset("dnd35e", "D&D 3.5 Edition", "D&D 3.5e", "D&D", 2003, "the early-to-mid 2000s"),
    Ruleset("dnd4e", "D&D 4th Edition", "D&D 4e", "D&D", 2008, "the late 2000s"),
    Ruleset("dnd5e", "D&D 5th Edition (2014)", "D&D 5e", "D&D", 2014, "the mid-2010s"),
    Ruleset("dnd55e", "D&D 5.5 Edition (the 2024 revision)", "D&D 5.5e", "D&D", 2024, "the mid-2020s"),
    Ruleset("pf1e", "Pathfinder, 1st Edition", "Pathfinder 1e", "Pathfinder", 2009, "the late 2000s and 2010s"),
    Ruleset("pf2e", "Pathfinder, 2nd Edition (Remaster)", "Pathfinder 2e", "Pathfinder", 2019, "the late 2010s and 2020s"),
)
DEFAULT_RULESET = "dnd55e"
BY_ID = {r.id: r for r in RULESETS}


def get(ruleset_id: str) -> Ruleset:
    try:
        return BY_ID[ruleset_id]
    except KeyError:
        raise ValueError(f"unknown ruleset {ruleset_id!r}") from None
