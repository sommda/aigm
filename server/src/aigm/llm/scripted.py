"""A scripted stand-in for the LLM, used by `--test` mode.

The user's chat message selects a canned "plan" (a list of steps). Plans exercise the real
server pipeline (SSE framing, tool loop, real `roll_dice`, history) with no network access.
Send `help` to list the commands.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from aigm.llm.base import (
    Completed,
    LLMError,
    LLMEvent,
    TextChunk,
    ThinkingChunk,
    ThinkingStarted,
    ThinkingStopped,
    ToolInputChunk,
    ToolInputStarted,
    ToolInputStopped,
)


# ---- plan steps ------------------------------------------------------------------------


@dataclass
class Think:
    text: str


@dataclass
class Say:
    text: str


@dataclass
class UseTool:
    name: str
    input: dict[str, Any]


@dataclass
class Fail:
    message: str
    retryable: bool = True


@dataclass
class Pause:
    seconds: float


Step = Think | Say | UseTool | Fail | Pause

HELP = """\
## Test mode commands

The server is running with `--test`: replies are scripted, not from a model. Try:

- `roll <expr>`: roll dice via the real `roll_dice` tool, e.g. `roll 4d6kh3+2 # strength`
- `multiroll`: two dice rolls in one response
- `ruleset <id>`: choose the game's ruleset in Session 0 (calls the real `set_ruleset` tool), e.g. `ruleset adnd1e`; ids are in docs/RULESETS.md
- `structure <mode>`: choose endless, short, medium or long in Session 0 (calls the real `set_structure` tool)
- `begin`: end Session 0 and start the adventure (calls the real `begin_adventure` tool; a new game starts in Session 0)
- `establish <name>`: record a new person in the world (adventure only; calls the real `establish` tool)
- `recall <name>`: look a name up in the world (adventure only; calls `recall`)
- `persuade <name> [words]`: a social check on a person (adventure only; calls `social_check`). With no words the GM asks what you say; with words of your own it rolls, and eight or more words count as strong. Name a person you have `establish`ed
- `motive <name> [text]`: give a recorded person a scene motive (adventure only; calls `set_motive`)
- `quest <id> <done|skipped|failed> [outcome]` or `quest goal`: report story progress (story games; calls `set_scene`)
- `scene <place> [hours]`: set the scene and pass time (adventure only; calls `set_scene`)
- `hurt <name> <n>` (or `heal <name> <n>`): change a party member's hit points (adventure only; calls `update_character`)
- `fight [foes]` (`fight wolf 3`) starts a fight, `wound <name> <word>` changes a foe's health, `peace` ends it (adventure only; calls `set_combat`)
- `badroll [expr]`: a malformed roll (shows the tool-error path)
- `markdown`: a sampler of every markup form below
- `bold`, `italic`, `strike`, `code`, `codeblock`, `list`, `numbered`, `heading`, `quote`, `table`, `link`
- `think [n]`: a thinking phase of *n* sentences, then an answer
- `long [n]`: *n* paragraphs of text (to test paging)
- `slow`: a 2 second pause before replying
- `error`: text, then a simulated upstream failure
- `loop`: endless tool calls (hits the tool-loop limit)
- `echo <text>`: repeat your text back (markdown allowed)

