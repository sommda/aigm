# AIGM Backend Design

Implementation plan for the v0.1 backend described in [API.md](API.md). No code yet; this document defines structure,
responsibilities, and key decisions.

## Goals / Non-goals

**Goals (v0.1)**
- FastAPI server with `POST /chat` streaming SSE (markdown text + custom events).
- Forwards conversation to a Claude model, streaming tokens through.
- Server-side tool loop with one tool, `roll_dice`, backed by the `d20` library.
- In-memory per-session chat history plus named saved histories (list / show / save / restore / delete).

**Non-goals (later)**
- History truncation, summarization, long-term memory.
- Auth, multi-user isolation, database storage.
- Game state (characters, maps, rules), prompt caching tuning, additional tools.

## Stack

- Python 3.13, managed with `uv`. The server is its own uv project in `server/`, independent of the client in `client/`
  (separate `pyproject.toml`, `.venv`, and `uv.lock`).
- Dependencies: `fastapi`, `uvicorn[standard]`, `anthropic` (async SDK), `d20`, `pydantic` (via FastAPI),
  `pydantic-settings`. SSE is produced with `fastapi.responses.StreamingResponse` (or `sse-starlette` if its disconnect
  handling proves easier; start without it).
- Dev: `pytest`, `pytest-asyncio`, `httpx` (ASGI test client).
- Run (from `server/`): `uv run aigm` (or `uv run aigm --test`, see "Test mode"), or directly
  `uv run uvicorn aigm.app:app --reload`.

## Project Layout

Convert the placeholder `main.py` into a package:

```
server/              # (inside the repo root; docs live in ../docs)
  pyproject.toml
  src/aigm/
    __init__.py
    app.py            # FastAPI app factory, router wiring, lifespan
    history.py        # the reduced history the model is shown: trimming and digests (section 11)
    metrics.py        # per-turn measurements: timings, token use, request sizes
    config.py         # Settings (env-driven)
    models.py         # Pydantic request/response models, SSE event models
    sse.py            # SSE event encoding helpers
    routes/
      chat.py         # POST /chat, POST /chat/new, GET /chat/history
      history.py      # /history/* endpoints (saved histories) and GET /chat/history
      health.py       # GET /health
      debug.py        # GET /debug/context (registered only with --debug; builds on context_view.py)
    llm/
      client.py       # Thin wrapper around anthropic.AsyncAnthropic
      loop.py         # Streaming + tool-use loop (the core)
    tools/
      __init__.py     # Registry: name -> (schema, handler)
      roll_dice.py    # roll_dice tool
      world.py        # recall / establish / set_scene (the world tools, see WORLD.md)
    session/
      store.py        # In-memory SessionStore + per-session lock
      persistence.py  # Save/restore snapshots to disk
    prompts/
  tests/
    test_roll_dice.py
    test_sse.py
    test_history_api.py
    test_chat_loop.py  # uses a fake LLM client
  saves/               # runtime snapshots (gitignored; server/saves/)
```

## Configuration (`config.py`)

Environment variables (via `pydantic-settings`, optional `.env`):

