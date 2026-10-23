# AIGM

An AI-powered Game Master. A FastAPI backend streams a Claude-driven narrative (with dice-rolling tool calls) over SSE,
and a Textual terminal client plays it like a text adventure.

| Directory | What | Docs |
|---|---|---|
| `server/` | FastAPI backend (own uv project) | [docs/API.md](docs/API.md), [docs/BACKEND.md](docs/BACKEND.md), [docs/WORLD.md](docs/WORLD.md) (the persistent world: design and how it works), [docs/RULESETS.md](docs/RULESETS.md) (choosing the game's ruleset), [docs/CONTEXT.md](docs/CONTEXT.md) (the debug context viewer), [docs/HISTORY.md](docs/HISTORY.md) (shrinking the history), [docs/COMPENDIUM.md](docs/COMPENDIUM.md) (what the player has learned), [docs/NARRATION_STREAMING.md](docs/NARRATION_STREAMING.md) (spec: streaming roll narration) |
| `client/` | Textual terminal client (own uv project) | [docs/CLIENT.md](docs/CLIENT.md) |

The two projects have separate dependencies, virtualenvs, and lockfiles; they communicate only over HTTP.

## Configuration

The server reads its settings from environment variables, or from a `server/.env` file (gitignored; it is read from the
directory you launch the server in, so run it from `server/`).

```sh
cp server/.env.example server/.env   # then edit it
```

| Variable | Default | Purpose |
|---|---|---|
| `AIGM_PROVIDER` | `anthropic` | `anthropic`, or `ollama` to run the GM and the world curator on a local Ollama server (see below) |
| `ANTHROPIC_API_KEY` | (required for chat) | Your Anthropic API key (not needed with `ollama`) |
| `AIGM_MODEL` | `claude-sonnet-5-5` | Model id to use (with `ollama`, an Ollama tag such as `gemma4:12b`) |
| `AIGM_MAX_TOKENS` | `16000` | Max output tokens per response (includes thinking) |
| `AIGM_THINKING_SUMMARIES` | `true` | Ask the model for adaptive thinking with readable summaries. Set `false` for models without adaptive thinking (e.g. Haiku 4.5) |
| `AIGM_EFFORT` | (model default) | Thinking depth: `low`, `medium`, `high`, `xhigh`, `max` |
| `AIGM_STREAM_THINKING` | `true` | Forward reasoning text to the client |
| `AIGM_DEBUG` | `false` | Same as `aigm --debug`: let a client inspect the full model context (shows spoilers; see [docs/CONTEXT.md](docs/CONTEXT.md)) |
| `AIGM_HISTORY_TRIM` / `AIGM_HISTORY_DIGEST` | `true` / `true` | Old turns are trimmed (thinking dropped) or replaced by short digests in what the model is sent; saves keep everything (see [docs/HISTORY.md](docs/HISTORY.md)) |
| `AIGM_HISTORY_TRIM_KEEP` / `_STEP`, `AIGM_HISTORY_DIGEST_KEEP` / `_STEP` | `4` / `6`, `12` / `12` | How many recent turns stay untouched, and how many turns the cut moves at a time (keeps the prompt cache warm) |
| `AIGM_METRICS` | `true` | One JSON line per turn (time to first text, total time, token and cache use) in `{AIGM_SAVE_DIR}/metrics/` |
| `AIGM_ROLL_PAUSE` | `0.8` | Seconds to pause before each dice roll is shown, so the narration leading up to it can be read (`0` disables) |
| `AIGM_WORLD_MODEL` / `AIGM_WORLD_EXPAND_MODEL` | `claude-haiku-5-5` / `claude-sonnet-5-5` | Models for the background world curator: cheap for bookkeeping, stronger for inventing the world (`AIGM_WORLD_CURATOR=false` turns it off) |
| `AIGM_WORLD_DUMP` | `true` | Write a readable JSON dump of each session's world to `{AIGM_SAVE_DIR}/worlds/` (inspect a saved game with `uv run python -m aigm.world.dump NAME`) |
| `AIGM_WORLD_EVERY_PAGES` | `3` | World curator pass after this many pages of GM narration (see [docs/WORLD.md](docs/WORLD.md)) |
| `AIGM_WORLD_PAGE_CHARS` | `1800` | Characters in a "page" of narration, as the server counts it |
| `AIGM_WORLD_BRIEFING_TOKENS` | `2000` | Rough size of the world notes shown to the GM with each request (see [docs/WORLD.md](docs/WORLD.md)) |
| `AIGM_STORY_EXPAND_ENTITIES` | `3` | Story games: new entities one curator pass may add in chapters 2 and 3 (see [docs/STORY.md](docs/STORY.md)) |
| `AIGM_STORY_NUDGE_TURNS` | `12` | Story games: turns without progress before the GM is asked to offer a hook (see [docs/STORY.md](docs/STORY.md)) |
| `AIGM_PROMPT_DIR` | (none) | Directory of prompt files that override or extend the packaged ones (see Prompts) |

### Local models (Ollama)

```sh
AIGM_PROVIDER=ollama
AIGM_MODEL=gemma4:12b          # any model from `ollama list` that supports tools
```

| Variable | Default | Purpose |
|---|---|---|
| `AIGM_OLLAMA_HOST` | `http://localhost:11434` | Where Ollama is listening |
| `AIGM_OLLAMA_NUM_CTX` | `32768` | Context window requested per call. Ollama's own default is small and silently cuts a long prompt |
| `AIGM_OLLAMA_KEEP_ALIVE` | (Ollama's) | How long the model stays loaded, e.g. `1h` or `-1` |
| `AIGM_OLLAMA_THINK` | (model's) | `true`/`false` to ask for or forbid thinking; leave empty if the model has no thinking mode |

The world curator uses the same model unless `AIGM_WORLD_MODEL` / `AIGM_WORLD_EXPAND_MODEL` name another. Small local
models follow the long GM prompt and its tools less reliably than Claude does.

Or inline: `ANTHROPIC_API_KEY=sk-ant-... AIGM_MODEL=claude-opus-5-5 uv run uvicorn aigm.app:app`. The active model is
shown by `GET /health`. The full list of settings is in [docs/BACKEND.md](docs/BACKEND.md).

## Prompts

Prompts are Markdown files, not Python strings, so they are easy to edit and diff:

```
server/src/aigm/prompts/
  system/common/        # used in every mode
  system/session_zero/  # Session 0: building the setting and party
  system/adventure/     # the game proper
  templates/            # the campaign record shown to the model in the adventure
  rulesets/<id>/        # the rules and the period feel of each ruleset the player can choose (see docs/RULESETS.md)
  world/                # prompts and aspect checklists for the background world curator
  tools/                # one tool description per file
```

A new game starts in **Session 0**, where the GM helps you choose the ruleset (D&D 5.5e by default, or any older D&D or
Pathfinder edition) and establish the setting and the party (a higher-level or larger party means a tougher, more
complex setting). When you confirm, the GM starts the adventure and the game switches to the
adventure prompts for good; there is no way back to Session 0. Saves record which mode the game is in, so you can save
during Session 0. Prompts for a mode are the `common` files followed by that mode's files, in filename order. Add a file
to a folder to add a section (its number sets where it goes). HTML comments in prompt files are stripped, so they can
hold notes. To experiment without touching the package, point `AIGM_PROMPT_DIR` at a folder with the same layout: files
there replace packaged files of the same name, and extra files are added. Prompts are read at startup, so restart the
server (or use `--reload`) after editing.

## Running

```sh
# server (see Configuration above)
cd server && uv sync && uv run aigm            # real Claude model (needs ANTHROPIC_API_KEY)
cd server && uv run aigm --test     # scripted replies, no LLM/API key needed (try: help, roll 2d6, markdown)
cd server && uv run aigm --debug    # also allow clients to inspect the model's context (shows spoilers)

# client (default server URL http://127.0.0.1:8000)
# options: --url http://host:8000, --session NAME, --ascii, --no-mouse (select and copy text); or AIGM_URL
cd client && uv sync && uv run aigm-client
```

## Tests

```sh
cd server && uv run pytest
cd client && uv run pytest
```
