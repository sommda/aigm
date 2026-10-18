from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from aigm.history import HistoryPolicy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    model: str = Field(default="claude-sonnet-5-5", validation_alias="AIGM_MODEL")
    max_tokens: int = Field(default=16000, validation_alias="AIGM_MAX_TOKENS")
    max_tool_iters: int = Field(default=8, validation_alias="AIGM_MAX_TOOL_ITERS")
    stream_thinking: bool = Field(default=True, validation_alias="AIGM_STREAM_THINKING")
    # Seconds to wait before each dice roll is shown, so the narration leading up to it can be read.
    roll_pause: float = Field(default=0.8, ge=0, validation_alias="AIGM_ROLL_PAUSE")
    # Request readable thinking summaries (adaptive thinking). Set false for models that do not
    # support adaptive thinking; the model then uses its own default.
    thinking_summaries: bool = Field(default=True, validation_alias="AIGM_THINKING_SUMMARIES")
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = Field(
        default=None, validation_alias="AIGM_EFFORT"
    )
    # Rough size, in tokens, of the world notes shown to the GM with each request.
    world_briefing_tokens: int = Field(default=2000, validation_alias="AIGM_WORLD_BRIEFING_TOKENS")
    # Shrinking the history the model sees (docs/HISTORY.md). The stored messages are never changed. Turns older than
    # *_keep are trimmed (thinking dropped, tool calls folded into notes) or replaced by their digests; the cuts move
    # every *_step turns, so the start of the request stays the same in between and the prompt cache keeps hitting.
    history_trim: bool = Field(default=True, validation_alias="AIGM_HISTORY_TRIM")
    history_trim_keep: int = Field(default=4, ge=1, validation_alias="AIGM_HISTORY_TRIM_KEEP")
    history_trim_step: int = Field(default=6, ge=1, validation_alias="AIGM_HISTORY_TRIM_STEP")
    history_digest: bool = Field(default=True, validation_alias="AIGM_HISTORY_DIGEST")
    history_digest_keep: int = Field(default=12, ge=1, validation_alias="AIGM_HISTORY_DIGEST_KEEP")
    history_digest_step: int = Field(default=12, ge=1, validation_alias="AIGM_HISTORY_DIGEST_STEP")
    # Write one JSON line per turn (timings, token usage, request sizes) to {save_dir}/metrics/{session}.jsonl.
    metrics: bool = Field(default=True, validation_alias="AIGM_METRICS")
    # The world curator's models: a cheap one for extraction, reconciliation and checks, a stronger
    # one for inventing new parts of the world. Point both at one model to tune.
    world_curator: bool = Field(default=True, validation_alias="AIGM_WORLD_CURATOR")
    world_model: str = Field(default="claude-haiku-5-5", validation_alias="AIGM_WORLD_MODEL")
    world_expand_model: str = Field(default="claude-sonnet-5-5", validation_alias="AIGM_WORLD_EXPAND_MODEL")
    world_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(default="low", validation_alias="AIGM_WORLD_EFFORT")
    world_expand_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        default="medium", validation_alias="AIGM_WORLD_EXPAND_EFFORT"
    )
    # Keep a readable JSON dump of each session's world in {save_dir}/worlds/ for debugging.
    world_dump: bool = Field(default=True, validation_alias="AIGM_WORLD_DUMP")
    # The curator runs in the background once this many pages of GM narration have built up.
    world_every_pages: float = Field(default=3.0, validation_alias="AIGM_WORLD_EVERY_PAGES")
    world_page_chars: int = Field(default=1800, validation_alias="AIGM_WORLD_PAGE_CHARS")
    prompt_dir: Path | None = Field(default=None, validation_alias="AIGM_PROMPT_DIR")
    save_dir: Path = Field(default=Path("./saves"), validation_alias="AIGM_SAVE_DIR")
    test_mode: bool = Field(default=False, validation_alias="AIGM_TEST_MODE")
    # Debug mode: expose GET /debug/context, which shows the GM's private notes (start with `aigm --debug`).
    debug: bool = Field(default=False, validation_alias="AIGM_DEBUG")
    test_delay: float = Field(default=0.02, validation_alias="AIGM_TEST_DELAY")
    test_chunk_size: int = Field(default=4, validation_alias="AIGM_TEST_CHUNK_SIZE")
    cors_origins: list[str] = Field(
        default=["http://localhost", "http://127.0.0.1"], validation_alias="AIGM_CORS_ORIGINS"
    )

    @property
    def history_policy(self) -> HistoryPolicy:
        return HistoryPolicy(
            trim=self.history_trim,
            trim_keep=self.history_trim_keep,
            trim_step=self.history_trim_step,
            digest=self.history_digest,
            digest_keep=self.history_digest_keep,
            digest_step=self.history_digest_step,
        )