| Var                    | Default               | Purpose                              |
|------------------------|-----------------------|--------------------------------------|
| `ANTHROPIC_API_KEY`    | (required)            | API credential                       |
| `AIGM_MODEL`           | `claude-sonnet-5-5`   | Model id                             |
| `AIGM_MAX_TOKENS`      | `16000`               | Per-response output cap (includes thinking)  |
| `AIGM_MAX_TOOL_ITERS`  | `8`                   | Tool-loop safety limit per turn      |
| `AIGM_STREAM_THINKING` | `true`               | Forward reasoning text as `thinking` `delta` events; `false` sends only `start`/`end` |
| `AIGM_DEBUG`           | `false`              | Debug mode (`aigm --debug`): registers `GET /debug/context` and reports `debug: true` in `/health` (see CONTEXT.md) |
| `AIGM_HISTORY_TRIM` / `AIGM_HISTORY_DIGEST` | `true` / `true` | Shrink the history the model sees (see section 11); `false` for both sends everything |
| `AIGM_HISTORY_TRIM_KEEP` / `_STEP` | `4` / `6` | Newest turns never trimmed; the trim cut moves this many turns at a time |
| `AIGM_HISTORY_DIGEST_KEEP` / `_STEP` | `12` / `12` | Newest turns always shown in full; the digest cut moves this many turns at a time |
| `AIGM_METRICS`         | `true`               | Append one JSON line per turn (timings, token use, request sizes) to `{save_dir}/metrics/{session}.jsonl` |
| `AIGM_ROLL_PAUSE`      | `0.8`                | Seconds to wait before each `dice_roll` event is sent, after the narration that precedes it (`0` disables) |
| `AIGM_THINKING_SUMMARIES` | `true`            | Request adaptive thinking with summaries (`false` for models without adaptive thinking) |
| `AIGM_EFFORT`          | (model default)       | `low` to `max`; maps to `output_config.effort` |
| `AIGM_WORLD_DUMP`      | `true`              | Write a readable JSON dump of each session's world to `{save_dir}/worlds/` for debugging |
| `AIGM_WORLD_CURATOR`   | `true`              | Run the background world curator (model-driven; scripted in `--test` mode) |
| `AIGM_WORLD_MODEL`     | `claude-haiku-5-5`  | Model for curator extraction, reconciliation and the independence check |
| `AIGM_WORLD_EXPAND_MODEL` | `claude-sonnet-5-5` | Model for generating new parts of the world |
| `AIGM_WORLD_EFFORT` / `AIGM_WORLD_EXPAND_EFFORT` | `low` / `medium` | Thinking effort for those two groups |
| `AIGM_WORLD_EVERY_PAGES` | `3`             | Run a world-curator pass after this many pages of unprocessed GM narration |
| `AIGM_WORLD_PAGE_CHARS` | `1800`           | Characters in a "page" of narration, as the server counts it |
| `AIGM_WORLD_BRIEFING_TOKENS` | `2000`          | Rough size of the world notes shown to the GM with each request |
| `AIGM_PROMPT_DIR`      | (none)                | Directory overriding/extending the packaged prompt files |
| `AIGM_SAVE_DIR`        | `./saves`             | Snapshot directory                   |
| `AIGM_CORS_ORIGINS`    | `http://localhost:*`  | Allowed front-end origins            |

## Core Components

### 1. Data model (`models.py`)

- `ChatRequest { message: str, session_id: str = "default" }` with validators (non-empty, session-id regex).
- `SaveRequest { name: str | None }`.
- SSE event models: `MessageStart`, `Thinking`, `TextDelta`, `ToolCall`, `DiceRoll`, `MessageEnd`, `ErrorEvent`, all
  subclasses of a base with an `event: ClassVar[str]` name, so serialization is uniform.
- History is stored as raw Anthropic message dicts (`{"role", "content": [blocks]}`), not custom types, so it passes
  straight back to the API and serializes trivially to JSON.

### 2. SSE encoding (`sse.py`)

