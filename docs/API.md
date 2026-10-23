# AIGM Backend API

HTTP API for the AI Game Master backend (v0.1). The server is a FastAPI app. Clients send chat messages by `POST` and
receive the GM's reply as a Server-Sent Events (SSE) stream of markdown text interleaved with custom events (e.g. die
rolls) that a front end may render specially.

- Base URL (dev): `http://127.0.0.1:8000` (the default address of `uvicorn aigm.app:app`)
- All request bodies are JSON (`Content-Type: application/json`).
- Non-streaming responses are JSON.
- No authentication in v0.1. Single global conversation (see "Sessions").

## Sessions

v0.1 supports multiple named sessions so the API doesn't need to change later, but a client may ignore this and use the
default.

- A session is identified by `session_id` (string, `[A-Za-z0-9_-]{1,64}`).
- If omitted, `session_id` defaults to `"default"`.
- Sessions are created implicitly on first use.
- Each session owns one chat history and one game state.

## Game phases

Each session is in one of two phases, reported as `phase` in several responses:

| `phase`        | Meaning                                                                                  |
|----------------|------------------------------------------------------------------------------------------|
| `session_zero` | Setup. The GM helps the player establish the setting and the party. Every new game starts here. |
| `adventure`    | The game proper.                                                                         |

The only transition is `session_zero` to `adventure`, and it is made by the model: once the setting and party are
settled and the player has confirmed, it calls the `begin_adventure` tool (see below). There is no way back to Session 0
within a game; `POST /chat/new` starts a new game, which begins in Session 0. The phase selects the system prompt and
tools the model sees; clients just chat as usual.

The game state (the phase, plus the campaign record written by `begin_adventure`) is saved and restored together with
the history, so a game can be saved during Session 0. Saves made before game state existed load as `adventure`.

---

## Endpoints Summary

| Method | Path                          | Purpose                                              | Response   |
|--------|-------------------------------|------------------------------------------------------|------------|
| POST   | `/chat`                       | Send a user message, stream GM reply                 | SSE stream |
| POST   | `/chat/new`                   | Start a fresh game (clear live history)              | JSON       |
| GET    | `/chat/history`               | Show the session's live (current) chat history       | JSON       |
| GET    | `/history`                    | List all saved histories                             | JSON       |
| GET    | `/history/{name}`             | Show info about one saved history (no loading)       | JSON       |
| PUT    | `/history/{name}/save`        | Save the live history under `{name}`                 | JSON       |
| POST   | `/history/{name}/restore`     | Load saved history `{name}` into the live session    | JSON       |
| DELETE | `/history/{name}`             | Delete one saved history                             | JSON       |
| GET    | `/health`                     | Liveness check; reports whether debug mode is on     | JSON       |
| GET    | `/compendium`                 | Counts of what the player has learned, and what is new | JSON     |
| GET    | `/compendium/{category}`      | The known locations, characters or other things      | JSON       |
| GET    | `/compendium/entities/{id}`   | What the player knows about one entity               | JSON       |
| POST   | `/compendium/seen`            | Mark compendium entries as read                      | JSON       |
| GET    | `/debug/context`              | The next request's context (**debug mode only**)     | JSON       |
| GET    | `/debug/story`                | The whole story plan (**debug mode only**)           | JSON       |
| GET    | `/debug/thinking`             | Whether model thinking is on (**debug mode only**)   | JSON       |
| PUT    | `/debug/thinking`             | Turn model thinking on or off (**debug mode only**)  | JSON       |

Terminology:

- **Live history**: the in-memory conversation for a session. `/chat` appends to it.
- **Saved history** (or "named history"): an on-disk snapshot, like a saved game file, identified by `{name}`. Names
  match `[A-Za-z0-9_-]{1,64}`.

`/chat` takes `session_id` in the body. `/chat/new`, `/chat/history`, `/history/{name}/save` and
`/history/{name}/restore` act on a session's live history, selected by optional query param `?session_id=...` (default
`"default"`). `GET /history`, `GET /history/{name}` and `DELETE /history/{name}` touch only saved files and take no
session.

There is intentionally no blanket delete of saved histories. The live history is emptied only by `POST /chat/new` or
replaced by a restore.

---

## POST `/chat`

Send a user message. The server appends it to history, calls the Claude model (running any tool calls), and streams the
reply.

### Request

```json
{
  "message": "I kick open the door and attack the goblin.",
  "session_id": "default"
}
```

| Field        | Type   | Required | Notes                                   |
|--------------|--------|----------|-----------------------------------------|
| `message`    | string | yes      | Non-empty user text.                    |
| `session_id` | string | no       | Defaults to `"default"`.                |

### Response

- Status `200`, `Content-Type: text/event-stream`, `Cache-Control: no-cache`.
- Validation errors (bad JSON, empty message, bad session id) return a normal `422`/`400` JSON error *before* the stream
  starts. Errors occurring after streaming starts are delivered as an `error` event.
- Only one in-flight `/chat` per session; a second concurrent request returns `409 Conflict` (JSON).

### SSE framing

Standard SSE: each event is

```
event: <type>
data: <JSON object>

```

`data` is always a single-line JSON object. Event names:

