# AIGM

An AI-powered Game Master. A FastAPI backend streams a Claude-driven narrative (with dice-rolling tool calls) over SSE, and a Textual terminal client plays it like a text adventure.

| Directory | What | Docs |
|---|---|---|
| `server/` | FastAPI backend (own uv project) | [docs/API.md](docs/API.md), [docs/BACKEND.md](docs/BACKEND.md) |
| `client/` | Textual terminal client (own uv project) | [docs/CLIENT.md](docs/CLIENT.md) |

The two projects have separate dependencies, virtualenvs, and lockfiles; they communicate only over HTTP.

## Configuration

The server reads its settings from environment variables, or from a `server/.env` file (gitignored; it is read from the directory you launch the server in, so run it from `server/`).

```sh
cp server/.env.example server/.env   # then edit it
```

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required for chat) | Your Anthropic API key |
| `AIGM_MODEL` | `claude-sonnet-5-5` | Claude model id to use |
| `AIGM_MAX_TOKENS` | `16000` | Max output tokens per response (includes thinking) |
| `AIGM_THINKING_SUMMARIES` | `true` | Ask the model for adaptive thinking with readable summaries. Set `false` for models without adaptive thinking (e.g. Haiku 4.5) |
| `AIGM_EFFORT` | (model default) | Thinking depth: `low`, `medium`, `high`, `xhigh`, `max` |
| `AIGM_STREAM_THINKING` | `true` | Forward reasoning text to the client |
| `AIGM_PROMPT_DIR` | (none) | Directory of prompt files that override or extend the packaged ones (see Prompts) |

Or inline: `ANTHROPIC_API_KEY=sk-ant-... AIGM_MODEL=claude-opus-5-5 uv run uvicorn aigm.app:app`. The active model is shown by `GET /health`. The full list of settings is in [docs/BACKEND.md](docs/BACKEND.md).

## Prompts

Prompts are Markdown files, not Python strings, so they are easy to edit and diff:

```
server/src/aigm/prompts/
  system/common/        # used in every mode
  system/session_zero/  # Session 0: building the setting and party
  system/adventure/     # the game proper
  templates/            # the campaign record shown to the model in the adventure
  tools/                # one tool description per file
```

A new game starts in **Session 0**, where the GM helps you establish the setting and the party (a higher-level or larger party means a tougher, more complex setting). When you confirm, the GM starts the adventure and the game switches to the adventure prompts for good; there is no way back to Session 0. Saves record which mode the game is in, so you can save during Session 0. Prompts for a mode are the `common` files followed by that mode's files, in filename order. Add a file to a folder to add a section (its number sets where it goes). HTML comments in prompt files are stripped, so they can hold notes. To experiment without touching the package, point `AIGM_PROMPT_DIR` at a folder with the same layout: files there replace packaged files of the same name, and extra files are added. Prompts are read at startup, so restart the server (or use `--reload`) after editing.

## Running

```sh
# server (see Configuration above)
cd server && uv sync && uv run aigm            # real Claude model (needs ANTHROPIC_API_KEY)
cd server && uv run aigm --test     # scripted replies, no LLM/API key needed (try: help, roll 2d6, markdown)

# client (default server URL http://127.0.0.1:8000; options: --url http://host:8000, --session NAME, --ascii; or AIGM_URL)
cd client && uv sync && uv run aigm-client
```

## Tests

```sh
cd server && uv run pytest
cd client && uv run pytest
```
