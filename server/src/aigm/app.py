from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aigm.config import Settings
from aigm.errors import install_error_handlers
from aigm.llm.anthropic_client import AnthropicLLM
from aigm.llm.base import LLMClient
from aigm.llm.scripted import ScriptedLLM
from aigm.game import Game
from aigm.prompts import PromptLibrary
from aigm.routes import chat, health, history
from aigm.session.persistence import HistoryRepository
from aigm.session.store import SessionStore

TEST_MODEL_NAME = "scripted-test"


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="AIGM", version="0.1.0")
    app.state.settings = settings
    app.state.sessions = SessionStore()
    app.state.repo = HistoryRepository(settings.save_dir)
    app.state.game = Game(PromptLibrary(settings.prompt_dir))  # prompts are read at startup; restart to pick up edits
    if llm is None:
        if settings.test_mode:
            llm = ScriptedLLM(delay=settings.test_delay, chunk_size=settings.test_chunk_size)
        else:
            llm = AnthropicLLM(
                api_key=settings.anthropic_api_key,
                model=settings.model,
                max_tokens=settings.max_tokens,
                thinking_summaries=settings.thinking_summaries,
                effort=settings.effort,
            )
    app.state.llm = llm
    app.state.model_name = TEST_MODEL_NAME if settings.test_mode else settings.model

    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(history.router)
    return app


app = create_app()
