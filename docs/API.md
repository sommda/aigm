# AIGM Backend API

HTTP API for the AI Game Master backend (v0.1). The server is a FastAPI app. Clients send chat messages by `POST` and receive the GM's reply as a Server-Sent Events (SSE) stream of markdown text interleaved with custom events (e.g. die rolls) that a front end may render specially.

- Base URL (dev): `http://localhost:8000`
- All request bodies are JSON (`Content-Type: application/json`).
- Non-streaming responses are JSON.
- No authentication in v0.1. Single global conversation (see "Sessions").

## Sessions

v0.1 supports multiple named sessions so the API doesn't need to change later, but a client may ignore this and use the default.

- A session is identified by `session_id` (string, `[A-Za-z0-9_-]{1,64}`).
- If omitted, `session_id` defaults to `"default"`.
- Sessions are created implicitly on first use.
- Each session owns one chat history.

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
| GET    | `/health`                     | Liveness check                                       | JSON       |

Terminology:

- **Live history**: the in-memory conversation for a session. `/chat` appends to it.
- **Saved history** (or "named history"): an on-disk snapshot, like a saved game file, identified by `{name}`. Names match `[A-Za-z0-9_-]{1,64}`.

`/chat` takes `session_id` in the body. `/chat/new`, `/chat/history`, `/history/{name}/save` and `/history/{name}/restore` act on a session's live history, selected by optional query param `?session_id=...` (default `"default"`). `GET /history`, `GET /history/{name}` and `DELETE /history/{name}` touch only saved files and take no session.

There is intentionally no blanket delete of saved histories. The live history is emptied only by `POST /chat/new` or replaced by a restore.

---

## POST `/chat`

Send a user message. The server appends it to history, calls the Claude model (running any tool calls), and streams the reply.

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
- Validation errors (bad JSON, empty message, bad session id) return a normal `422`/`400` JSON error *before* the stream starts. Errors occurring after streaming starts are delivered as an `error` event.
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
| `message_end`  | Assistant turn complete                              | yes       |
| `error`        | Unrecoverable error; stream ends after this          | yes       |

Exactly one terminal event (`message_end` or `error`) ends every stream. Clients should concatenate `text` chunks in order to build the markdown reply. Unknown event types must be ignored by clients (forward compatibility). `thinking` is optional: it is only sent when the configured model supports and has enabled extended thinking, and clients must work correctly if it never appears.

#### `message_start`
```json
{ "message_id": "msg_01", "session_id": "default" }
```

#### `thinking`
Signals that the model is reasoning, explaining a pause before (or between) visible output, and streams the reasoning text. Only sent when thinking is enabled for the model. A thinking phase is a `start`, zero or more `delta`s, and an `end`:

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
- A turn may contain several thinking phases (e.g. one before each tool call and one after tool results). Phases never nest or overlap, and every `start` is followed by an `end` before the next `text` or `tool_call` event.
- Clients concatenate `delta`s in order to build the reasoning text for a phase, and should keep it separate from the reply (e.g. a collapsible "reasoning" panel). Reasoning text is not part of the reply and must never be mixed into `text`.
- Some models return summarized rather than raw reasoning, and redacted reasoning produces a `start`/`end` pair with no `delta`s. Clients must handle phases with no deltas and should always be able to fall back to a simple "Thinking..." indicator between `start` and `end`.
- If the stream fails mid-phase, the terminal `error` event ends the stream without an `end`; clients should clear any thinking indicator on a terminal event.
- The server can be configured to omit `delta`s (sending only `start`/`end`); clients must not depend on them.

#### `text`
```json
{ "delta": "The goblin snarls and " }
```
`delta` is a markdown fragment; fragments may split mid-word and mid-markdown-token, so clients must concatenate before rendering.

#### `tool_call`
Emitted when the model finishes specifying a tool call, before it runs.
```json
{ "tool_use_id": "toolu_abc", "name": "roll_dice", "input": { "expression": "1d20+5" } }
```

#### `dice_roll`
Emitted after `roll_dice` succeeds. Intended for front-end rendering (animations, roll log). Carries everything the `d20` library reports about the roll, including every individual die.

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

Dice added by exploding (`e`) appear as additional entries in `rolls`. The exact shape for rerolls and explodes follows whatever d20 exposes and is pinned by unit tests.

If a roll fails, no `dice_roll` event is emitted. A `tool_call` is followed by a `tool_error` only if we later add one; in v0.1 the error goes back to the model as the tool result (so it can retry or narrate), and is visible in `/chat/history`. The tool result sent to the model stays the short `result` string; the structured `dice` data is for the front end only and is not stored in history.

#### `message_end`
```json
{
  "message_id": "msg_01",
  "stop_reason": "end_turn",
  "usage": { "input_tokens": 1234, "output_tokens": 210 }
}
```

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
data: {"tool_use_id":"toolu_abc","expression":"1d20+5","total":17,"result":"1d20 (12) + 5 = `17`","crit":"none","comment":null,"dice":[{"notation":"1d20","count":1,"sides":20,"total":12,"annotation":null,"rolls":[{"value":12,"kept":true,"values":[12]}]}]}

event: text
data: {"delta":"A **17** -- your blade bites deep!"}

event: message_end
data: {"message_id":"msg_01","stop_reason":"end_turn","usage":{"input_tokens":812,"output_tokens":64}}

