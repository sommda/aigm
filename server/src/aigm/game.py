"""What the model is shown for a given game state: the system prompt and the tools."""

from dataclasses import dataclass
from typing import Any

from aigm.history import HistoryPolicy, Reduction, reduce_history
from aigm.prompts import PromptLibrary, PromptPart
from aigm.rulesets import RULESETS
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch, tool_schemas
from aigm.tools.base import ToolOutcome
from aigm.world.briefing import build_briefing

BRIEFING_OPEN = "<world_notes>"
BRIEFING_CLOSE = "</world_notes>"


@dataclass(frozen=True)
class RequestDescription:
    """Everything the model is shown for one request, in named parts.

    The real request is derived from this (`system`, `tools`, `messages`), so anything that wants to
    display the request reads the same object and cannot drift from what is sent."""

    system_parts: tuple[PromptPart, ...]
    tools: list[dict[str, Any]]
    history: list[dict[str, Any]]  # the stored messages as reduced for the model (no world notes)
    briefing: str  # the <world_notes> block for this request, "" if none
    reduction: Reduction = Reduction()  # what the reduction did to the stored messages

    @property
    def system(self) -> str:
        return "\n\n".join(part.text for part in self.system_parts)

    @property
    def messages(self) -> list[dict[str, Any]]:
        """The history as sent to the model: the stored messages plus the world notes as an extra block
        at the end of the last user message. The notes are never stored in history, so each request
        carries exactly one briefing, the current one.

        The block before the notes is marked as a cache breakpoint, because the notes change
        every turn and the history up to that point does not."""
        if not self.briefing or not self.history or self.history[-1]["role"] != "user":
            return self.history
        last = self.history[-1]
        content = [dict(b) for b in last["content"]]
        if content:
            content[-1]["cache_control"] = {"type": "ephemeral"}
        content.append({"type": "text", "text": self.briefing})
        return [*self.history[:-1], {**last, "content": content}]


class Game:
    """Per-phase prompts and tools. Prompt files are read once, at construction."""

    def __init__(
        self,
        prompts: PromptLibrary | None = None,
        briefing_tokens: int = 2000,
        history_policy: HistoryPolicy | None = None,
    ) -> None:
        self.prompts = prompts or PromptLibrary()
        self.briefing_tokens = briefing_tokens
        self.history_policy = history_policy or HistoryPolicy()
        self._system = {
            (phase, rs.id): tuple(self.prompts.system_parts(phase, rs.id)) for phase in Phase for rs in RULESETS
        }
        self._tools = {phase: tool_schemas(self.prompts, phase) for phase in Phase}

    def system_parts(self, state: GameState) -> tuple[PromptPart, ...]:
        parts = self._system[state.phase, state.ruleset]
        if state.phase is Phase.ADVENTURE and state.world.is_empty:
            # Normally the private notes live in the world as hidden facts. Without a world (curator
            # off, or an older save) the GM still needs them.
            notes = self.prompts.gm_notes_section(state.campaign)
            if notes:
                parts = (*parts, PromptPart("templates/gm_notes.md", notes))
        return parts

    def system(self, state: GameState) -> str:
        return "\n\n".join(part.text for part in self.system_parts(state))

    def describe(self, state: GameState, messages: list[dict[str, Any]], user_text: str) -> RequestDescription:
        """The request for the model: `messages` is the stored history ending with the user's message.
        The briefing is chosen from the full history; the history sent is the reduced view of it."""
        reduced = reduce_history(messages, state.world.digests, self.history_policy)
        return RequestDescription(
            system_parts=self.system_parts(state),
            tools=self.tools(state),
            history=reduced.messages,
            briefing=self.briefing(state, user_text, _last_gm_text(messages)),
            reduction=reduced.info,
        )

    def briefing(self, state: GameState, user_text: str, gm_text: str) -> str:
        """The world notes for this request (empty outside the adventure or while the world is empty)."""
        if state.phase is not Phase.ADVENTURE:
            return ""
        notes = build_briefing(state.world, user_text=user_text, gm_text=gm_text, budget_tokens=self.briefing_tokens)
        return f"{BRIEFING_OPEN}\n{notes}\n{BRIEFING_CLOSE}" if notes else ""

    def request_messages(self, state: GameState, messages: list[dict[str, Any]], user_text: str) -> list[dict[str, Any]]:
        """The history as sent to the model (see `RequestDescription.messages`)."""
        return self.describe(state, messages, user_text).messages

    def history_after_begin(self, state: GameState) -> list[dict[str, Any]]:
        """The conversation once the adventure begins. Session 0 (the discussion, the player's
        confirmation and the begin_adventure call) is discarded and replaced by a single GM entry:
        the campaign record built from the tool's arguments. The adventure's first reply follows it."""
        assert state.campaign is not None
        text = lambda t: [{"type": "text", "text": t}]  # noqa: E731
        return [
            {"role": "user", "content": text(self.prompts.session_zero_done_note())},
            {"role": "assistant", "content": text(self.prompts.campaign_record(state.campaign, state.ruleset, state.structure))},
            {"role": "user", "content": text(self.prompts.begin_cue())},
        ]

    def tools(self, state: GameState) -> list[dict[str, Any]]:
        return self._tools[state.phase]

    def dispatch(self, state: GameState, name: str, tool_use_id: str, tool_input: dict[str, Any]) -> ToolOutcome:
        return dispatch(name, tool_use_id, tool_input, state)


def _last_gm_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg["role"] == "assistant":
            text = "".join(b.get("text", "") for b in msg["content"] if b.get("type") == "text")
            if text:
                return text
    return ""
