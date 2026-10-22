"""Chat session view-model: applies server events to the transcript. UI-free."""

from typing import Any

from aigm_client import events as ev
from aigm_client.blocks import (
    award_lines,
    DiceBlock,
    MarkdownBlock,
    ReasoningBlock,
    SystemBlock,
    history_to_blocks,
)
from aigm_client.transcript import Transcript


PHASE_LABELS = {"session_zero": "Session 0", "adventure": "Adventure"}
INTRO = {
    "session_zero": "Welcome! This is Session 0, where we choose the rules (D&D 5.5e by default, or any older D&D or Pathfinder edition) and set up your world and your party. Say hello to begin. Type /help for commands.",
    "adventure": "Welcome back. Describe what you do. Type /help for commands.",
}


def _seconds(ms: Any) -> str:
    return f"{ms / 1000:.1f}s" if isinstance(ms, (int, float)) else "-"


def _count(n: Any) -> str:
    return f"{n / 1000:.1f}k" if isinstance(n, int) and n >= 1000 else str(n if isinstance(n, int) else "-")


def metrics_line(m: dict[str, Any]) -> str:
    """One dim line for a finished turn (debug servers only): how long it took and what it cost."""
    return (
        f"first text {_seconds(m.get('first_text_ms'))} · total {_seconds(m.get('total_ms'))} · "
        f"in {_count(m.get('input_tokens'))} (cached {_count(m.get('cache_read_tokens'))}, "
        f"written {_count(m.get('cache_write_tokens'))}) · out {_count(m.get('output_tokens'))} · "
        f"{m.get('model_calls', '?')} call(s)"
    )


def story_note(story: dict[str, Any] | None) -> str:
    """"short story, chapter 2: The road" for a saved or live story game; "" for an endless game."""
    if not story:
        return ""
    if story.get("ended"):
        return f"{story.get('length', '')} story, finished".strip()
    title = story.get("chapter_title") or ""
    return f"{story.get('length', '')} story, chapter {story.get('chapter', '?')}" + (f": {title}" if title else "")


def intro_text(phase: str) -> str:
    return INTRO.get(phase, "Welcome, adventurer. Describe what you do. Type /help for commands.")


