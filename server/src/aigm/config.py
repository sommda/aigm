from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    model: str = Field(default="claude-sonnet-5-5", validation_alias="AIGM_MODEL")
    max_tokens: int = Field(default=16000, validation_alias="AIGM_MAX_TOKENS")
    max_tool_iters: int = Field(default=8, validation_alias="AIGM_MAX_TOOL_ITERS")
    stream_thinking: bool = Field(default=True, validation_alias="AIGM_STREAM_THINKING")
    # Request readable thinking summaries (adaptive thinking). Set false for models that do not
    # support adaptive thinking; the model then uses its own default.
    thinking_summaries: bool = Field(default=True, validation_alias="AIGM_THINKING_SUMMARIES")
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = Field(
        default=None, validation_alias="AIGM_EFFORT"
    )
    prompt_dir: Path | None = Field(default=None, validation_alias="AIGM_PROMPT_DIR")
    save_dir: Path = Field(default=Path("./saves"), validation_alias="AIGM_SAVE_DIR")
    test_mode: bool = Field(default=False, validation_alias="AIGM_TEST_MODE")
    test_delay: float = Field(default=0.02, validation_alias="AIGM_TEST_DELAY")
    test_chunk_size: int = Field(default=4, validation_alias="AIGM_TEST_CHUNK_SIZE")
    cors_origins: list[str] = Field(
        default=["http://localhost", "http://127.0.0.1"], validation_alias="AIGM_CORS_ORIGINS"
    )
