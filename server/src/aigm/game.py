"""What the model is shown for a given game state: the system prompt and the tools."""

from typing import Any

from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch, tool_schemas
from aigm.tools.base import ToolOutcome
from aigm.world.briefing import build_briefing

BRIEFING_OPEN = "<world_notes>"
BRIEFING_CLOSE = "</world_notes>"


class Game:
    """Per-phase prompts and tools. Prompt files are read once, at construction."""

    def __init__(self, prompts: PromptLibrary | None = None, briefing_tokens: int = 2000) -> None:
        self.prompts = prompts or PromptLibrary()
        self.briefing_tokens = briefing_tokens
        self._system = {phase: self.prompts.system_prompt(phase) for phase in Phase}
        self._tools = {phase: tool_schemas(self.prompts, phase) for phase in Phase}

    def system(self, state: GameState) -> str:
        prompt = self._system[state.phase]
        if state.phase is Phase.ADVENTURE and state.world.is_empty:
            # Normally the private notes live in the world as hidden facts. Without a world (curator
            # off, or an older save) the GM still needs them.
            notes = self.prompts.gm_notes_section(state.campaign)
            if notes:
                prompt = f"{prompt}\n\n{notes}"
        return prompt

    def briefing(self, state: GameState, user_text: str, gm_text: str) -> str:
        """The world notes for this request (empty outside the adventure or while the world is empty)."""
        if state.phase is not Phase.ADVENTURE:
            return ""
        notes = build_briefing(state.world, user_text=user_text, gm_text=gm_text, budget_tokens=self.briefing_tokens)
        return f"{BRIEFING_OPEN}\n{notes}\n{BRIEFING_CLOSE}" if notes else ""

    def request_messages(self, state: GameState, messages: list[dict[str, Any]], user_text: str) -> list[dict[str, Any]]:
        """The history as sent to the model: the stored messages plus the current world notes as an
        extra block at the end of the last user message. The notes are never stored in history, so
        each request carries exactly one briefing, the current one.

        The block before the notes is marked as a cache breakpoint, because the notes change
        every turn and the history up to that point does not."""
        notes = self.briefing(state, user_text, _last_gm_text(messages))
        if not notes or not messages or messages[-1]["role"] != "user":
            return messages
        content = [dict(b) for b in messages[-1]["content"]]
        if content:
            content[-1]["cache_control"] = {"type": "ephemeral"}
        content.append({"type": "text", "text": notes})
        return [*messages[:-1], {**messages[-1], "content": content}]

    def history_after_begin(self, state: GameState) -> list[dict[str, Any]]:
        """The conversation once the adventure begins. Session 0 (the discussion, the player's
        confirmation and the begin_adventure call) is discarded and replaced by a single GM entry:
        the campaign record built from the tool's arguments. The adventure's first reply follows it."""
        assert state.campaign is not None
        text = lambda t: [{"type": "text", "text": t}]  # noqa: E731
        return [
            {"role": "user", "content": text(self.prompts.session_zero_done_note())},
            {"role": "assistant", "content": text(self.prompts.campaign_record(state.campaign))},
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
