# AIGM Context Viewer: Design

Status: **implemented** (all three build steps, section 9). Decisions taken after review are in section 10.
This builds on [BACKEND.md](BACKEND.md) (prompts, turn loop), [WORLD.md](WORLD.md) (the briefing), [API.md](API.md)
and [CLIENT.md](CLIENT.md).

## 1. Goal

The game master's behavior is shaped by what is in the context window: the system prompt (many files), the tool
definitions, the world briefing, and the conversation history. As the context engineering grows, we need to *see*
exactly what the model would receive, not infer it from the prompt files and the code.

The context viewer shows, inside the client, **the full request that the next player message would produce**, as a
colored tree in which every part can be collapsed. It is a developer tool: it reveals the GM's private notes, hidden
world facts and the full system prompt, so it is **off unless the server is started with `--debug`**.

### Non-goals (v1)

Editing the context, replaying or diffing past requests, exact token counts from the API (estimates only, see 5),
showing what the model *returned* (the transcript already does), and a viewer for the curator's own requests (the world
dump covers the world's content).

## 2. Debug mode

- `aigm --debug` (and `AIGM_DEBUG=true`) turns it on. It composes with `--test`; test mode is the easiest way to try the
  viewer without an API key.
- Without it, nothing about the context is available. There is no other switch, and it is not read from saves.
- The server identifies itself: `GET /health` gains a boolean `debug` field (`false` normally). The client uses this as
  a hint to enable its keystroke and command. The hint is not security: the endpoint enforces the rule itself.
- On startup in debug mode the server prints a line saying that the context endpoint is open and shows hidden game
  information. If `--host` is not a loopback address, it warns that anyone who can reach the server can read the GM's
  secrets.