| Event          | Meaning                                              | Terminal? |
|----------------|------------------------------------------------------|-----------|
| `message_start`| A new assistant turn begins                          | no        |
| `thinking`     | The model is reasoning before/between output         | no        |
| `text`         | A chunk of markdown text to append to the reply      | no        |
| `tool_call`    | The model is invoking a tool (informational)         | no        |
| `dice_roll`    | Result of a `roll_dice` call (front-end custom event)| no        |
| `award`        | The party earned XP or a level (docs/PROGRESSION.md)   | no        |
| `status`       | Progress of a long wait: a tool call being written, or the world after Session 0 | no |
| `phase_change` | The game moved to a new phase (sent once, at the end of the turn) | no |
| `message_end`  | Assistant turn complete                              | yes       |
| `error`        | Unrecoverable error; stream ends after this          | yes       |

Exactly one terminal event (`message_end` or `error`) ends every stream. Clients should concatenate `text` chunks in
order to build the markdown reply. Unknown event types must be ignored by clients (forward compatibility). `thinking` is
optional: it is only sent when the configured model supports and has enabled extended thinking, and clients must work
correctly if it never appears.

#### `message_start`
```json
{ "message_id": "msg_01", "session_id": "default", "phase": "session_zero",
  "ruleset": "dnd55e", "ruleset_name": "D&D 5.5e" }
```

`ruleset` is the id of the ruleset the game is played under (see `set_ruleset` below) and `ruleset_name` its short
display name. A ruleset chosen during the turn shows in the `message_end` of that turn.

`phase` is the phase the turn started in.

#### `thinking`
Signals that the model is reasoning, explaining a pause before (or between) visible output, and streams the reasoning
text. Only sent when thinking is enabled for the model. A thinking phase is a `start`, zero or more `delta`s, and an
`end`:

```json
{ "status": "start" }
{ "status": "delta", "delta": "The goblin has AC 15, so I should " }
{ "status": "end", "duration_ms": 4200 }
```

| Field         | Type   | Notes                                                                 |
|---------------|--------|-----------------------------------------------------------------------|
| `status`      | string | `"start"`, `"delta"`, or `"end"`.                                     |
| `delta`       | string | On `delta` only: a fragment of reasoning text (plain text, not necessarily markdown). |
| `duration_ms` | number | On `end` only: wall-clock length of the thinking phase.               |

Rules:
- A turn may contain several thinking phases (e.g. one before each tool call and one after tool results). Phases never
  nest or overlap, and every `start` is followed by an `end` before the next `text` or `tool_call` event.
- Clients concatenate `delta`s in order to build the reasoning text for a phase, and should keep it separate from the
  reply (e.g. a collapsible "reasoning" panel). Reasoning text is not part of the reply and must never be mixed into
  `text`.
- Some models return summarized rather than raw reasoning, and redacted reasoning produces a `start`/`end` pair with no
  `delta`s. Clients must handle phases with no deltas and should always be able to fall back to a simple "Thinking..."
  indicator between `start` and `end`.
- If the stream fails mid-phase, the terminal `error` event ends the stream without an `end`; clients should clear any
  thinking indicator on a terminal event.
- The server can be configured to omit `delta`s (sending only `start`/`end`); clients must not depend on them.

#### `text`
```json
{ "delta": "The goblin snarls and " }
```
`delta` is a markdown fragment; fragments may split mid-word and mid-markdown-token, so clients must concatenate before
rendering.

#### `tool_call`
Emitted when the model finishes specifying a tool call, before it runs.
```json
{
  "tool_use_id": "toolu_abc", "name": "roll_dice",
  "input": { "expression": "1d20+5", "narration": "You lunge at the goblin." }
}
```

For `roll_dice`, the `narration` in the input has already been sent as ordinary `text` events, a few words at a time
as the model wrote it, so it arrives before this event, and a client does not need to read it from `input` (see Tool:
`roll_dice`). `tool_call` and `dice_roll` follow once the model's response is complete. When the response holds several
rolls the order is each roll's narration, then each `tool_call` and `dice_roll` in turn.

#### `dice_roll`
Emitted after `roll_dice` succeeds. Intended for front-end rendering (animations, roll log). Carries everything the
`d20` library reports about the roll, including every individual die.

```json
{
  "tool_use_id": "toolu_abc",
  "expression": "4d6kh3+2 [slashing]",
  "total": 12,
  "result": "4d6kh3 (**1**, **6**, ~~**1**~~, 3) + 2 [slashing] = `12`",
  "crit": "none",
  "comment": null,
  "dice": [
    {
      "notation": "4d6kh3",
      "count": 4,
      "sides": 6,
      "total": 10,
      "annotation": null,
      "rolls": [
        { "value": 1, "kept": true,  "values": [1] },
        { "value": 6, "kept": true,  "values": [6] },
        { "value": 1, "kept": false, "values": [1] },
        { "value": 3, "kept": true,  "values": [3] }
      ]
    }
  ]
}
```