- `encode(event) -> str`: renders `event: <name>\ndata: <json>\n\n`; JSON is single-line (no embedded newlines).
- Response headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`,
  `Connection: keep-alive`.
- Optional periodic comment heartbeat (`: ping\n\n`) during long tool/LLM waits.

### 3. Session store (`session/store.py`)

- `Session { id, messages: list[dict], state: GameState, busy: bool }`, where `GameState { phase, campaign }` lives in
  `session/state.py` (`Phase`: `session_zero` | `adventure`; new sessions start in `session_zero`) with `try_begin()` /
  `end()`. (A plain flag rather than an `asyncio.Lock`: everything runs on one event loop, so check-and-set is atomic,
  and the route can reject with 409 without awaiting.)
- `SessionStore`: `get_or_create(id)`, `replace_messages(id, msgs)` (used by restore and `/chat/new`, which replaces
  with `[]`). Backed by a plain dict; single process only in v0.1.
- Concurrency rule: `/chat` sets `busy` for the whole streamed turn; `/chat`, `/chat/new`, save, and restore return
  `409` if the session is busy. The flag is released from the stream generator's `finally` and again (idempotently) from
  a response background task, so it is cleared even if the client disconnects before the generator starts.

### 4. Persistence (`session/persistence.py`)

A saved history is a "named history", like a saved game file. `HistoryRepository` exposes:

| Method                          | Backs endpoint                      | Notes                                              |
|---------------------------------|-------------------------------------|----------------------------------------------------|
| `list() -> list[HistoryInfo]`   | `GET /history`                      | Reads each file's metadata, newest first           |
| `info(name, include_messages)`  | `GET /history/{name}`               | Never touches a live session                       |
| `save(name, messages, state, model, overwrite)` | `PUT /history/{name}/save` | Raises `AlreadyExists` if the file exists and `overwrite` is false; returns `overwritten` flag |
| `load(name) -> (messages, state, info)` | `POST /history/{name}/restore`      | Validates fully before returning                   |
| `delete(name)`                  | `DELETE /history/{name}`            | Single file only; no delete-all                    |

- Snapshot file: `{AIGM_SAVE_DIR}/{name}.json`:
  ```json
  { "version": 3, "name": "...", "saved_at": "...", "model": "...", "phase": "adventure",
    "campaign": {...}, "world": {...}, "messages": [...] }
  ```
  Files are written pretty-printed (`indent=2`), never on one line. Version 1 files (messages only) load as `adventure`
  with no campaign record; version 2 files (no `world`) load with an empty world. Restore also validates the state
  (known phase, `campaign` an object or null, none in `session_zero`) and the world (ids unique, every reference
  resolves, parent chains end, names unique, `next_id` above every id, supersession consistent). A `session_zero` save
  must have an empty world. Content caps are not re-checked on load, so a save still loads if the caps are tightened
  later.

- `aigm/world/` also holds the curator pipeline: `curator.py` (the `Curator` interface and its request/answer types),
  `passes.py` (one pass, the frontier, the precedence and connectivity rules, narration measuring), `ops.py` (replayable
  changes), `service.py` (background scheduling), `scripted.py` (the deterministic test-mode curator),
  `anthropic_curator.py` (the model-backed curator: schemas, calls, defensive parsing), `render.py` (request to prompt
  text), `independence.py` (fact-text rules), `sample.py` (prints a grown world), `dump.py` (the readable world dump and
  its command-line helper; the server rewrites `{save_dir}/worlds/{session}.world.json` after each turn that changed the
  world). Curator prompts are in `prompts/world/`.
- The world model lives in `aigm/world/` (`model.py`: `World`, `Entity`, `Fact`, `WorldTime`, `Scene`, with the indexes
  and validation; `text.py`: name normalization and tokenizing). It is pure data with no I/O. See [WORLD.md](WORLD.md).
- Write atomically (temp file + `os.replace`). Names are validated by regex, which also prevents path traversal.
- Restore validates `version` and message structure (role in {user, assistant}, content is list of blocks, and
  tool_use/tool_result pairing is intact) and raises a typed error mapped to `422`.
- `list()` and `info()` must not need to parse huge message arrays unnecessarily in future; v0.1 just loads the JSON,
  but `message_count`, `saved_at`, and `model` live at the top level so a sidecar/index could be added later.
- Restore ordering: validate the snapshot **first**, then (holding the session lock) swap the messages in. A failed
  restore must leave live history unchanged.
- File I/O is wrapped in `asyncio.to_thread`.

### 5. LLM client (`llm/client.py`)

- Single `AsyncAnthropic` instance created in app lifespan and kept on `app.state`.
- Defined as a small protocol (`stream(messages, system, tools) -> async context manager`) so tests can inject a fake
  that replays scripted events.

### 6. Streaming tool loop (`llm/loop.py`) — the heart of the system

`async def run_turn(session, user_text, llm, game, ...) -> AsyncIterator[SSEEvent]`

`game` (`game.py`) supplies the system prompt and tool list for a given `GameState` and dispatches tool calls. The loop
works on a staged copy of the state, and asks `game` for the system prompt and tools on **every** request, so a tool
that changes the phase (`begin_adventure`) takes effect for the very next request in the same turn: the model that
called it continues, now seeing the adventure prompt, the campaign record and no `begin_adventure` tool. When the phase
changes during tool handling, the loop replaces the staged history with `game.history_after_begin(state)` (a system
note, one GM entry holding the campaign record, a begin cue) instead of appending the tool result, so the adventure's
first request never sees Session 0. Messages and state are committed together on success; on failure both are discarded.
When the phase changed and a curator is configured, the loop then builds the world before the next request:
`_seed_world` runs `curator.seed(...)` (a bootstrap pass, WORLD.md 4.6) as a task, yields `status` events from its
progress messages, applies the resulting ops to the working state, and yields a final `status` with `done: true`; a
failure becomes a retryable `upstream_error` and rolls the whole turn back, and closing the stream cancels the work.
`phase_change` is yielded at commit time, just before `message_end`, so it is never announced for a turn that is then
rolled back.

Algorithm:

1. Append `{"role":"user","content":[{"type":"text","text":user_text}]}` to `session.messages`. Yield `message_start`.
2. Loop up to `MAX_TOOL_ITERS`:
   1. Open `llm.stream(model, system, messages, tools, max_tokens)`.
   2. For each SDK stream event: on a `thinking` content block start, yield `thinking(start)` and record the time; on
      that block's stop, yield `thinking(end, duration_ms)`; each thinking delta is forwarded as `thinking(delta)` when
      `AIGM_STREAM_THINKING` is true (otherwise dropped); redacted thinking blocks emit only `start`/`end`. For each
      text delta, yield a `text` event immediately. If the stream errors or is cancelled mid-block, no `end` is emitted
      (the terminal `error` event, or the disconnect, ends the stream).
   3. When the stream completes, get the final message. Append it to `session.messages` as an assistant message (all
      blocks, including `tool_use` and, when thinking is enabled, `thinking` blocks with their signatures — the API
      requires thinking blocks to be passed back unmodified alongside tool results within a turn, so never strip or
      reorder them).
   4. If `stop_reason != "tool_use"`: yield `message_end` (with accumulated usage and the turn's `metrics`, which are
      also logged and appended to the session's metrics file) and return.
   5. Otherwise, for each `tool_use` block, in order:
      - yield `tool_call`;
      - dispatch to the tool registry (handler runs in `to_thread` if blocking);
      - build a `tool_result` block (`is_error` set on failure);
      - if the tool is `roll_dice` and succeeded, yield `dice_roll`.
   6. Append one user message containing all `tool_result` blocks, then continue the loop.
3. If the iteration cap is hit: yield `error(tool_loop_limit)`.

Error handling:
- Anthropic exceptions → `error(upstream_error, retryable=<bool>)`. History rollback rule: on any failure, truncate
  `session.messages` back to the state at turn start *plus* the user message? Decision for v0.1: **roll back to the
  state before the turn entirely** so a failed turn leaves no dangling `tool_use` without `tool_result` (which the API
  rejects). The client can simply resend.
- Client disconnect (`asyncio.CancelledError`): same rollback, in a `finally` block, then re-raise.
- Tool handler exceptions are caught and converted to `is_error` tool results; they never abort the turn.

Mid-turn history consistency: messages are staged in a local list during the turn and committed to the session only on
successful completion (or equivalently, rolled back on failure). This makes the rollback rule trivial.

### 7. Tools (`tools/`)

Registry shape:

```
Tool = (schema: dict, handler: Callable[[tool_use_id, dict, GameState], ToolOutcome], phases: set[Phase])
ToolOutcome = { content: str, is_error: bool, event: SSEEvent | None }
```

`phases` says where a tool is offered (`roll_dice` everywhere; `set_ruleset` and `begin_adventure` only in
`session_zero`; `recall`,
`establish` and `set_scene` only in `adventure`); dispatching a tool outside its phases is an unknown-tool error. A
handler may change the `GameState` it is given (the turn's working copy).

The optional `event` lets a tool emit a custom front-end event (e.g. `dice_roll`) without the loop knowing tool
specifics. The loop just yields `outcome.event` if present — adding future tools with custom events requires no loop
change.

**World tools** (`adventure` only; `tools/world.py`): `recall` reads the knowledge base, `establish` and `set_scene`
change it, all on the turn's working copy of the state, so a failed turn records nothing. `establish` and `set_scene`
build a copy of the world and swap it in only if every part is accepted. `GameState.turn` (not saved) is set by the loop
to the number of player messages so far, and stamps the facts. Details in [WORLD.md](WORLD.md) section 6.

**`begin_adventure`** (`session_zero` only): the model must put its whole summary of Session 0 into the arguments,
because everything else is discarded on success. The handler therefore validates sufficiency, collecting *all* problems
into one error result so the model can fix them in a single retry: `confirmed is true`; `setting` >= 300 chars;
`opening` >= 100 chars; `level` 1-20; `party` 1-6 members, each a player character with a unique name and a `sheet` >=
150 chars (the party is the player's whole party: there is no main character and no GM-run party members; NPCs live in
the setting); optional `gm_notes`; total <= 30,000 chars. Thresholds are constants at the top of
`tools/begin_adventure.py`; they are only a floor against empty or hand-wavy summaries, not a quality check. On success
it sets `phase = adventure` and stores the fields as `campaign`; the loop then rewrites the history (above). Nothing on
the server verifies the player's confirmation beyond the `confirmed` flag; that rule lives in the Session 0 prompt.

**`roll_dice`**
- Input: `{"expression": str, "narration": str}`.
- Validate: `narration` is a string of at least 10 characters (otherwise the call is refused, nothing is rolled and the
  error asks the model to call again with one); `expression` is a string, non-empty, ≤ 200 chars.
- The outcome carries the stripped narration as `say`. The loop sends it as a `text` delta (starting a new paragraph if
  text was already shown, and ending with a blank line) right before the `dice_roll` event, and before the roll pause.
  This guarantees the player reads what the roll is for. The narration is the model's own words, written as part of
  the tool call, so it stays in history; the curator's transcript includes it as GM text.
- Call `d20.roll(expression)`; build content from `str(result)` (the same markdown string as the event's `result`),
  total from `result.total`.
- Build the structured `dice_roll` payload from the `RollResult`: `crit` from `result.crit` (`CritType`: NONE/CRIT/FAIL
  → `"none"`/`"crit"`/`"fail"`), `comment` from `result.comment`, then walk the AST (`result.expr`, recursing via
  `.children`) collecting every `d20.Dice` node. For each: `count=num`, `sides=size`, `total`, `annotation`, and
  `notation` rebuilt from `num`, `size` and `operations` (d20's `str(Dice)` is a debug repr, not the source text; each
  `SetOperator` has `op` and `sels` with `cat`/`num`, e.g. `k`+`h`+`3` → `kh3`); for each `Die` in `dice.values`:
  `kept=die.kept`, `values=[v.total for v in die.values]`, `value=values[-1]`. Note d20 attaches `[annotation]` text to
  the adjacent `Literal` rather than the `Dice`, so `annotation` is often null. Keep this in one pure function
  (`build_roll_payload`) so it can be unit tested against fixed expressions without randomness assumptions (assert
  structure and invariants, e.g. sum of kept dice equals term total).
- Only `result` (the string) goes back to the model; the structured payload is only in the SSE event.
- Catch `d20.RollError` (and its subclasses `RollSyntaxError`, `TooManyRolls`, `RollValueError`, etc.) plus generic
  `Exception` → `is_error` outcome with the message format in API.md.
- Emits `DiceRoll` event (with the structured payload) on success.
- Pure and synchronous; cheap enough to run inline, but dispatch is uniform via the registry.

### 8. Prompts (`prompts/`)

All prompt text lives in Markdown files, never in Python. `aigm.prompts.PromptLibrary` loads them:

```
prompts/system/common/      01_role 02_rules 03_dice 04_formatting     # every phase
prompts/system/session_zero/ 01_mode 01a_ruleset 02_party 03_scaling 04_wrapup  # Session 0 only
prompts/rulesets/<id>/       01_rules.md 02_era.md                       # the chosen ruleset, see RULESETS.md
prompts/system/adventure/    01_role 02_rules 03_style 04_world          # Adventure only
prompts/templates/           campaign_record.md party_member.md gm_notes.md session_zero_done.md begin_cue.md
prompts/tools/               roll_dice.md set_ruleset.md begin_adventure.md recall.md establish.md set_scene.md
```

- A phase's system prompt is the `common` files followed by that phase's files, each in filename order. Session 0
  therefore never carries combat or narration rules, and the adventure never carries party-building rules. Add a section
  by adding a file; its filename number decides where it lands. HTML comments are stripped, so files can carry authoring
  notes.
- The campaign record (setting, party, opening) is **not** in the system prompt. It is the first GM entry in the
  adventure's history, rendered from the tool arguments with `templates/campaign_record.md` and `party_member.md` (see
  the loop). Only the private `gm_notes` are added to the adventure system prompt, as a `## GM notes (private)` section
  from `templates/gm_notes.md`; saves with no notes omit it.
