"""The rules of spoken role play (docs/ROLEPLAY.md 3 to 7): did the player actually say something, how good was it,
how do the motives of the listener bear on it, and what does that make of the dice in the chosen ruleset?

Pure functions, no I/O. The GM judges (quality, which motives the words touch); everything that can be checked or
computed is done here, so the GM cannot pick its own dice. `aigm.tools.social` is the tool that uses this."""

import re
from dataclasses import dataclass

from aigm.world.model import Motive
from aigm.world.text import normalize_text

QUALITIES = ("weak", "ordinary", "strong", "brilliant")
QUALITY_BOON = {"weak": -1, "ordinary": 0, "strong": 1, "brilliant": 2}
EFFECTS = ("aligned", "against")
STRENGTH_RANK = {"leaning": 1, "driven": 2, "absolute": 3}
MOTIVE_BOON = {("aligned", "leaning"): 1, ("aligned", "driven"): 2, ("against", "leaning"): -1, ("against", "driven"): -2}
MAX_BOON = 2
MIN_SPOKEN_WORDS = 4
MIN_MATCH = 0.6  # the share of the quoted words that must be in the player's message, in order

SOCIAL_STYLES = ("advantage", "bonus", "circumstance", "reaction")

# Skills that are rolled with `social_check`. "Insight" and its kin are receptive: they are not speech and are not here.
# Performance is left out because it may be played to a crowd, which `social_check` (one listener) cannot name.
SOCIAL_SKILL = re.compile(
    r"\b(persuasion|persuade|diplomacy|deception|deceive|bluff|intimidat\w*|haggl\w*|gather information|"
    r"reaction roll)\b",
    re.IGNORECASE,
)


def words_problem(spoken: object, player_text: str) -> str | None:
    """Why the quoted words are not what the player said (None when they are). The quote may be trimmed or lightly
    reworded, so most of its words have to appear in the player's latest message, in order."""
    if not isinstance(spoken, str) or not spoken.strip():
        return "`spoken` is empty"
    quote = normalize_text(spoken).split()
    if len(quote) < MIN_SPOKEN_WORDS:
        return f"`spoken` is only {len(quote)} word{'s' if len(quote) != 1 else ''}"
    said = normalize_text(player_text).split()
    at = matched = 0
    for word in quote:
        try:
            at = said.index(word, at) + 1
        except ValueError:
            continue
        matched += 1
    if matched / len(quote) < MIN_MATCH:
        return "`spoken` is not what the player's latest message says"
    return None


@dataclass(frozen=True)
class MotiveEffect:
    """What the motives the words touch do to the check."""

    boon: int = 0  # added to the quality's boon
    auto_success: bool = False  # an absolute motive is served: no roll
    barred: bool = False  # an absolute motive is crossed: no roll, and no success
    decided_by: Motive | None = None  # the strongest motive that settled it, if any


def _rank(motive: Motive) -> float:
    """How hard a motive pulls: by strength, and the moment beats a lasting motive of the same strength."""
    return STRENGTH_RANK[motive.strength] + (0.5 if motive.scope == "scene" else 0.0)


def motive_effect(engaged: list[tuple[Motive, str]]) -> MotiveEffect:
    """Apply the motives the words touch (docs/ROLEPLAY.md 7.2). Only the strongest on each side counts; if both
    sides are engaged the stronger decides, and equal ones cancel."""
    best: dict[str, Motive] = {}
    for motive, effect in engaged:
        if effect not in best or _rank(motive) > _rank(best[effect]):
            best[effect] = motive
    aligned, against = best.get("aligned"), best.get("against")
    if aligned and against:
        if _rank(aligned) == _rank(against):
            return MotiveEffect()
        decider, effect = (aligned, "aligned") if _rank(aligned) > _rank(against) else (against, "against")
    elif aligned or against:
        decider, effect = (aligned, "aligned") if aligned else (against, "against")  # type: ignore[assignment]
    else:
        return MotiveEffect()
    if decider.strength == "absolute":
        return MotiveEffect(auto_success=effect == "aligned", barred=effect == "against", decided_by=decider)
    return MotiveEffect(boon=MOTIVE_BOON[(effect, decider.strength)], decided_by=decider)


def boon_for(quality: str, effect: MotiveEffect) -> int:
    """Quality and motive add, capped at plus or minus two."""
    return max(-MAX_BOON, min(MAX_BOON, QUALITY_BOON[quality] + effect.boon))


@dataclass(frozen=True)
class Plan:
    """The dice for a social check: an expression for the roller, and the number it is held against."""

    expression: str  # e.g. "2d20kh1+5", without a comment
    dc: int | None  # the target after any adjustment; None for a reaction roll, which has no DC
    modifier_note: str  # the boon in the ruleset's terms, for the GM's result ("advantage", "+2", "")


def _signed(n: int) -> str:
    return f"{n:+d}" if n else ""


def plan_roll(style: str, boon: int, modifier: int, dc: int | None) -> Plan:
    """Turn a boon into dice by the ruleset's `social_style` (the table in docs/ROLEPLAY.md 5)."""
    if style == "advantage":
        die = "2d20kh1" if boon > 0 else "2d20kl1" if boon < 0 else "1d20"
        note = "advantage" if boon > 0 else "disadvantage" if boon < 0 else ""
        if abs(boon) == 2 and dc is not None:  # advantage does not stack, so the second step moves the DC
            dc += -5 if boon > 0 else 5
            note += f" and DC {'-' if boon > 0 else '+'}5"
        return Plan(f"{die}{_signed(modifier)}", dc, note)
    if style == "bonus":
        bonus = 2 * boon
        return Plan(f"1d20{_signed(modifier + bonus)}", dc, f"{bonus:+d}" if bonus else "")
    if style == "circumstance":
        return Plan(f"1d20{_signed(modifier + boon)}", dc, f"{boon:+d} circumstance" if boon else "")
    if style == "reaction":
        return Plan(f"2d6{_signed(modifier + boon)}", None, f"{boon:+d} to the reaction roll" if boon else "")
    raise ValueError(f"unknown social style {style!r}")


DEGREES = ("critical failure", "failure", "success", "critical success")


def degree(total: int, dc: int, natural: int | None, shift_on_natural: bool) -> str:
    """Pathfinder 2e degrees of success: 10 or more over the DC is a critical success, 10 or more under a critical
    failure, and a natural 20 or 1 moves the result one step."""
    step = 3 if total >= dc + 10 else 2 if total >= dc else 0 if total <= dc - 10 else 1
    if shift_on_natural and natural == 20:
        step = min(3, step + 1)
    elif shift_on_natural and natural == 1:
        step = max(0, step - 1)
    return DEGREES[step]