| Field         | Type        | Notes                                                                                  |
|---------------|-------------|----------------------------------------------------------------------------------------|
| `tool_use_id` | string      | Matches the preceding `tool_call`.                                                     |
| `expression`  | string      | Expression as submitted by the model.                                                  |
| `total`       | number      | Final numeric total of the whole expression.                                           |
| `result`      | string      | Human-readable breakdown from `d20`, as markdown (kept dice **bold**, dropped dice ~~struck~~). |
| `crit`        | string      | `"none"`, `"crit"`, or `"fail"`: d20's critical status (natural max/min on the first d20 of the expression). |
| `comment`     | string/null | Text after a `#` in the expression (e.g. `1d20+5 # attack`), if any.                  |
| `dice`        | array       | One entry per dice term in the expression, in order. Empty if the expression has no dice (e.g. `"5+3"`). |

Each `dice` entry:

| Field        | Type        | Notes                                                                           |
|--------------|-------------|---------------------------------------------------------------------------------|
| `notation`   | string      | The dice term, normalized from d20's parse (e.g. `"4d6kh3"`); may differ cosmetically from how it was typed. |
| `count`      | number      | Number of dice rolled (before keep/drop).                                       |
| `sides`      | number      | Faces per die.                                                                  |
| `total`      | number      | Sum of this term's kept dice.                                                   |
| `annotation` | string/null | Annotation d20 attaches to this term. d20 usually attaches `[bracketed]` text to the adjacent term rather than the dice, so this is often `null`; the annotation is always visible in `result`. |
| `rolls`      | array       | Individual dice, in the order rolled.                                           |

Each `rolls` entry:

| Field    | Type     | Notes                                                                                  |
|----------|----------|----------------------------------------------------------------------------------------|
| `value`  | number   | The die's final face value.                                                            |
| `kept`   | boolean  | `false` if dropped by a keep/drop selector (`kh`, `kl`, `dh`, `dl`, advantage, ...).   |
| `values` | number[] | Every face d20 records for this die, in order; `value` is the last entry. Usually one entry; more only if d20 keeps history for the die. |

Dice added by exploding (`e`) appear as additional entries in `rolls`. The exact shape for rerolls and explodes follows
whatever d20 exposes and is pinned by unit tests.

If a roll fails, no `dice_roll` event is emitted. A `tool_call` is followed by a `tool_error` only if we later add one;
in v0.1 the error goes back to the model as the tool result (so it can retry or narrate), and is visible in
`/chat/history`. The tool result sent to the model stays the short `result` string; the structured `dice` data is for
the front end only and is not stored in history.

#### `status`
```json
{ "stage": "world", "message": "Preparing the world...", "done": false }
```
Sent during the turn in which Session 0 ends, between the `begin_adventure` `tool_call` and the opening scene's `text`,
while the server builds the world for the new game (this can take tens of seconds with a real model). Several are sent,
each replacing the last message ("Building the setting...", "Detailing the Rusty Flagon...", and for a story game
"Planning the story..."), then one with
`"done": true` ("The world is ready."). Clients should show the latest `message` in place of their usual "writing"
indicator until `done` (or the end of the stream), and may ignore the event entirely: nothing in the transcript depends
on it. If world preparation fails the stream ends with an `error` (`upstream_error`, retryable) and the whole turn is
rolled back, including the phase change, so the player can confirm again.

The same event reports the silent stretch while the model writes a tool call, which shows no text:
`{ "stage": "tool", "message": "Rolling the dice...", "done": false }` (or `"The GM is making notes..."` for any
other tool) as soon as the call begins, then `{ "stage": "tool", "message": "", "done": true }` when the model's
response ends or it goes on to think or write text. Clients show it in place of their "writing" indicator.

#### `phase_change`
```json
{ "previous": "session_zero", "phase": "adventure" }
```
Sent when the turn changed the game phase, after the last `text` and just before `message_end`. It is only sent once the
turn has succeeded: a turn that fails after calling `begin_adventure` is rolled back entirely, with no `phase_change`,
and the game stays in `session_zero`. The opening scene of the adventure is part of the same turn, so it streams before
this event. The history is rewritten at the same time (see `begin_adventure`).

#### `award`
```json
{ "tool_use_id": "toolu_1", "xp_gained": 120, "to": ["Maren Holt"], "everyone": false, "average_level": 1.67,
  "reason": "the wolves",
  "characters": [{ "name": "Maren Holt", "xp": 340, "level": 2, "previous_level": 1,
                   "classes": { "Paladin": 2 } }] }
```
Sent when the GM calls the `award` tool, in order with the dice rolls. `xp_gained` is what each name in `to` earned
(`everyone`: the whole party; 0 for a pure level-up). `characters` holds the new totals of every character the award
touched, and `level` (the overall level) is above `previous_level` for one who gained a level; `classes` maps their
recorded classes to levels. `average_level` is the whole party's.
Part of a turn that fails is discarded with it.

#### `chapter`
```json
{ "previous": 1, "chapter": 2, "title": "The road to the Vault" }
```
Story games only (docs/STORY.md). Sent when the turn moved the story into a new chapter, after the last `text` and
before `message_end`, and only once the turn has succeeded. When the story ends it is sent with `chapter` 4 and the
title "The end". A chapter can also change between turns, when the background curator reports a finished quest; then
there is no event and the next `message_end` simply shows the new chapter in `story`.