- `AIGM_PROMPT_DIR` points at an override directory with the same layout: same-named files replace packaged ones, new
  files are added. This is the intended way to iterate on prompts without editing the package.
- `Game` (`game.py`) renders both phases' prompts and tool lists once at startup (`app.state.game`); restart or use
  `--reload` to pick up edits. The system prompt goes in the API's `system` parameter and is never stored in history.
- Each request is built by `game.describe(state, messages, user_text)`, which returns a `RequestDescription`: the system
  prompt as ordered `PromptPart`s (each with its source file, e.g. `system/common/01_role.md`), the tools, the stored
  history and the world briefing. `run_turn` sends `.system`, `.tools` and `.messages` (the history with the briefing
  and its cache breakpoint added), so anything that shows the request reads the same object that is sent. See
  [CONTEXT.md](CONTEXT.md).
- Session 0 content: welcome and open questions; choosing the ruleset (`01a_ruleset`); party size, starting level, and
  building characters the way the chosen ruleset does; a
  table matching the scale and danger of the setting to party level and the complexity of the adventure to party size;
  and how to wrap up (summarize, ask the player explicitly, warn there is no way back, and only then call
  `begin_adventure`). Adventure content: the mode statement, the digital adaptations, and narration style. The rules
  themselves and the period feel are in the chosen ruleset's files (RULESETS.md), placed between the common and the mode
  files.