```

Client disconnect mid-stream cancels the upstream call; the partial assistant turn is discarded and the user message remains in history (see backend design for the rule).

---

## POST `/chat/new`

Start a fresh game: empties the session's live history. **Destructive**: the current live history is discarded and is *not* saved automatically, so save it first (`PUT /history/{name}/save`) if you want to keep it. Saved histories are never affected.

Query: `session_id` (optional). No request body.

### Response `200`
```json
{ "session_id": "default", "message_count": 0, "discarded_message_count": 14 }
```

Errors: `409` a `/chat` is in flight for that session; `422` invalid `session_id`. Calling it on an already-empty session succeeds with `discarded_message_count: 0`.

---

## GET `/chat/history`

Return the full live chat history for a session.

Query: `session_id` (optional).

### Response `200`

```json
{
  "session_id": "default",
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

History uses the Anthropic Messages API content-block format verbatim, so it round-trips to the model with no translation. An unknown/empty session returns `200` with `"messages": []`.

---

## GET `/history`

List all saved histories (the "save slots"). Sorted by `saved_at`, newest first.

### Response `200`
```json
{
  "histories": [
    { "name": "tavern-brawl", "message_count": 14, "saved_at": "2026-10-15T18:22:04Z", "model": "claude-sonnet-5-5" },
    { "name": "act-1",        "message_count": 52, "saved_at": "2026-10-14T21:03:40Z", "model": "claude-sonnet-5-5" }
  ]
}
```

No saves yields `{ "histories": [] }`.

---

## GET `/history/{name}`

Show information about one saved history without loading it. Does not touch any live session.

Query: `include_messages` (optional bool, default `false`). When true, the response also contains the full `messages` array in the same format as `/chat/history`.

### Response `200`
```json
{
  "name": "tavern-brawl",
  "message_count": 14,
  "saved_at": "2026-10-15T18:22:04Z",
  "model": "claude-sonnet-5-5",
  "last_message_preview": "A **17** -- your blade bites deep!"
}
```

`last_message_preview` is the first ~200 characters of the final assistant text (omitted if none). Errors: `400` invalid name; `404` no such history; `422` file corrupt.

---

## PUT `/history/{name}/save`

Save the session's live history under `{name}`. Does not change the live history. If a save with that name already exists, the request is refused unless `overwrite=true` is given.

Query: `session_id` (optional); `overwrite` (optional bool, default `false`). No request body.

### Response `200`
```json
{ "name": "tavern-brawl", "session_id": "default", "message_count": 14, "saved_at": "2026-10-15T18:22:04Z", "overwritten": false }
```

`overwritten` is `true` only when `overwrite=true` was given and a save of that name already existed. Errors: `400` invalid name; `409` with error code `already_exists` if `{name}` exists and `overwrite` is not `true` (the existing save is untouched); `409` with code `conflict` if a `/chat` is in flight for that session (avoids saving a half-finished turn); `500` storage failure. Saving an empty live history is allowed.

---

## POST `/history/{name}/restore`

Load saved history `{name}` into the session's live history. **Destructive**: the current live history is discarded (save it first if you want to keep it). POST is used because it changes server state and must not be triggered by prefetching or caching.

Query: `session_id` (optional). No request body.

### Response `200`
```json
{ "name": "tavern-brawl", "session_id": "default", "message_count": 14, "saved_at": "2026-10-15T18:22:04Z", "replaced_message_count": 6 }
```

`replaced_message_count` is the size of the discarded live history. Errors: `400` invalid name; `404` no such history; `409` a `/chat` is in flight for that session; `422` saved file corrupt or invalid. On any error the live history is left unchanged.

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

Response `200`: `{ "status": "ok", "model": "claude-sonnet-5-5" }`

---

## Tool: `roll_dice`

Exposed to the model, not directly to HTTP clients. Documented here because its results surface in `dice_roll` events and history.

### Tool definition (as sent to Claude)

```json
{
  "name": "roll_dice",
  "description": "Roll dice using d20 expression syntax (e.g. '1d20+5', '4d6kh3', '2d8+1d4+3'; use '2d20kh1' for advantage). Use for any random outcome: attacks, checks, saves, damage, random tables.",
  "input_schema": {
    "type": "object",
    "properties": {
      "expression": { "type": "string", "description": "A dice expression supported by the Python d20 library." }
    },
    "required": ["expression"]
  }
}
```

### Results

- Success: tool result text is the d20 breakdown string (e.g. ``1d20 (12) + 5 = `17` ``); `is_error: false`; a `dice_roll` SSE event is emitted.
- Malformed expression: tool result is an error message such as `Invalid dice expression '2x20': <d20 error text>. Expected syntax like '1d20+5' or '4d6kh3'.` with `is_error: true`. The model sees this and may retry. No `dice_roll` event.
- Guardrails: expression length limit (200 chars) and d20's own roll-count limits; violations are reported as the same error form.

---

## Error format (non-streaming)

```json
{ "error": { "code": "not_found", "message": "No saved history named 'tavern-brawl'" } }
```

Codes: `bad_request` (400), `not_found` (404), `conflict` (409), `already_exists` (409), `validation_error` (422), `internal_error` (500).

---

## Open Questions

1. Stream resumption (`Last-Event-ID`) is not supported in v0.1; a dropped stream means resending the message.