#### `message_end`
```json
{
  "message_id": "msg_01",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 1234, "output_tokens": 210, "cache_read_tokens": 1000, "cache_write_tokens": 0
  },
  "phase": "session_zero",
  "ruleset": "dnd55e",
  "ruleset_name": "D&D 5.5e",
  "story": { "length": "short", "chapter": 2, "chapter_title": "The road to the Vault", "ended": false },
  "compendium": { "new": 1, "updated": 2 },
  "metrics": {
    "turn": 14, "phase": "session_zero", "model": "claude-sonnet-5-5",
    "first_text_ms": 1840, "total_ms": 9210, "pause_ms": 800, "model_calls": 2,
    "input_tokens": 2468, "uncached_input_tokens": 468,
    "cache_read_tokens": 2000, "cache_write_tokens": 0, "output_tokens": 420,
    "history": { "turns": 14, "digested_turns": 0, "trimmed_turns": 0 },
    "requests": [ <request>, ... ]
  }
}
```

`phase` is the phase after the turn. `compendium` counts the compendium entries with something the player has not
read yet (see the compendium section below). `story` is the public summary of a story game and `null` for an endless
game (see `GET /chat/history`). `usage` sums the turn's model calls: `input_tokens` is everything the model read,
cached or not, and the two `cache_*` counts say how much of it was read from or written to the prompt cache.

`metrics` measures the turn (docs/HISTORY.md, A). Times are milliseconds. `first_text_ms` runs from the start of the
turn to the first visible `text` chunk; thinking does not count as text, so a model that thinks first has a later
first text, and each request's `thinking_ms` says how much of the wait was thinking. `total_ms` is the whole turn,
`pause_ms` the part of it spent in the deliberate pause before dice rolls (`AIGM_ROLL_PAUSE`). In a story game the
record also has `chapter`, the chapter the turn began in. `history` says how much of the stored history was condensed
for the model. Each entry of `requests` (one per model call) has the same token counts, its own `first_text_ms` (from
the start of that call; `null` if it wrote no text), `thinking_ms`, `total_ms`, `stop_reason`, and `sent`: estimated
token sizes (`system`, `tools`, `history`, `briefing`, and `history_stored`, what the history would have been without
reduction), message counts, and `history_by_kind` (`player`, `gm`, `digests`, `thinking`, `tool_calls`, `tool_results`).
The same record is appended to `{AIGM_SAVE_DIR}/metrics/{session_id}.jsonl` (with a timestamp and the session id) unless
`AIGM_METRICS=false`. Clients must ignore fields they do not know.

#### `error`
```json
{ "code": "upstream_error", "message": "Anthropic API request failed", "retryable": true }
```

| `code`            | Meaning                                         |
|-------------------|-------------------------------------------------|
| `upstream_error`  | Claude API failure (network, 5xx, rate limit)   |
| `tool_loop_limit` | Model exceeded max tool iterations per turn     |
| `internal_error`  | Unexpected server fault                         |

### Example stream

```
event: message_start
data: {"message_id":"msg_01","session_id":"default"}

event: thinking
data: {"status":"start"}

event: thinking
data: {"status":"delta","delta":"A melee attack, so I roll d20 plus the bonus."}

event: thinking
data: {"status":"end","duration_ms":3100}

event: text
data: {"delta":"You swing your sword. "}

event: tool_call
data: {"tool_use_id":"toolu_abc","name":"roll_dice","input":{"expression":"1d20+5"}}

event: dice_roll
data: {"tool_use_id":"toolu_abc","expression":"1d20+5","total":17,"result":"1d20 (12) + 5 = `17`","crit":"none",
  "comment":null,"dice":[{"notation":"1d20","count":1,"sides":20,"total":12,"annotation":null,
  "rolls":[{"value":12,"kept":true,"values":[12]}]}]}
# (the data field is one line on the wire; it is wrapped here for reading)

event: text
data: {"delta":"A **17** -- your blade bites deep!"}

event: message_end
data: {"message_id":"msg_01","stop_reason":"end_turn","usage":{"input_tokens":812,"output_tokens":64}}

```

Client disconnect mid-stream cancels the upstream call; the partial assistant turn is discarded and the user message
remains in history (see backend design for the rule).

---

## POST `/chat/new`

Start a fresh game: empties the session's live history and puts the game back in Session 0. **Destructive**: the current
live history is discarded and is *not* saved automatically, so save it first (`PUT /history/{name}/save`) if you want to
keep it. Saved histories are never affected.

Query: `session_id` (optional). No request body.

### Response `200`
```json
{ "session_id": "default", "phase": "session_zero", "ruleset": "dnd55e", "ruleset_name": "D&D 5.5e",
  "message_count": 0, "discarded_message_count": 14 }
```

Errors: `409` a `/chat` is in flight for that session; `422` invalid `session_id`. Calling it on an already-empty
session succeeds with `discarded_message_count: 0`.

---

## GET `/chat/history`

Return the full live chat history for a session.

Query: `session_id` (optional).

### Response `200`