- Switching prompts changes the cached prefix once, at the moment the adventure begins, and the history is replaced at
  the same moment, so there is no reuse to lose. Afterwards the adventure prompt and history prefix are stable. Because
  Session 0 is gone, the adventure model never sees a `begin_adventure` call that is no longer in its tool list. (The
  synthetic `[System: ...]` user messages keep roles alternating; they are the only user-role text the player did not
  type.) Nothing here has been run against the live API yet.

### 9. Routes

- `POST /chat` → validate, get session, try-acquire lock (409 on fail), return `StreamingResponse(generator)` where the
  generator wraps `run_turn`, encodes events, and releases the lock in `finally`.
- `POST /chat/new`, `GET /chat/history`, `GET /history`, `GET /history/{name}`, `PUT /history/{name}/save`,
  `POST /history/{name}/restore`, `DELETE /history/{name}`, `GET /health` per API.md. `{name}` is validated by a shared
  path-param dependency (regex) so every route rejects bad names with `400`. Handlers are thin; logic lives in the
  store/persistence modules.
- Exception handlers map domain errors (`NotFound`, `Conflict`, `InvalidName`, `CorruptSave`) to the JSON error format.

### 10. App wiring (`app.py`)

- `create_app()` factory; lifespan creates the Anthropic client, `SessionStore`, tool registry, and builds the `Game`
  (prompts and tools per phase), placing them on `app.state` (accessed via FastAPI dependencies for easy test override).