class ChatSession:
    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript
        self.busy = False  # a chat turn is in flight
        self.thinking = False
        self.status = ""  # a long wait the server is reporting ("Preparing the world..."); "" when none
        self.game_name: str | None = None
        self.phase = ""  # "session_zero" | "adventure" | "" (unknown)
        self.ruleset_name = ""  # e.g. "AD&D 1e"; "" when the server does not report it
        self.story: dict[str, Any] | None = None  # the server's public story summary (docs/STORY.md 11)
        self.dirty = False  # unsaved changes since last save/load/new
        self.changed = False  # set whenever anything visible changed; the UI clears it
        self.show_metrics = False  # a debug server: print each turn's timings and token use
        self._text: MarkdownBlock | None = None
        self._reasoning: ReasoningBlock | None = None

    # ---- derived ------------------------------------------------------------------------

    @property
    def phase_label(self) -> str:
        return PHASE_LABELS.get(self.phase, "")

    @property
    def story_label(self) -> str:
        """"Ch 2: The road" for a story game, "Story over" once it has ended, "" for an endless game."""
        story = self.story
        if not story:
            return ""
        if story.get("ended"):
            return "Story over"
        title = story.get("chapter_title") or ""
        return f"Ch {story.get('chapter', '?')}/3" + (f": {title}" if title else "")

    @property
    def can_input(self) -> bool:
        """The prompt is shown only when no turn is in flight and nothing is held."""
        return not self.busy and self.transcript.held == 0

    def _touch(self) -> None:
        self.transcript.invalidate()
        self.changed = True

    # ---- turn lifecycle -----------------------------------------------------------------

    def begin_turn(self, user_text: str) -> None:
        self.transcript.start_user_message(user_text)
        self.busy = True
        self.dirty = True
        self._text = self._reasoning = None
        self._touch()

    def apply(self, event: ev.Event) -> None:
        match event:
            case ev.Text(delta=delta):
                if self._text is None:
                    self._text = MarkdownBlock()
                    self.transcript.add(self._text)
                self._text.append(delta)
            case ev.Thinking(status="start"):
                self.thinking = True
                self._text = None  # text before/after a thinking phase are separate segments
                self._reasoning = None
            case ev.Thinking(status="delta", delta=delta):
                if self._reasoning is None:
                    self._reasoning = ReasoningBlock()
                    self.transcript.add(self._reasoning)
                self._reasoning.append(delta)
            case ev.Thinking(status="end"):
                self.thinking = False
                self._reasoning = None
            case ev.Status(done=True):
                self.status = ""
            case ev.Status(message=message):
                self.status = message
            case ev.ToolCall():
                self._text = None
            case ev.DiceRoll():
                self._text = None
                self.transcript.add(DiceBlock(event))
            case ev.MessageStart(phase=phase, ruleset_name=ruleset) if phase:
                self.phase = phase
                self.ruleset_name = ruleset or self.ruleset_name
            case ev.PhaseChange(phase=phase):
                self.phase = phase
                self._text = self._reasoning = None
                if phase == "adventure":
                    self.add_system("Session 0 is over. The adventure begins!", "bold green")
            case ev.ChapterChange(chapter=chapter, title=title):
                self._announce_chapter(chapter, title)
            case ev.Award() as award:
                self._text = None
                levelled = [
                    (c.name, c.level, ", ".join(f"{k} {v}" for k, v in c.classes))
                    for c in award.characters
                    if c.level > c.previous_level
                ]
                lines = award_lines(award.xp_gained, award.to, award.everyone, levelled, award.reason)
                for line in lines:
                    self.add_system(line, "bold green" if "reaches level" in line else "green")
            case ev.MessageEnd(phase=phase, ruleset_name=ruleset, metrics=metrics, story=story):
                if phase:
                    self.phase = phase
                self.ruleset_name = ruleset or self.ruleset_name
                if story is not None:  # a chapter that changed between turns shows up only here
                    if self.story and story.get("chapter") != self.story.get("chapter"):
                        self._announce_chapter(int(story.get("chapter", 0)), str(story.get("chapter_title", "")))
                    self.story = story
                self._finish_turn()
                if self.show_metrics and metrics:
                    self.add_system(metrics_line(metrics))
            case ev.ErrorEvent(message=message):
                self._finish_turn()
                self.add_system(
                    f"Error: {message or 'unknown error'} (this turn was discarded; send it again)", "red"
                )
            case _:  # MessageStart, Unknown: nothing to show
                pass
        self._touch()

    def _announce_chapter(self, chapter: int, title: str) -> None:
        """One banner per chapter: the event and the next message_end both report the same change."""
        if self.story and self.story.get("chapter") == chapter:
            return
        self.story = {**(self.story or {}), "chapter": chapter, "chapter_title": title, "ended": chapter > 3}
        if chapter > 3:
            self.add_system("The story has ended. You can keep playing in this world.", "bold green")
        else:
            self.add_system(f"Chapter {chapter}: {title}" if title else f"Chapter {chapter}", "bold green")

    def _finish_turn(self) -> None:
        self.busy = False
        self.thinking = False
        self.status = ""
        self._text = self._reasoning = None
        self.transcript.finalize_markdown()

    def fail(self, message: str) -> None:
        """A request failed before or outside the event stream (ApiError)."""
        self._finish_turn()
        self.add_system(f"Error: {message}", "red")

    def interrupted(self) -> None:
        self._finish_turn()
        self.add_system("[interrupted - turn discarded; send it again]", "yellow")

    # ---- other content ------------------------------------------------------------------

    def add_system(self, text: str, style: str = "dim") -> None:
        for line in text.splitlines() or [""]:
            self.transcript.add(SystemBlock(line, style))
        self._touch()

    def load_history(
        self, messages: list[dict[str, Any]], phase: str = "", ruleset_name: str = "", story: dict[str, Any] | None = None
    ) -> None:
        """Replace the transcript with a server history and open on its last page."""
        self.phase = phase
        self.ruleset_name = ruleset_name
        self.story = story
        self.transcript.replace_blocks(history_to_blocks(messages))
        self.busy = self.thinking = False
        self.status = ""
        self._text = self._reasoning = None
        self.dirty = False
        self._touch()

    def new_game(self, phase: str = "session_zero", ruleset_name: str = "") -> None:
        self.phase = phase
        self.ruleset_name = ruleset_name
        self.story = None
        self.transcript.clear()
        self.busy = self.thinking = False
        self.status = ""
        self._text = self._reasoning = None
        self.game_name = None
        self.dirty = False
        self._touch()

    def mark_saved(self, name: str) -> None:
        self.game_name = name
        self.dirty = False
        self.changed = True

    def mark_loaded(self, name: str) -> None:
        self.game_name = name
        self.dirty = False
        self.changed = True