```json
{
  "session_id": "default",
  "phase": "adventure",
  "ruleset": "dnd55e",
  "ruleset_name": "D&D 5.5e",
  "campaign": {
    "setting": "The Misty Fens: gritty, haunted marshland ...",
    "opening": "The party arrives at the Drowned Lantern inn at dusk ...",
    "level": 3,
    "party": [{ "name": "Ann", "sheet": "Elf rogue, level 3 ..." }],
    "gm_notes": "The innkeeper is a spy."
  },
  "messages": [
    { "role": "user", "content": [{ "type": "text", "text": "I attack the goblin." }] },
    {
      "role": "assistant",
      "content": [
        { "type": "text", "text": "You swing your sword. " },
        { "type": "tool_use", "id": "toolu_abc", "name": "roll_dice", "input": { "expression": "1d20+5" } }
      ]
    },
    {
      "role": "user",
      "content": [
        { "type": "tool_result", "tool_use_id": "toolu_abc", "content": "1d20 (12) + 5 = `17`", "is_error": false }
      ]
    },
    { "role": "assistant", "content": [{ "type": "text", "text": "A **17** -- your blade bites deep!" }] }
  ]
}
```

`campaign` is the record `begin_adventure` wrote at the end of Session 0, or `null` (always `null` in `session_zero`,
and for adventures loaded from older saves). It includes the private `gm_notes`, so a client should not show it to the
player. History uses the Anthropic Messages API content-block format verbatim, so it round-trips to the model with no
translation. An unknown/empty session returns `200` with `"messages": []`.


`story` is the public summary of a story game, and `null` for an endless one (or before the plan is written):
`{ "length", "chapter", "chapter_title", "ended" }`, plus `ending` (the title of the ending reached) once `ended` is
true; `chapter` is 4 after the end. It never contains the goal, the quests or the endings. `POST
/history/{name}/restore` returns it too. Both the summary and the `chapter` event are what a client shows.

---

## GET `/history`

List all saved histories (the "save slots"). Sorted by `saved_at`, newest first.

### Response `200`
```json
{
  "histories": [
    { "name": "tavern-brawl", "phase": "adventure", "message_count": 14,
      "saved_at": "2026-10-15T18:22:04Z", "model": "claude-sonnet-5-5",
      "structure": "short", "story": { "length": "short", "chapter": 2, "chapter_title": "The road", "ended": false } },
    { "name": "act-1", "phase": "session_zero", "message_count": 52,
      "saved_at": "2026-10-14T21:03:40Z", "model": "claude-sonnet-5-5" }
  ]
}
```

`structure` is `endless`, `short`, `medium` or `long`, and `story` is the public summary (below) or `null`. No saves
yields `{ "histories": [] }`.

---

## GET `/history/{name}`

Show information about one saved history without loading it. Does not touch any live session.

Query: `include_messages` (optional bool, default `false`). When true, the response also contains the full `messages`
array in the same format as `/chat/history`.

### Response `200`
```json
{
  "name": "tavern-brawl",
  "phase": "adventure",
  "message_count": 14,
  "saved_at": "2026-10-15T18:22:04Z",
  "model": "claude-sonnet-5-5",
  "entity_count": 12,
  "fact_count": 61,
  "world_time": { "day": 3, "hour": 14 },
  "last_message_preview": "A **17** -- your blade bites deep!"
}
```

`entity_count`, `fact_count` (active facts) and `world_time` summarize the saved world (zero and day 1, 08:00 for saves
with no world); the same three fields appear in each entry of `GET /history`. `last_message_preview` is the first ~200
characters of the final assistant text (omitted if none). Errors: `400` invalid name; `404` no such history; `422` file
corrupt.

---

## PUT `/history/{name}/save`

Save the session's live history under `{name}`. Does not change the live history. If a save with that name already
exists, the request is refused unless `overwrite=true` is given.

Query: `session_id` (optional); `overwrite` (optional bool, default `false`). No request body.

### Response `200`
```json
{ "name": "tavern-brawl", "session_id": "default", "phase": "adventure", "message_count": 14,
  "saved_at": "2026-10-15T18:22:04Z", "overwritten": false }
```

`overwritten` is `true` only when `overwrite=true` was given and a save of that name already existed. Errors: `400`
invalid name; `409` with error code `already_exists` if `{name}` exists and `overwrite` is not `true` (the existing save
is untouched); `409` with code `conflict` if a `/chat` is in flight for that session (avoids saving a half-finished
turn); `500` storage failure. Saving an empty live history is allowed.

---

## POST `/history/{name}/restore`

Load saved history `{name}` into the session's live history, and set the session's game state (phase and campaign) to
the saved one. **Destructive**: the current live history is discarded (save it first if you want to keep it). POST is
used because it changes server state and must not be triggered by prefetching or caching.

Query: `session_id` (optional). No request body.

### Response `200`
```json
{ "name": "tavern-brawl", "session_id": "default", "phase": "adventure", "message_count": 14,
  "saved_at": "2026-10-15T18:22:04Z", "replaced_message_count": 6 }
```

`replaced_message_count` is the size of the discarded live history. Errors: `400` invalid name; `404` no such history;
`409` a `/chat` is in flight for that session; `422` saved file corrupt or invalid. On any error the live history is
left unchanged.

---

## DELETE `/history/{name}`

Delete one saved history. Does not affect any live session, even one that was restored from it.