- CORS middleware for the front-end origin(s).
- Structured logging (request id, session id, tool calls, token usage); never log API keys, and log message bodies only
  at DEBUG.

### 11. History reduction (`history.py`)

Design and reasoning are in [HISTORY.md](HISTORY.md). `Game.describe` passes the stored messages through
`reduce_history`, so the request (and the context viewer, which reads the same description) shows the reduced view;
the stored messages, the saves and `/chat/history` are never changed. The briefing is still chosen from the full
history.

- A **turn** starts at each player message and runs to the next one, so a turn includes the tool-call messages in it.
  The first turn (the campaign record after Session 0) is always shown in full.
- **Cuts.** `cut(turns, keep, step) = max(0, (turns - keep) // step * step)`: it counts the turns that have aged out,
  moves only every `step` turns, and always leaves at least `keep` turns newer than it. Only the number of turns
  matters, so between moves the start of the request is byte-identical and the prompt cache keeps hitting; a move
  rewrites the cache once.
- **Digest cut** (`AIGM_HISTORY_DIGEST_KEEP`/`_STEP`): turns before it are replaced by their digests (world.digests,
  written by the curator, see WORLD.md 4.7), listed in one `<story_so_far>` block at the front of the oldest turn
  that is still shown in full (so the roles keep alternating). The cut stops at the first turn without a digest, so
  a lagging curator only delays the reduction.