- The new endpoint is read-only. It changes no state and has no side effects (it does not run the curator, take the
  session's turn slot or touch saves).

## 3. REST call

`GET /debug/context?session_id=default&draft=...`

| Parameter | Meaning |
|---|---|
| `session_id` | Which live session (default `"default"`), as for the other endpoints. |
| `draft` | Optional. The text the player has typed so far. It stands in for the unsent message when the briefing is computed (see 4.3). Omitted means an empty draft. |

Not in debug mode: the route is **not registered at all**, so the server answers `404 not_found` exactly as it does for
any unknown path, and the OpenAPI schema does not list it. Nothing reveals that the feature exists. The client therefore
tells "disabled" from "server too old" by `/health`: a `debug` field that is `false` or missing means the feature is not
available, and it never calls the endpoint.

### Response `200`

```json
{
  "session_id": "default",
  "phase": "adventure",
  "model": "claude-sonnet-5-5",
  "turn": 14,
  "estimated_tokens": 18420,
  "sections": [ <section>, ... ]
}
```

A **section** is a node in a tree:

```json
{
  "id": "prompt/system/adventure/02_rules.md",
  "kind": "system",
  "title": "Rules (adventure/02_rules.md)",
  "text": "## Rules\n...",
  "tokens": 640,
  "children": [ <section>, ... ]
}
```

- `kind` selects the color and is one of `system`, `prompt`, `tools`, `briefing`, `history`, `digest`, `user`,
  `assistant`, `tool_use`, `tool_result`, `thinking`, `input`.
- `text` is the content of a leaf, exactly as the model receives it. A node with `children` has no `text` of its own.
- `tokens` is an estimate (5) for the node and everything under it.
- `id` is stable across calls for the same content (a prompt file path, `history/7`, ...), so the client can
  keep its collapse state when it refreshes.
- An optional `cache_breakpoint: true` marks the node *after which* the request carries a prompt-cache breakpoint,
  because where the breakpoint falls is a context-engineering concern in its own right.

### The tree, in request order

The order is the order of the real request, so reading top to bottom is reading what the model reads.

1. **System prompt** (`system`): one child per source part, in order.
   - the common files (`system/common/*.md`), then the phase's files (`system/<phase>/*.md`), each its own child
     (`prompt`), titled with its path so an override in `AIGM_PROMPT_DIR` is recognizable;
   - the private GM-notes section, only when it is used (an adventure with an empty world, see BACKEND.md).
2. **Tools** (`tools`): one child per tool with its description and input schema.
3. **History** (`history`): one child per message, as the model receives it (when [HISTORY.md](HISTORY.md)'s reduction
   is on, old turns appear trimmed or as one `digest` block, and the response says how much that saved; the stored
   messages themselves are unchanged), `user` or `assistant`, titled with its turn number and a
   first-line preview. Each message has one child per content block: text, `thinking`, `tool_use` (name and input),
   `tool_result`. Stored thinking blocks are sent back to the model, so they are shown; the signature is omitted.
4. **The pending user message**, in two parts, because the briefing travels in the same message as the player's text:
   - the **input placeholder** (`input`): `«your next message goes here»`, or the draft if given;
   - the **briefing** (`briefing`): the `<world_notes>` block, with its sections (clock, location, present, nearby,
     relevant, corrections) as children. It is absent in Session 0 and while the world is empty.

## 4. Keeping the view true

### 4.1 One source of truth

The viewer must not drift from the real request. Today `Game` builds the pieces (`system`, `tools`, `request_messages`)
and `run_turn` hands them to the model client. The change is to have `Game` produce a structured **request description**
(named, ordered parts) from which both the real request and the debug view are derived, rather than writing a second
code path that imitates the first. A test asserts that flattening the description yields exactly the system prompt,
tools and messages that `run_turn` sends.

For this, `PromptLibrary` returns the system prompt as a list of `(source, text)` parts and joins them; the joined
string is unchanged.

### 4.2 What is shown

The committed state of the session: `session.messages` and `session.state`, as the next turn would start from them. A
turn still in flight is not included, and the viewer does not block it. If a curator result is queued, the next turn
would apply it first, so the view applies it to a copy (`drain_pending` semantics, without mutating the session).

### 4.3 The briefing depends on the message

The briefing is chosen by what the player's message and the last GM reply mention. Before the player sends anything the
exact text is unknown, so the preview is computed from the `draft` (empty if none). The client sends what is currently
typed in the prompt when it opens or refreshes the view. The view says so on the briefing node ("computed for the draft,
not the final message"). Without a draft, the "relevant" section is what the last GM reply alone brings in.

### 4.4 Session 0

The viewer works in both phases. In Session 0 there is no briefing and no world, and the tree is the Session 0 prompts,
tools and history.

## 5. Token estimates

Per-node `tokens` use the same rough estimate as the briefing budget (characters divided by four), so the numbers are
comparable with `AIGM_WORLD_BRIEFING_TOKENS`. They are for proportion ("the rules are 6% of the window"), not billing.
Exact counts would need the API's token-counting call; that is a possible later addition, not v1.

## 6. Client

### 6.1 Opening it

- Keystroke **`Ctrl+K`**, and the slash command **`/context`**. (`Ctrl+D` is avoided because terminals treat it as
  end-of-input.)
- Both are active only when `/health` reported `debug: true`. Otherwise the key is not bound and the footer hint is not
  shown, and `/context` prints "The server is not in debug mode (start it with --debug)." If the server answers `404`
  anyway (an older server), it prints the same message.
- It is available at any time, including while a turn is streaming (it shows the committed state, see 4.2).

### 6.2 The screen

A full-screen modal over the game, closed with `Esc`, `Ctrl+K` or `q`. A header line shows the phase, model, turn and
the total estimated tokens. The body is a scrollable tree; each row is `▸/▾ title (~N tokens)` in the node's color.

| Kind | Color (suggested) |
|---|---|
| `system` / `prompt` | blue |
| `tools` | cyan |
| `briefing` | yellow |
| `digest` | purple |
| `history` | (group header) dim white |
| `user` | green |
| `assistant` | magenta |
| `thinking` | dim magenta |
| `tool_use` / `tool_result` | orange / dim orange |
| `input` | bold white on a bright background, so the gap is hard to miss |

The colors apply to the row and to a left-hand bar beside the expanded text, so a long expanded section still shows
which part it belongs to. They must be readable in `--ascii` mode (the bar becomes `|`), and every row also carries its
kind as text, so color is never the only signal.

Defaults:

- the top-level groups (system prompt, tools, history, pending message) are **expanded**, showing their children as
  one-line rows;
- every **leaf and every history message is collapsed**: a message shows its preview line and token count, and expanding
  it shows its blocks;
- within a message, **tool calls and results are collapsed** even when the message is expanded (they can be long);
- the **input placeholder is always visible**, never collapsible.

Keys: `Enter`/`Space` toggles the focused node, `Up`/`Down` move, `PageUp`/`PageDown` scroll, `e` expands everything,
`c` collapses everything back to the defaults, `r` refreshes from the server (the current draft is re-sent), `Esc`
closes. Collapse state is kept by node `id` across refreshes within one open, and is reset when the viewer is closed.

### 6.3 Implementation notes

- Built on Textual's `Tree` or a custom `ScrollView` of rows, whichever lets a long, wrapped body sit under a node;
  decided when implementing (long multi-line text rules out one-line `Tree` labels, so a custom list of collapsible
  blocks is likely).
- A pure function turns the response into a flat list of visible rows given the collapse set, so that the logic is
  testable without a terminal.
- The client treats unknown `kind` values as plain text (the same rule as unknown SSE events).
- `ApiClient` gains `context(session_id, draft)`.

## 7. Spoilers and safety

- Debug off means the route is never registered (decided at app creation), so no handler can run the builder. A test
  covers every way of reaching it (no flag, `AIGM_DEBUG=false`, a second app instance created without the flag).
- The response is never logged in full; the server logs only that it was requested.
- It is not cached or written to disk. The world dump (WORLD.md) is a separate, already-existing debug aid and has its
  own switch.
- The viewer shows the client the same text the model sees, nothing derived or hidden beyond that, so there is no second
  representation to leak.

## 8. Tests

Server:
- `--debug` and `AIGM_DEBUG` set the flag; `/health` reports it both ways.
- The endpoint is `404` without the flag (the same body as any unknown path, and absent from `/openapi.json`) and `200`
  with it; unknown sessions behave like `/chat/history`.
- The flattened description equals the real request (system, tools and messages), for both phases, with and without a
  world, and with a cache breakpoint.
- Ordering, kinds and ids are as in 3; the briefing node carries the draft's effect; a queued curator result is
  reflected without being applied to the session.
- Calling the endpoint changes nothing (the world version, messages and pending queue are the same before and after).

Client:
- The row builder: default collapse state, toggling, expand/collapse all, state kept by id across refresh.
- The key and command are inert when `/health` says `debug: false` or lacks the field, and no request is made.
- A Pilot test opens the screen against a scripted response and checks the placeholder is visible and colors/kinds
  appear in the rendered rows.

## 9. Build steps

1. **Request description** (server), *done*: the system prompt is split into parts (`PromptLibrary.system_parts`),
   `Game.describe` produces a `RequestDescription`, `run_turn` sends what it describes, and a test checks the
   equivalence. No behavior change.
2. **Debug mode and endpoint**, *done*: `--debug`/`AIGM_DEBUG`, the `/health` field, `GET /debug/context`, the startup
   notice, tests, and API.md/BACKEND.md/README.
3. **Client viewer**, *done*: `ApiClient.context`, the row model, the screen, `Ctrl+K` and `/context`, tests, and
   CLIENT.md.

Each step leaves both test suites green.

## 10. Decisions

1. **Key:** `Ctrl+K`.
2. **Draft:** the client sends the text typed so far, so the briefing preview matches what the next message would bring
   in.
3. **Thinking blocks:** shown (collapsed by default). The aim is to see everything the model will see, so there is no
   hide toggle.
4. **Disabled server:** `404`, with the route not registered, as if the feature did not exist.