### Response `200`
```json
{ "name": "tavern-brawl", "deleted": true }
```

Errors: `400` invalid name; `404` no such history. There is no endpoint that deletes all saves.

---

## GET `/health`

Response `200`: `{ "status": "ok", "model": "claude-sonnet-5-5", "debug": false, "compendium": true }`

`compendium` is `true` when the server has the compendium endpoints below; older servers leave it out.

`debug` is `true` when the server was started with `--debug` (or `AIGM_DEBUG=true`). Clients use it to decide whether
to offer the context viewer and the thinking switch; it does not grant access by itself. In debug mode the response
also has `"thinking": true|false`, the current state of the switch below.

---

## The compendium

What the player has learned about the world (docs/COMPENDIUM.md). Every call takes the usual `session_id` query
parameter. Only facts the player has been told, and entities they have discovered, are ever returned. The calls read the
game as of the last finished turn, so they are safe at any time, including during a turn.

Categories: `locations` (location), `characters` (npc) and `other` (faction and concept).

### GET `/compendium`

```json
{
  "session_id": "default",
  "phase": "adventure",
  "categories": [
    { "id": "locations", "title": "Locations", "count": 6, "new": 1, "updated": 1 },
    { "id": "characters", "title": "Characters", "count": 4, "new": 0, "updated": 2 },
    { "id": "other", "title": "Other", "count": 2, "new": 0, "updated": 0 }
  ],
  "new": 1,
  "updated": 3
}
```

`new` entries are ones whose every known fact is unread; `updated` ones have some read and some unread. In Session 0
every count is `0`.

### GET `/compendium/{category}`

Query: `q` (case-insensitive part of a name or a known alias), `status` (`new`, `updated` or `unseen` for either),
`sort` (`name`, the default; `recent`, newest learned first; `tree`, locations only, parents before children). A bad
value is `422`; an unknown category is `404`.

```json
{
  "session_id": "default",
  "category": "locations",
  "title": "Locations",
  "count": 1,
  "entries": [
    {
      "id": "e007",
      "name": "Harrow Mine",
      "kind": "location",
      "category": "locations",
      "summary": "The mine lies deep in the Thornwood.",
      "parent": { "id": "e003", "name": "Thornwood" },
      "depth": 0,
      "fact_count": 5,
      "status": "updated",
      "unseen_count": 2,
      "learned_turn": 31
    }
  ]
}
```

`parent` is set only when the parent is itself discovered. `depth` is the nesting level in a `tree` sort and `0`
otherwise. `status` is `"new"`, `"updated"` or `null`.

### GET `/compendium/entities/{entity_id}`

```json
{
  "session_id": "default",
  "id": "e007",
  "name": "Harrow Mine",
  "kind": "location",
  "category": "locations",
  "aliases": ["the old mine"],
  "status": "updated",
  "parent": { "id": "e003", "name": "Thornwood" },
  "path": [{ "id": "e001", "name": "Ashby Vale" }, { "id": "e003", "name": "Thornwood" }],
  "children": [{ "id": "e012", "name": "Lower Gallery", "kind": "location", "status": "new" }],
  "facts": [
    {
      "id": "f0042",
      "text": "The Harrow Mine was abandoned forty years ago after a collapse.",
      "aspect": "history",
      "label": "History",
      "learned_turn": 31,
      "new": false
    }
  ],
  "related": [{ "id": "e020", "name": "Thorn Guild", "kind": "faction", "category": "other" }],
  "learned_turn": 31,
  "updated_turn": 48
}
```

`facts` read subject facts first, then mentions, each in the order of the kind's checklist. `404` for an id that does
not exist and, with the same message, for one the player has not discovered. A malformed id is `422`.

### POST `/compendium/seen`

Request: exactly one of `{ "entities": ["e007", "e012"] }` or `{ "all": true }`. Unknown and undiscovered ids are
ignored. The response is the `GET /compendium` summary after the change. While a turn is running the marks are held and
applied after it, and the response already shows them applied.

`GET /chat/history` and `POST /history/{name}/restore` also carry `"compendium": { "new": n, "updated": m }`.

---

## GET `/debug/context`

**Debug mode only.** Without `--debug` the route is not registered: the server answers `404 not_found` exactly as for
any unknown path, and the path is absent from the OpenAPI schema. The response shows the GM's private notes and hidden
world facts, so run debug mode only on a trusted machine (the server warns if it listens on a non-loopback host).

The request the next player message would produce, as a tree of named parts in request order. It is built from the
same description that is sent to the model, from the session's committed state; calling it changes nothing. Finished
curator results the next turn would apply first are included.

Query parameters: `session_id` (default `"default"`) and `draft` (optional, at most 20000 characters): the text typed
so far, used in place of the unsent message when the world briefing is chosen.

### Response `200`

```json
{
  "session_id": "default",
  "phase": "adventure",
  "model": "claude-sonnet-5-5",
  "turn": 14,
  "estimated_tokens": 18420,
  "reduction": {
    "turns": 40, "digested_turns": 23, "trimmed_turns": 12,
    "history_tokens_stored": 61000, "history_tokens_sent": 14000, "history_tokens_saved": 47000
  },
  "sections": [ { "id": "system", "kind": "system", "title": "System prompt", "tokens": 5200, "children": [] } ]
}
```

