"""Transcript blocks and their rendering to terminal lines (lists of Rich Segments)."""

import io
from dataclasses import dataclass
from typing import Any

from rich.console import Console, RenderableType
from rich.markdown import Markdown
from rich.segment import Segment
from rich.text import Text

from aigm_client.events import DiceRoll
from aigm_client.heal import heal

Line = list[Segment]

_console = Console(file=io.StringIO(), force_terminal=True, color_system="truecolor", width=80)


def render_lines(renderable: RenderableType, width: int) -> list[Line]:
    options = _console.options.update(width=max(width, 1))
    return _console.render_lines(renderable, options, pad=False, new_lines=False)


def render_markdown(text: str, width: int) -> list[Line]:
    return render_lines(Markdown(text), width)


def plain(lines: list[Line]) -> list[str]:
    return ["".join(seg.text for seg in line) for line in lines]


@dataclass
class RenderContext:
    width: int
    show_reasoning: bool = False
    ascii_only: bool = False


class Block:
    """Base class. `version` must be bumped whenever the block's content changes."""

    version: int = 0

    def render(self, ctx: RenderContext) -> list[Line]:
        raise NotImplementedError


def _blank() -> Line:
    return [Segment("")]


class UserBlock(Block):
    def __init__(self, text: str) -> None:
        self.text = text

    def render(self, ctx: RenderContext) -> list[Line]:
        body = Text.assemble(("You: ", "bold cyan"), (self.text, "cyan"))
        return [_blank(), *render_lines(body, ctx.width), _blank()]


class MarkdownBlock(Block):
    """A segment of GM text. While streaming (`final` False) the display copy is healed."""

    def __init__(self, raw: str = "", final: bool = False) -> None:
        self.raw = raw
        self.final = final

    def append(self, delta: str) -> None:
        self.raw += delta
        self.version += 1

    def finalize(self) -> None:
        if not self.final:
            self.final = True
            self.version += 1

    def render(self, ctx: RenderContext) -> list[Line]:
        if not self.raw.strip():
            return []
        return render_markdown(self.raw if self.final else heal(self.raw), ctx.width)


class ReasoningBlock(Block):
    def __init__(self, text: str = "") -> None:
        self.text = text

    def append(self, delta: str) -> None:
        self.text += delta
        self.version += 1

    def render(self, ctx: RenderContext) -> list[Line]:
        if not ctx.show_reasoning or not self.text.strip():
            return []
        body = Text.assemble(("Reasoning: ", "dim bold"), (self.text.strip(), "dim italic"))
        return render_lines(body, ctx.width)


class SystemBlock(Block):
    def __init__(self, text: str, style: str = "dim") -> None:
        self.text = text
        self.style = style

    def render(self, ctx: RenderContext) -> list[Line]:
        return render_lines(Text(self.text, style=self.style), ctx.width)


class DiceBlock(Block):
    def __init__(self, event: DiceRoll) -> None:
        self.event = event

    def render(self, ctx: RenderContext) -> list[Line]:
        ev = self.event
        icon = "[dice]" if ctx.ascii_only else "🎲"
        text = Text(f"  {icon} ", style="yellow")
        text.append(ev.expression, style="bold yellow")
        if ev.dice:
            text.append("  →  ", style="yellow")
            for ti, term in enumerate(ev.dice):
                if ti:
                    text.append("; ", style="yellow")
                text.append(f"{term.notation}: ", style="yellow")
                for ri, roll in enumerate(term.rolls):
                    if ri:
                        text.append(" ")
                    if roll.kept:
                        text.append(f"[{roll.value}]", style="bold")
                    else:
                        text.append(f"[{roll.value}]", style="dim strike")
        elif ev.result:
            text.append("  →  ", style="yellow")
            text.append(_strip_markup(ev.result))
        if ev.total is not None:
            text.append("  =  ", style="yellow")
            text.append(str(ev.total), style="bold white")
        if ev.crit == "crit":
            text.append("  CRITICAL!", style="bold green")
        elif ev.crit == "fail":
            text.append("  FUMBLE!", style="bold red")
        if ev.comment:
            text.append(f"  # {ev.comment}", style="dim")
        return render_lines(text, ctx.width)


def award_lines(
    xp_gained: int, to: list[str] | tuple[str, ...], everyone: bool, levelled: list[tuple[str, int, str]], reason: str
) -> list[str]:
    """What the player is told when the party earns something: the XP line, then one line per character who levelled
    (name, overall level, a note such as "Paladin 2, Rogue 1")."""
    lines = []
    if xp_gained:
        who = "the party" if everyone else ", ".join(to) or "the party"
        lines.append(f"  +{xp_gained} XP " + ("each to " if not everyone and len(to) > 1 else "to ") + who)
    lines += [f"  {name} reaches level {level}!" + (f" ({note})" if note else "") for name, level, note in levelled]
    if lines and reason:
        lines[0] += f" for {reason}"
    return lines or [f"  Awarded for {reason}" if reason else "  Awarded"]


def _strip_markup(s: str) -> str:
    """Drop d20's markdown emphasis (**bold**, ~~struck~~, `code`) for plain display."""
    for token in ("**", "~~", "`"):
        s = s.replace(token, "")
    return s


def history_to_blocks(messages: list[dict[str, Any]]) -> list[Block]:
    """Map Anthropic-format history (GET /chat/history) to display blocks."""
    blocks: list[Block] = []
    roll_inputs: dict[str, str] = {}
    for msg in messages:
        content = msg.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if msg.get("role") == "user":
            texts = [b.get("text", "") for b in content if b.get("type") == "text"]
            if texts:
                text = "\n".join(texts)
                if text.startswith("[System:"):  # a note the server inserted, not something the player typed
                    blocks.append(SystemBlock(text.strip("[]").removeprefix("System: "), "dim"))
                else:
                    blocks.append(UserBlock(text))
            for b in content:
                if b.get("type") != "tool_result":
                    continue
                expr = roll_inputs.get(b.get("tool_use_id", ""), "")
                if b.get("is_error"):
                    blocks.append(SystemBlock(f"  (roll failed: {expr})", "dim"))
                else:
                    result = b.get("content", "")
                    if isinstance(result, list):
                        result = "".join(p.get("text", "") for p in result)
                    blocks.append(DiceBlock(DiceRoll(expression=expr, result=str(result))))
        else:
            for b in content:
                if b.get("type") == "text" and b.get("text", "").strip():
                    blocks.append(MarkdownBlock(b["text"], final=True))
                elif b.get("type") == "tool_use" and b.get("name") == "award":
                    given = b.get("input") or {}
                    xp = given.get("xp") if isinstance(given.get("xp"), int) else 0
                    who = [str(n) for n in given.get("who") or [] if isinstance(n, str)]
                    ups = [
                        (str(u.get("who", "")), int(u["level"]) if isinstance(u.get("level"), int) else 0,
                         f"{u['class']} {u['class_level']}" if u.get("class") and u.get("class_level") else "")
                        for u in given.get("level_up") or [] if isinstance(u, dict)
                    ]  # fmt: skip
                    for line in award_lines(xp, who, not who, ups, str(given.get("reason", "")).strip()):
                        blocks.append(SystemBlock(line, "green"))
                elif b.get("type") == "tool_use" and b.get("name") == "roll_dice":
                    given = b.get("input") or {}
                    roll_inputs[b.get("id", "")] = str(given.get("expression", ""))
                    narration = str(given.get("narration", "")).strip()
                    if narration:  # shown as story text just before the dice, as it was live
                        blocks.append(MarkdownBlock(narration, final=True))
    return blocks
