from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aigm.config import Settings
from aigm.errors import install_error_handlers
from aigm.llm.anthropic_client import AnthropicLLM
from aigm.llm.base import LLMClient
from aigm.llm.ollama_client import OllamaLLM
from aigm.llm.scripted import ScriptedLLM
from aigm.game import Game
from aigm.images import Images, make_images
from aigm.metrics import MetricsLog
from aigm.portraits import ImageStore, PortraitService
from aigm.prompts import PromptLibrary
from aigm.routes import characters, chat, compendium, debug, health, history, portraits, status
from aigm.session.persistence import HistoryRepository
from aigm.session.store import SessionStore
from aigm.world.anthropic_curator import AnthropicCurator
from aigm.world.ollama_curator import OllamaCurator
from aigm.world.dump import WorldDumper
from aigm.world.passes import PassConfig
from aigm.world.scripted import ScriptedCurator
from aigm.world.service import CuratorService

TEST_MODEL_NAME = "scripted-test"


def create_app(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    curator: CuratorService | None = None,
    images: Images | None = None,
) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="AIGM", version="0.1.0")
    app.state.settings = settings
    app.state.sessions = SessionStore()
    app.state.repo = HistoryRepository(settings.save_dir)
    generator = images if images is not None else make_images(settings)
    # prompts are read at startup; restart to pick up edits
    app.state.game = Game(
        PromptLibrary(settings.prompt_dir), settings.world_briefing_tokens, settings.history_policy,
        settings.story_nudge_turns, art_styles=generator is not None,
    )  # fmt: skip
    if llm is None:
        if settings.test_mode:
            llm = ScriptedLLM(delay=settings.test_delay, chunk_size=settings.test_chunk_size)
        elif settings.provider == "ollama":
            llm = OllamaLLM(
                model=settings.model,
                host=settings.ollama_host,
                max_tokens=settings.max_tokens,
                num_ctx=settings.ollama_num_ctx,
                keep_alive=settings.ollama_keep_alive,
                think=settings.ollama_think,
            )
        else:
            llm = AnthropicLLM(
                api_key=settings.anthropic_api_key,
                model=settings.model,
                max_tokens=settings.max_tokens,
                thinking_summaries=settings.thinking_summaries,
                effort=settings.effort,
            )
    app.state.llm = llm
    app.state.metrics = MetricsLog(settings.save_dir / "metrics" if settings.metrics else None)
    app.state.dumper = WorldDumper(settings.save_dir / "worlds", settings.world_dump)
    app.state.curator = curator if curator is not None else _make_curator(settings, app.state.game.prompts)
    app.state.image_store = ImageStore(settings.save_dir / "images")
    app.state.portraits = (
        PortraitService(
            generator, app.state.image_store, settings.image_size, settings.image_quality, settings.place_image_size
        )
        if generator
        else None
    )
    if app.state.portraits is not None and app.state.curator is not None:
        wrote = app.state.curator.curator
        app.state.portraits.describes = {
            "npc": getattr(wrote, "look", None) is not None, "location": getattr(wrote, "place_look", None) is not None
        }
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
    app.include_router(compendium.router)
    app.include_router(status.router)
    app.include_router(characters.router)
    app.include_router(portraits.router)
    if settings.debug:  # without it the path does not exist at all
        app.include_router(debug.router)
    return app


def _make_curator(settings: Settings, prompts: PromptLibrary) -> CuratorService | None:
    """The background world curator: scripted in test mode, model-driven otherwise (or off)."""
    timing = {
        "every_pages": settings.world_every_pages,
        "page_chars": settings.world_page_chars,
        "config": PassConfig(digests=settings.history_digest, story_entities=settings.story_expand_entities),
    }
    if settings.test_mode:
        return CuratorService(ScriptedCurator(), **timing)
    if not settings.world_curator:
        return None
    if settings.provider == "ollama":
        return CuratorService(
            OllamaCurator(
                prompts=prompts,
                model=settings.curator_model,
                expand_model=settings.curator_expand_model,
                host=settings.ollama_host,
                num_ctx=settings.ollama_num_ctx,
                keep_alive=settings.ollama_keep_alive,
            ),
            **timing,
        )
    return CuratorService(
        AnthropicCurator(
            api_key=settings.anthropic_api_key,
            prompts=prompts,
            model=settings.world_model,
            expand_model=settings.world_expand_model,
            effort=settings.world_effort,
            expand_effort=settings.world_expand_effort,
        ),
        **timing,
    )


app = create_app()