- **Trim cut** (`AIGM_HISTORY_TRIM_KEEP`/`_STEP`): turns between the digest cut and this one lose their `thinking`
  blocks. Tool calls and results stay exactly as stored: an earlier version folded them into text notes such as
  `(Rolled 1d20+5: ...)`, and the model then began writing rolls as text instead of calling the tool. The turn in
  progress is never touched, because thinking must go back unmodified while its tool calls are answered.
- With both switches off the stored list is returned as it is.

## LLM abstraction

The tool loop does not talk to the Anthropic SDK directly. `llm/base.py` defines a small `LLMClient` protocol whose
`stream(system, messages, tools)` yields normalized events: `ThinkingStarted`, `ThinkingChunk`, `ThinkingStopped`,
`TextChunk`, and a final `Completed(content, stop_reason, usage)` carrying the assistant message as Anthropic-format
blocks (exactly what is stored in history). Implementations:

- `llm/scripted.py`: `ScriptedLLM`, used by `--test` mode (below).
- `llm/anthropic_client.py`: `AnthropicLLM`, the real client. It calls `messages.stream()` on `AsyncAnthropic` and
  translates SDK events: a `thinking` content block becomes `ThinkingStarted` / `ThinkingChunk`s / `ThinkingStopped` (an
  omitted-thinking block yields start/stop with no chunks); `text_delta`s become `TextChunk`s; and the SDK's accumulated
  final message becomes `Completed`, with content stored verbatim (`model_dump`), so thinking blocks keep their
  signatures and tool_use blocks keep their parsed input.
  - Requests send: `system` (the assembled prompt), the tool schemas, prompt caching of the growing prefix (a top-level
    `cache_control`, or, when the request carries world notes, an explicit breakpoint on the block before them, see
    WORLD.md 6.1), `thinking={"type": "adaptive", "display": "summarized"}` unless `AIGM_THINKING_SUMMARIES=false`, and
    `output_config.effort` if `AIGM_EFFORT` is set. No sampling parameters and no forced `tool_choice` (both are
    rejected by current models). Default model: `claude-sonnet-5-5`.
  - `stop_reason: "refusal"` becomes a non-retryable `LLMError`; SDK exceptions map to `LLMError` with `retryable` set
    for rate limits, connection failures and 5xx. Missing credentials give a clear "set ANTHROPIC_API_KEY" error. The
    SDK client is created lazily, so the server starts (and `/health` works) without a key.
  - The loop also rejects malformed completions before they reach history: an empty response, or a `tool_use` block with
    a stop reason other than `tool_use` (e.g. `max_tokens` mid tool call), both become retryable errors.
  - Not implemented (yet): server-side refusal `fallbacks` (a beta that changes the request path),
    `eager_input_streaming` for tool inputs (dice expressions are tiny), and the 1h cache TTL.

## Test mode (`--test`)

