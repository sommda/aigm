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
| `AIGM_MAX_TOKENS` | `4096` | Max output tokens per response |
| `AIGM_THINKING_BUDGET` | `0` (off) | Extended-thinking token budget; `>0` enables it |
| `AIGM_STREAM_THINKING` | `true` | Forward reasoning text to the client |

Or inline: `ANTHROPIC_API_KEY=sk-ant-... AIGM_MODEL=claude-opus-5-5 uv run uvicorn aigm.app:app`. The active model is shown by `GET /health`. The full list of settings is in [docs/BACKEND.md](docs/BACKEND.md).

## Running

```sh
# server (see Configuration above)
cd server && uv sync && uv run uvicorn aigm.app:app --reload

# client
cd client && uv sync && uv run aigm-client
```

## Tests

```sh
cd server && uv run pytest
cd client && uv run pytest
```