Anything else is echoed back."""

SAMPLES: dict[str, str] = {
    "bold": "The door **splinters** inward and the goblin lets out a **very loud** shriek.",
    "italic": "The torchlight flickers; *something* moves in the *dark* ahead.",
    "strike": "You thought it was ~~a friendly innkeeper~~ a disguised assassin.",
    "code": "Inscribed on the blade: `Ignis Mortem`. Use the `search` action to look closer.",
    "codeblock": "The scroll reads:\n\n```python\ndef fireball(level):\n    return f\"{level + 2}d6 fire damage\"  # **not bold**\n```\n\nIt crumbles to dust.",
    "list": "You find in the chest:\n\n- a **rusty** key\n- a *glowing* gem\n- 3 gold coins\n  - one of them is cursed\n\nWhat do you take?",
    "numbered": "Your options:\n\n1. Fight the goblin\n2. Sneak past it\n3. **Bribe** it with the gem\n\nChoose wisely.",
    "heading": "# The Sunken Temple\n\nWater drips from the ceiling.\n\n## The First Chamber\n\nA statue stares back at you.\n\n### Inscription\n\nIt reads: *beware*.",
    "quote": "The old hermit rasps:\n\n> Seek the key beneath the *weeping stone*,\n> and **never** look back.\n\nHe vanishes into the mist.",
    "table": "Your party:\n\n| Name   | Class   | HP |\n|--------|---------|----|\n| Aria   | Rogue   | 18 |\n| Brom   | Fighter | 31 |\n| Cael   | Wizard  | 12 |\n\nAll alive, for now.",
    "link": "See the [Adventurer's Guide](https://example.com/guide) for the rules, or visit [the map](https://example.com/map).",
}


def markdown_sampler() -> str:
    return "\n\n".join(SAMPLES[k] for k in ("heading", "bold", "italic", "strike", "code", "list", "numbered", "quote", "table", "link", "codeblock"))


def long_text(n: int) -> str:
    words = "the party presses onward through mist and shadow while distant bells toll".split()
    paras = []
    for i in range(1, n + 1):
        body = " ".join(words[(i + j) % len(words)] for j in range(36))
        paras.append(f"**Paragraph {i}.** {body.capitalize()}.")
    return "\n\n".join(paras)


# ---- planning --------------------------------------------------------------------------


def _int(arg: str, default: int, lo: int = 1, hi: int = 200) -> int:
    try:
        return max(lo, min(hi, int(arg.split()[0])))
    except (ValueError, IndexError):
        return default


TEST_CAMPAIGN = {
    "confirmed": True,
    "setting": (
        "The Test Marches: a gritty border region of crumbling forts and muddy roads, where the old kingdom's "
        "garrisons have been left to rot. Rival bandit chiefs and a failing baron squabble over toll roads, and "
        "something stirs in the drowned crypts beneath the oldest fort. The tone is grim but not hopeless. "
        "A level 1 party will find it dangerous but survivable."
    ),
    "opening": "The party shelters from a storm in the common room of the Rusty Flagon inn, where a nervous traveller wants to hire guards.",
    "level": 1,
    "party": [
        {
            "name": "Test Hero",
            "sheet": "Human fighter, Soldier background, level 1. STR 16, DEX 13, CON 14, INT 10, WIS 12, CHA 8. HP 12, AC 16 (chain mail, shield). Longsword, handaxes, Second Wind. Blunt, loyal, hates wizards.",
            "appearance": "A broad-shouldered man in his thirties with a weathered face, close-cropped dark hair and a "
            "crooked nose, in a dented chain shirt over a faded blue tabard.",
            "background": "A former garrison soldier from the fens who knows the roads and the inns of the region well. "
            "[[knows: Old Tam:npc | Old Tam ferries travellers across the marsh and gossips about every inn on the road.]]",
        }
    ],
    "gm_notes": (
        "The innkeeper is a spy. [[at: Rusty Flagon:location]] [[present: Innkeeper:npc]] [[hour: 18]] "
        "[[hidden: Innkeeper | The innkeeper of the Rusty Flagon reports every guest to the baron.]]"
    ),
}


OPENING_SCENE = "## The adventure begins\n\nYou stand in the common room of the **Rusty Flagon**. Rain drums on the roof. What do you do?"


def _establish_plan(name: str) -> list[Step]:
    name = name or "Wren"
    return [
        Say(f"A figure steps forward: {name}. "),
        UseTool(
            "establish",
            {
                "entities": [{"name": name, "kind": "npc"}],
                "facts": [{"text": f"{name} tends the bar at the Rusty Flagon inn.", "about": [name]}],
            },
        ),
    ]


def _motive_plan(arg: str) -> list[Step]:
    name, _, text = arg.partition(" ")
    name = name or "Wren"
    text = text.strip() or f"{name} wants the visitors gone before the captain returns."
    change = {"op": "add", "owner": name, "text": text, "scope": "scene", "kind": "want", "strength": "driven",
              "tells": [f"{name} keeps glancing at the door."]}
    return [Say("A hush falls. "), UseTool("set_motive", {"changes": [change]})]


def _persuade_plan(arg: str) -> list[Step]:
    name, _, words = arg.partition(" ")
    name, words = name or "Wren", words.strip()
    if not words:  # a declared intention, not a played one: the real GM asks what the character says
        return [Say(f"{name} waits, watching you. What do you say?")]
    quality = "strong" if len(words.split()) >= 8 else "ordinary"
    check = {"character": "Test Hero", "skill": "Persuasion", "target": name, "spoken": words, "quality": quality,
             "modifier": 3, "dc": 12, "narration": f"You turn to {name} and speak plainly."}
    return [UseTool("set_scene", {"present": [name]}), UseTool("social_check", check)]


def _scene_plan(arg: str) -> list[Step]:
    place, _, hours = arg.rpartition(" ")
    if not hours.isdigit():
        place, hours = arg, ""
    payload: dict[str, Any] = {"location": place.strip() or arg}
    if hours:
        payload["elapsed_hours"] = int(hours)
    return [Say("You move on. "), UseTool("set_scene", payload)]


def _quest_plan(arg: str) -> list[Step]:
    """`quest m01 done [outcome]` reports a quest; `quest goal` reports that the player learned the goal."""
    if arg.strip() == "goal":
        return [Say("It comes together. "), UseTool("set_scene", {"story": {"goal_revealed": True}})]
    quest, _, rest = arg.partition(" ")
    status, _, outcome = rest.partition(" ")
    report = {"id": quest, "status": status or "done", "outcome": outcome or "It happened."}
    return [Say("That settles it. "), UseTool("set_scene", {"story": {"quests": [report]}})]


def _hp_plan(sign: int):
    def plan(arg: str) -> list[Step]:
        who, _, amount = arg.rpartition(" ")
        if not amount.isdigit():
            who, amount = arg, "1"
        return [Say("It tells. "), UseTool("update_character", {"name": who.strip(), "hp_delta": sign * int(amount)})]

    return plan


def _fight_plan(arg: str) -> list[Step]:
    name, _, count = (arg or "Wolf").rpartition(" ")
    if not count.isdigit():
        name, count = arg or "Wolf", "1"
    row = {"name": name.strip(), "side": "foe", "count": int(count)}
    return [Say("Steel is drawn. "), UseTool("set_combat", {"action": "start", "combatants": [row]})]


def _wound_plan(arg: str) -> list[Step]:
    name, _, word = arg.partition(" ")
    return [Say("A blow lands. "), UseTool("set_combat", {"action": "update", "combatants": [{"name": name, "health": word or "bloodied"}]})]


WORLD_COMMANDS: dict[str, Callable[[str], list[Step]]] = {
    "quest": _quest_plan,
    "establish": _establish_plan,
    "motive": _motive_plan,
    "persuade": _persuade_plan,
    "recall": lambda arg: [Say("Let me think... "), UseTool("recall", {"about": arg or "Wren"})],
    "scene": _scene_plan,
    "fight": _fight_plan,
    "wound": _wound_plan,
    "peace": lambda arg: [Say("It is over. "), UseTool("set_combat", {"action": "end"})],
    "hurt": _hp_plan(-1),
    "heal": _hp_plan(1),
}


def plan_for(text: str, tools: tuple[str, ...] = (), structure_chosen: bool = False) -> list[Step]:
    cmd, _, rest = text.strip().partition(" ")
    cmd, arg = cmd.lower(), rest.strip()
    if cmd == "help":
        return [Say(HELP)]
    if cmd == "ruleset":
        if "set_ruleset" not in tools:
            return [Say("The ruleset was fixed when the adventure began.")]
        return [Say("Changing the rules... "), UseTool("set_ruleset", {"ruleset": arg or "dnd55e"})]
    if cmd == "structure":
        if "set_structure" not in tools:
            return [Say("The kind of game was fixed when the adventure began.")]
        return [Say("Planning the shape of the game... "), UseTool("set_structure", {"mode": arg or "endless"})]
    if cmd == "begin":
        if "begin_adventure" not in tools:
            return [Say("The adventure has already begun; there is no way back to Session 0.")]
        begin = UseTool("begin_adventure", dict(TEST_CAMPAIGN))
        if structure_chosen:
            return [Say("Then let us begin! "), begin]
        # a real GM would have asked; the script just picks the endless game
        return [Say("Then let us begin! "), UseTool("set_structure", {"mode": "endless"}), begin]
    if cmd in WORLD_COMMANDS and "recall" in tools:
        return WORLD_COMMANDS[cmd](arg)
    if cmd == "echo":
        return [Say(arg or "Echo what?")]
    if cmd == "roll":
        expr = arg or "1d20"
        lead = f"You reach for the dice and roll **{expr.split('#')[0].strip()}**..."
        return [UseTool("roll_dice", {"expression": expr, "narration": lead})]
    if cmd == "multiroll":
        return [
            UseTool("roll_dice", {"expression": "1d20+5 # attack", "narration": "Attack and damage, coming up."}),
            UseTool("roll_dice", {"expression": "2d6+3 # damage", "narration": "If it lands, it bites deep."}),
        ]
    if cmd == "badroll":
        return [UseTool("roll_dice", {"expression": arg or "2x20", "narration": "Trying a strange roll..."})]
    if cmd == "markdown":
        return [Say(markdown_sampler())]
    if cmd in SAMPLES:
        return [Say(SAMPLES[cmd])]
    if cmd == "think":
        n = _int(arg, 3, 1, 30)
        thoughts = " ".join(f"Consideration {i}: weigh the risks and the rewards." for i in range(1, n + 1))
        return [Think(thoughts), Say("After careful thought, the **best** course is to proceed.")]
    if cmd == "long":
        return [Say(long_text(_int(arg, 8, 1, 100)))]
    if cmd == "slow":
        return [Pause(2.0), Say("That took a while, but here I am.")]
    if cmd == "error":
        return [Say("Starting to answer, and then "), Fail("Simulated upstream failure")]
    if cmd == "loop":
        return [UseTool("roll_dice", {"expression": "1d6", "narration": "Rolling again."})]
    mode = "Session 0" if "begin_adventure" in tools else "Adventure"
    return [Say(f"[test mode: {mode}] You said: {text.strip()}\n\nType `help` to see the test commands.")]


# ---- the client ------------------------------------------------------------------------


def _user_text(message: dict[str, Any]) -> str | None:
    blocks = message.get("content", [])
    texts = [
        b.get("text", "")
        for b in blocks
        if b.get("type") == "text" and not b.get("text", "").startswith("<world_notes>")
    ]
    return "\n".join(texts) if texts else None


def _last_command_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg["role"] == "user":
            text = _user_text(msg)
            if text is not None:
                return text
    return ""


def narrate_tool_results(messages: list[dict[str, Any]]) -> list[Step]:
    """The follow-up after tool results: describe each roll (or its error)."""
    uses: dict[str, tuple[str, dict[str, Any]]] = {}
    if len(messages) >= 2:
        for b in messages[-2].get("content", []):
            if b.get("type") == "tool_use":
                uses[b["id"]] = (b.get("name", ""), b.get("input", {}))
    lines = []
    for b in messages[-1].get("content", []):
        if b.get("type") != "tool_result":
            continue
        name, tool_input = uses.get(b.get("tool_use_id"), ("", {}))
        if name == "begin_adventure":  # on success the history is replaced, so only errors get here
            lines.append(f"- The adventure could not begin: {b.get('content')}")
            continue
        if name in WORLD_COMMANDS or name in ("recall", "establish", "set_scene", "set_motive", "social_check", "set_ruleset", "set_structure", "update_character", "set_combat"):
            lines.append(f"- `{name}`{' (error)' if b.get('is_error') else ''}:\n\n```\n{b.get('content')}\n```")
            continue
        expr = tool_input.get("expression", "?")
        if b.get("is_error"):
            lines.append(f"- The dice refused `{expr}`: {b.get('content')}")
        else:
            lines.append(f"- `{expr}` came up: {b.get('content')}")
    return [Say("\n\n" + "\n".join(lines) + "\n\nThe die is cast." if lines else "\n\nDone.")]


class ScriptedLLM:
    def __init__(self, delay: float = 0.02, chunk_size: int = 4) -> None:
        self.delay = delay
        self.chunk_size = max(1, chunk_size)
        self.thinking = True  # kept so the debug route works; the script's thinking steps are not affected

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def stream(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]:
        last = messages[-1]
        after_tools = last["role"] == "user" and any(
            b.get("type") == "tool_result" for b in last.get("content", [])
        )
        command = _last_command_text(messages)
        if command.startswith("[System: The adventure begins"):  # the server's cue after Session 0
            plan: list[Step] = [Say(OPENING_SCENE)]
        elif after_tools and command.strip().lower().startswith("loop"):
            plan = [UseTool("roll_dice", {"expression": "1d6", "narration": "Rolling again."})]
        elif after_tools:
            plan = narrate_tool_results(messages)
        else:
            chosen = any(
                b.get("type") == "tool_use" and b.get("name") == "set_structure"
                for m in messages
                for b in m.get("content", [])
            )
            plan = plan_for(command, tuple(t.get("name", "") for t in tools), chosen)

        content: list[dict[str, Any]] = []
        out_chars = 0
        for step in plan:
            if isinstance(step, Pause):
                await self._sleep(step.seconds)
            elif isinstance(step, Think):
                yield ThinkingStarted()
                for chunk in self._chunks(step.text):
                    yield ThinkingChunk(chunk)
                    await self._sleep(self.delay)
                yield ThinkingStopped()
                content.append({"type": "thinking", "thinking": step.text, "signature": "test-signature"})
            elif isinstance(step, Say):
                for chunk in self._chunks(step.text):
                    yield TextChunk(chunk)
                    out_chars += len(chunk)
                    await self._sleep(self.delay)
                if content and content[-1]["type"] == "text":
                    content[-1]["text"] += step.text
                else:
                    content.append({"type": "text", "text": step.text})
            elif isinstance(step, UseTool):
                tool_id = f"toolu_test_{uuid.uuid4().hex[:10]}"
                yield ToolInputStarted(tool_id, step.name)
                # the input goes out as JSON fragments, expression first like the real model writes it
                ordered = {k: v for k, v in step.input.items() if k != "narration"}
                ordered.update({k: v for k, v in step.input.items() if k == "narration"})
                for chunk in self._chunks(json.dumps(ordered)):
                    yield ToolInputChunk(tool_id, chunk)
                    await self._sleep(self.delay)
                yield ToolInputStopped(tool_id)
                content.append({"type": "tool_use", "id": tool_id, "name": step.name, "input": step.input})
            elif isinstance(step, Fail):
                raise LLMError(step.message, retryable=step.retryable)
        has_tool = any(b["type"] == "tool_use" for b in content)
        yield Completed(
            content=content,
            stop_reason="tool_use" if has_tool else "end_turn",
            usage={"input_tokens": sum(len(str(m)) for m in messages) // 4, "output_tokens": max(out_chars // 4, 1)},
        )

    def _chunks(self, text: str):
        for i in range(0, len(text), self.chunk_size):
            yield text[i : i + self.chunk_size]
