"""What the model is shown for a given game state: the system prompt and the tools."""

from typing import Any

from aigm.prompts import PromptLibrary
from aigm.session.state import GameState, Phase
from aigm.tools import dispatch, tool_schemas
from aigm.tools.base import ToolOutcome


class Game:
    """Per-phase prompts and tools. Prompt files are read once, at construction."""

    def __init__(self, prompts: PromptLibrary | None = None) -> None:
        self.prompts = prompts or PromptLibrary()
        self._system = {phase: self.prompts.system_prompt(phase) for phase in Phase}
        self._tools = {phase: tool_schemas(self.prompts, phase) for phase in Phase}

    def system(self, state: GameState) -> str:
        prompt = self._system[state.phase]
        if state.phase is Phase.ADVENTURE:
            notes = self.prompts.gm_notes_section(state.campaign)
            if notes:
                prompt = f"{prompt}\n\n{notes}"
        return prompt

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