`reduction` says what the history reduction did (docs/HISTORY.md): how many turns are shown as digests or trimmed,
and the estimated size of the history stored against the history sent.

Each node has `id` (stable between calls for the same content, so a client can keep its collapse state), `kind`,
`title` and `tokens` (an estimate: characters divided by four, summed over children). A leaf has `text`, exactly as the
model receives it; any other node has `children`. Optional fields: `cache_breakpoint` (true on the node after which the
request carries a prompt-cache breakpoint) and `note` (on the briefing).

Top-level sections, in order:

- `system` (kind `system`): one child per prompt file, kind `prompt`, `id` `prompt/<path under prompts/>`. The private
  GM-notes section (`prompt/templates/gm_notes.md`) appears only when the world is empty.
- `tools` (kind `tools`): one child per tool: its description and input schema.
- `history` (kind `history`): one child per message *as sent* (kind `user` or `assistant`, `id` `history/<index>`
  counted in the sent list) with one child per content block: text (kind `user`/`assistant`), `thinking` (signatures
  are not shown), `tool_use` and `tool_result`. When the history is reduced, the titles keep the real turn numbers,
  trimmed turns say `(trimmed)`, and the digests of the oldest turns are one block of kind `digest` at the start of the
  oldest turn shown in full.
- `next` (kind `user`): the pending message, with the `input` placeholder (the draft, or `«your next message goes
  here»`) and, in the adventure once the world is not empty, the `briefing` (the `<world_notes>` block) with one child
  per section: Clock, Location, Present, Nearby, Relevant, Corrections.

Unknown `kind` values may be added later; clients should show them as plain text.


---

## GET `/debug/story`

**Debug mode only** (absent otherwise, like `/debug/context`). The whole story plan, spoilers and all: `structure`,
`story` (the plan as saved: goal, chapters, quests with their statuses and outcomes, endings, choices, or `null`),
`text` (the same as readable lines) and `waiting_for_plan` (the chapter whose quests the background plotter has not
written yet, or `null`). Query parameter: `session_id`.

---

## GET and PUT `/debug/thinking`

**Debug mode only**, and absent otherwise exactly like `/debug/context` (`404 not_found`). It exists so one action can
be tried from the same save with and without the model's thinking.

`GET` answers `200` `{ "thinking": true }`. `PUT` takes `{ "enabled": false }` and answers `200` with the new state,
`{ "thinking": false }`; a non-boolean `enabled` is `422`. When thinking is off the GM's requests send
`thinking: {"type": "between_tools"}`. The setting belongs to the server, not to a session: it applies to every session
until it is changed again or the server restarts (it then starts on). The model then writes no thinking before
its answer; the short updates it writes between tool calls still come back as thinking blocks. The system prompt
gets a closing note asking it not to plan out loud in its visible text. The stored history is never changed, but while
thinking is off the request leaves out the thinking blocks of earlier turns (the current turn keeps its own), because
the model copies the reasoning it sees. The world curator's own requests are not affected.

---

## Tool: `roll_dice`

Exposed to the model, not directly to HTTP clients. Documented here because its results surface in `dice_roll` events
and history.

### Tool definition (as sent to Claude)

```json
{
  "name": "roll_dice",
  "eager_input_streaming": true,
  "description": "Roll dice using d20 expression syntax (e.g. '1d20+5', '4d6kh3', '2d8+1d4+3'; use '2d20kh1' for
    advantage). Use for any random outcome: attacks, checks, saves, damage, random tables.",
  "input_schema": {
    "type": "object",
    "properties": {
      "expression": { "type": "string", "description": "A dice expression supported by the Python d20 library." },
      "narration": { "type": "string", "description": "Narration shown to the player just before the dice." }
    },
    "required": ["expression", "narration"]
  }
}
```

### Results

- Success: tool result text is the d20 breakdown string (e.g. ``1d20 (12) + 5 = `17` ``); `is_error: false`; the
  `narration` was streamed as `text` events while the model wrote it (its own paragraph, ending with a blank line),
  and a `dice_roll` SSE event is emitted after the response completes. The narration is shown as story text, so the
  player reads what is happening before the dice land. It stays in the saved `tool_use` input, so the model sees it
  in later turns and history replay can show it.
- Missing or too short `narration` (under 10 characters): nothing is rolled. The tool result is an error that tells the
  model to call again with a narration, `is_error: true`, and no `dice_roll` event. A short narration has already been
  streamed by then, so the error also says it was shown.
- Malformed expression (with a valid narration): tool result is an error message such as
  `Invalid dice expression '2x20': <d20 error text>. Expected syntax like '1d20+5' or '4d6kh3'.` with `is_error: true`.
  The model sees this and may retry. No `dice_roll` event. The narration was already shown, so the error says so and
  asks the retry not to repeat it.
- Guardrails: expression length limit (200 chars) and d20's own roll-count limits; violations are reported as the same
  error form.

---

## Tool: `set_ruleset`

Offered in `session_zero` only. Chooses the ruleset the game is played under; the default is `dnd55e`, and the choice is
final once the adventure begins. The catalog and the meaning of each id are in [RULESETS.md](RULESETS.md).