`uv run aigm --test` (equivalently `AIGM_TEST_MODE=true`) swaps the LLM for `ScriptedLLM`. Everything else is the real
server: `/chat` SSE framing, the tool loop (with the **real** `roll_dice`), sessions, history, save/restore.
`GET /health` reports `"model": "scripted-test"`. No API key or network is needed.

The user's chat message selects a canned plan (a list of `Think`/`Say`/`UseTool`/`Fail`/`Pause` steps; `plan_for()` is
pure data and easy to extend). Text is streamed in small chunks (default 4 characters, `AIGM_TEST_CHUNK_SIZE`;
`AIGM_TEST_DELAY` seconds between chunks, default 0.02) so partially received markdown actually occurs. After tool
results the scripted model narrates them, so the full request -> tool -> follow-up loop is exercised.

| Message | Behavior |
|---|---|
| `help` | List the commands (markdown) |
| `roll <expr>` | A real `roll_dice` call with a narration (`roll 4d6kh3+2 # strength`; default `1d20`), then narration of the result |
| `multiroll` | Two `roll_dice` calls in one response |
| `badroll [expr]` | A malformed roll (default `2x20`): tool error is returned to the model, no `dice_roll` event |
| `markdown` | Sampler of every markup form below |
| `bold` `italic` `strike` `code` `codeblock` `list` `numbered` `heading` `quote` `table` `link` | One markup form each |
| `think [n]` | Thinking phase (start, deltas, end) then an answer; history gets a `thinking` block |
| `long [n]` | *n* paragraphs (for testing paging) |
| `slow` | 2 second pause, then a reply |
| `error` | Some text, then a simulated upstream failure (`error` event, `retryable: true`; turn rolled back) |
| `loop` | Endless tool calls, ending in `tool_loop_limit` |
| `echo <text>` | Streams your text back (any markdown) |
| anything else | Echoed back with a hint to type `help` |

## Testing Strategy

- **roll_dice**: valid expressions (`1d20+5`, `4d6kh3`, advantage), malformed (`2x20`, empty, too long, absurd roll
  counts) → expected content / `is_error`.
- **SSE encoding**: golden-string tests for each event type.
- **Loop and chat route** (implemented; `tests/test_chat_api.py` drives the real app in test mode): scripted LLM
  producing (a) plain text, (b) text → tool_use → text, (c) multiple tool calls in one response, (d) tool error then
  retry, (e) infinite tool_use (hits cap), (f) upstream exception. Assert event order and final history, including
  rollback behavior.
- **History API**: save → mutate → restore round-trip; list ordering; info without loading (live history untouched);
  `overwrite=true` required to replace an existing save (409 `already_exists` otherwise, existing file untouched);
  delete one leaves others; failed restore leaves live history intact; 404/409/422 cases; path-traversal names rejected;
  atomic write.
- **Chat route**: ASGI client reads the SSE stream end to end; concurrent request returns 409.
- No live API calls in the default test run; one optional `@pytest.mark.live` smoke test gated on `ANTHROPIC_API_KEY`.

## Build Order

1. Project scaffolding: package layout, dependencies, config, `/health`.
2. `roll_dice` tool + tests (no network needed).
3. Session store + persistence + history endpoints + tests.
4. SSE encoding + event models.
5. LLM client wrapper + fake + streaming tool loop + tests.
6. `/chat` route and wiring; manual end-to-end with `curl -N`.
7. System prompt iteration; live smoke test.

## Known Limitations / Future Work

- The stored history grows without bound (it is the transcript and the save). What the model is sent does not: see
  section 11.
- Single process: the in-memory store and locks don't survive restarts or scale across workers; saves are manual.
- Rolled-back turns lose partial text a client already displayed; a future version might persist partial turns with
  synthetic tool results.
- Prompt caching (cache breakpoint on system prompt + tools) is a cheap later optimization once history is long.
- Thinking text is streamed to the client in `thinking` deltas but only the `thinking` blocks in history are
  authoritative; the raw text may be large, so consider stripping it from `/chat/history` responses later.
- With thinking enabled, `/chat/history` will include `thinking` blocks (and redacted-thinking blocks) because they must
  round-trip to the API; front ends should skip rendering them.
