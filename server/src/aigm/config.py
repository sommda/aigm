from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    model: str = Field(default="claude-sonnet-5-5", validation_alias="AIGM_MODEL")
    max_tokens: int = Field(default=4096, validation_alias="AIGM_MAX_TOKENS")
    max_tool_iters: int = Field(default=8, validation_alias="AIGM_MAX_TOOL_ITERS")
    stream_thinking: bool = Field(default=True, validation_alias="AIGM_STREAM_THINKING")
    thinking_budget: int = Field(default=0, validation_alias="AIGM_THINKING_BUDGET")
    save_dir: Path = Field(default=Path("./saves"), validation_alias="AIGM_SAVE_DIR")
    cors_origins: list[str] = Field(
        default=["http://localhost", "http://127.0.0.1"], validation_alias="AIGM_CORS_ORIGINS"
    )