```json
{
  "name": "set_ruleset",
  "input_schema": {
    "type": "object",
    "required": ["ruleset"],
    "properties": {
      "ruleset": {
        "type": "string",
        "enum": ["odnd", "basic", "becmi", "adnd1e", "adnd2e", "dnd3e", "dnd35e", "dnd4e", "dnd5e", "dnd55e",
                 "pf1e", "pf2e"]
      }
    }
  }
}
```

Results: success says which ruleset is now in force (and that characters built under another must be rebuilt); an
unknown id is an error listing the valid ones. Its rules and period feel are in the system prompt from the next request
on. The ruleset is saved with the game (`ruleset` in the save file; older saves are `dnd55e`) and is part of the
campaign record.

---

## Tool: `set_structure`

Offered in `session_zero` only. Records the kind of game, which the GM always asks the player about before it leaves
Session 0 (unless their own words already made it plain). See [STORY.md](STORY.md).

```json
{
  "name": "set_structure",
  "input_schema": {
    "type": "object",
    "required": ["mode"],
    "properties": { "mode": { "type": "string", "enum": ["endless", "short", "medium", "long"] } }
  }
}
```

`endless` is an open campaign; `short`, `medium` and `long` are stories with a beginning, middle and end. The last call
wins. Results: success says what the game will be (for a story, that it is planned in secret later); an unknown mode is
an error listing the valid ones. `begin_adventure` is refused, with a message telling the GM to ask and call this tool,
until a choice has been recorded. The choice is saved with the game (`structure` in the save file, `null` until chosen;
games in play and older saves are `endless`), and a story game's campaign record says so.

---

## Tools for story games: `set_scene` story field and `end_story`

Offered only when the game has a story plan (docs/STORY.md); an endless game sees neither. `set_scene` gains an
optional `story` object, and `end_story` is added in the adventure.

```json
{
  "story": {
    "quests": [ { "id": "m03", "status": "done", "outcome": "The party exposed the miller; the captain was spared." } ],
    "goal_revealed": true
  }
}
```

- `status` is `done`, `skipped` or `failed`; the quest must be active, and `outcome` is required (kept to shape the
  ending, and the first 600 characters are stored). The result lists the quests that became active and says when a
  new chapter begins. Chapter 1 ends when its required quests are settled *and* the goal is known, whichever happens
  last. The whole call is all or nothing: a bad quest report leaves the scene unchanged too.
- `end_story` takes `ending` (an id from the plan, or `end_custom`), `epilogue` and an optional `party_defeated`. It
  is accepted in chapter 3 once its required quests are settled (or `failed`), or at any time with `party_defeated`.
  The story is then concluded, and the result tells the GM to write the final scene and offer to carry on endless.

---

## Tool: `begin_adventure`

Offered to the model only in `session_zero`; once the adventure has begun it is no longer in the tool list. Documented
here because it changes the game phase and rewrites the history.

**Input.** The arguments are the model's only record of Session 0, so the server validates that they are detailed
enough:

| Field | Rule |
|---|---|
| `confirmed` | bool; must be `true` (the player has clearly said they are ready) |
| `setting` | string, at least 300 characters: the world, tone, key places and factions, the central tension, how dangerous it is for this party |
| `opening` | string, at least 100 characters: starting location, situation and immediate hook |
| `level` | integer 1-20 |
| `party` | 1-6 player characters `{name, sheet}`: unique non-empty `name` (compared ignoring case); `sheet` at least 150 characters (the full character). The player controls the whole party and may switch between members; NPCs are not party members |
| `gm_notes` | optional string of private notes |

The total size is capped at 30,000 characters. A call that fails any rule returns an `is_error` tool result that lists
**every** problem, changes nothing, and lets the model fill the gaps and call again (or keep talking with the player).

**On success**, within the turn:

1. The phase becomes `adventure`, and the validated fields are stored as the session's `campaign` (see
   `GET /chat/history`).
2. The history is **replaced**: the Session 0 conversation, the player's confirmation and the tool call and result are
   all discarded, and the history becomes exactly three messages: a short system note (user role, text starting
   `[System: Session 0 is complete...`), a single GM entry (assistant role) containing the campaign record rendered from
   the arguments (setting, party with full sheets, and the opening situation), and a system cue (user role,
   `[System: The adventure begins now...`). The model's very next reply, the first scene, follows them. `gm_notes` are
   not in the record; they go into the adventure system prompt only.
3. When the turn commits, `phase_change` is sent. The final history is those three messages followed by the opening
   scene.

Messages whose text starts with `[System:` are inserted by the server rather than typed by the player; clients should
not show them as player speech.

Like all turn state, the change (including the history rewrite) is committed only if the whole turn succeeds.

---

## Error format (non-streaming)

```json
{ "error": { "code": "not_found", "message": "No saved history named 'tavern-brawl'" } }
```

Codes: `bad_request` (400), `not_found` (404), `conflict` (409), `already_exists` (409), `validation_error` (422),
`internal_error` (500).

---

## Open Questions

1. Stream resumption (`Last-Event-ID`) is not supported in v0.1; a dropped stream means resending the message.
