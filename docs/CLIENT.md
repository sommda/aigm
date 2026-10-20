# AIGM Client Design

A simple terminal client for the AI Game Master backend (v0.1), written in Python. It speaks the API in [API.md](API.md)
and is meant to feel like playing a text adventure: the story streams in as nicely formatted text, fills a page, and
waits for you to turn the page.

No code yet; this document defines scope, structure, and the tricky parts (streaming markdown, paging).

## Goals / Non-goals

**Goals (v0.1)**
1. Stream the GM's markdown reply to the screen **with correct formatting even while constructs are only partly
   received** (e.g. `**bol` ... `d**`, an unfinished code fence).
2. **Scrollback** through earlier chat.
3. **Paging**: when new text fills the visible page, stop and wait for a key press or click before showing more, while
   still receiving and buffering the stream.
4. Render the custom events (`dice_roll`, `thinking`) sensibly.
5. **Menu-driven save, load, and new game** from the UI (keyboard shortcuts, clickable footer, and dialogs), with
   slash-command equivalents.

**Non-goals (later)**: themes, inline images/maps, multiple panes, character sheets, voice, auto-reconnect/stream resume
(the server doesn't support it), mouse text selection niceties beyond what the terminal gives, authentication.

## Technology Choice

| Option | Verdict |
|---|---|
| **Terminal UI with Textual (+ Rich)** | **Chosen.** Pure Python, runs everywhere, mouse + keyboard, async-native (fits SSE streaming), works over SSH, and Rich gives us a markdown renderer that produces exact terminal lines, which paging needs. |
| Python thick GUI (Tk/Qt) | Heavier; markdown rendering in Tk is poor, Qt adds a big dependency. Revisit if we want images/maps. |
| Web UI (TypeScript) | Best markdown ecosystem and a natural fit for SSE, but a second toolchain. Likely later; the API is already front-end-neutral. |
| `prompt_toolkit` / plain Rich | Rich `Live` can't do scrollback or paging; prompt_toolkit would mean building more of the widget layer ourselves. |

It is a terminal "thick client" in Python, as preferred. The client is its own uv project in `client/` (separate
`pyproject.toml`, `.venv`, `uv.lock`), so it can pin its Python version independently of the server. Both currently use
Python 3.13 (verified: Textual 8.2.8 installs and imports).

### Dependencies

Declared in `client/pyproject.toml`, entirely separate from the server's dependencies:
`textual`, `rich` (comes with Textual), `httpx`. SSE parsing is hand-written (about 30 lines) rather than adding
`httpx-sse`. Dev: `pytest`, `pytest-asyncio`, plus Textual's `Pilot` test driver.

Run (from `client/`): `uv run aigm-client` (or `uv run python -m aigm_client`). Config: `AIGM_URL` (default
`http://127.0.0.1:8000`, where `uvicorn aigm.app:app` listens by default), `--session NAME` (default `default`).

## Screen Layout

```
┌──────────────────────────────────────────────────────────────┐
│ You: I kick open the door and attack the goblin.             │
│                                                              │
│ The door **splinters** inward. The goblin snarls...          │  transcript
│   🎲 1d20+5 → [12] + 5 = 17                                  │  (scrollable view,
│ A **17** -- your blade bites deep!                           │   paged)
│                                                              │
│                      ▼ MORE (34 lines buffered)  [Space/Enter]│  pager bar
├──────────────────────────────────────────────────────────────┤
│ ⠋ Thinking...   game: tavern-brawl*   ● connected            │  status line
│ > _                                                          │  input
├──────────────────────────────────────────────────────────────┤
│ ^S Save   ^O Load   ^N New game   ^T Reasoning   ^Q Quit     │  footer (clickable)
└──────────────────────────────────────────────────────────────┘
```

- **Transcript**: a custom `ScrollView` subclass that draws pre-rendered terminal lines (see "Pager").
- **Pager bar**: one row, shown only while content is being held back.
- **Status line**: spinner while thinking or streaming, the game mode (`Session 0` or `Adventure`, from the server's
  `phase`) followed by the ruleset's short name (`ruleset_name`, for example `Session 0 · AD&D 1e`; omitted by older
  servers), the current game name (the name last saved or loaded; `*` suffix means unsaved changes), and connection
  state.
- **Footer**: key hints that double as clickable buttons for Save / Load / New game.
- **Input**: single-line prompt. A multi-line paste is kept whole: each line break shows as a `⏎` marker in the prompt
  and is sent as a real newline. It is **hidden/disabled** while a page is held back or a turn is in flight (see Input
  Gating), so Space/Enter advance the page rather than type.

## Architecture

```
client/src/aigm_client/
  __main__.py        # arg parsing, launches the app
  app.py             # Textual App: layout, key bindings, wiring
  api.py             # httpx wrapper: REST calls + stream_chat() async iterator
  sse.py             # SSE line parser -> (event_name, data_dict)
  events.py          # typed event dataclasses mirroring API.md
  heal.py            # partial-markdown "healing" (pure functions)
  blocks.py          # transcript block types + rendering to lines
  transcript.py      # line store + pager state machine (pure logic, no UI)
  widgets.py         # TranscriptView (ScrollView), PagerBar, StatusLine, footer
  dialogs.py         # Save / Load / New-game modal screens
  commands.py        # slash-command parsing and dispatch
tests/client/
  test_sse.py  test_heal.py  test_transcript_pager.py  test_commands.py  test_dialogs_pilot.py  test_app_pilot.py
```

Principle: everything with real logic (`sse`, `heal`, `blocks`, `transcript`, `commands`) is pure or UI-free so it can
be unit tested without a terminal. `app.py` and `widgets.py` stay thin.

### Data flow

```
 POST /chat ──SSE──▶ api.stream_chat()  ──typed events──▶ app (worker task)
                                                              │ apply_event()
                                                              ▼
                                                  transcript (blocks → lines)
                                                              │ throttled refresh (~30 fps)
                                                              ▼
                                                  TranscriptView.render_line(y)
```

The stream is consumed by a Textual worker (an async task), independent of the UI's key handling. **Receiving never
stops**: events are always applied to the transcript's block model; the *pager* only limits how many lines are *shown*.

## Server Compatibility

The client implements exactly the contract in API.md.

| Server feature | Client behavior |
|---|---|
| Startup | `GET /health`; if it fails, show a clear "cannot reach server at URL" message and retry on demand. Then `GET /chat/history?session_id=...` to repopulate the transcript with prior conversation (e.g. after a restart). |
| `POST /chat` (SSE) | Stream with no read timeout (long thinking is normal), a short connect timeout, and header `Accept: text/event-stream`. Comment lines (`: ping`) are ignored. |
| `message_start` | Begin a new assistant turn (new page anchor handled by the pager; see below). |
| `thinking` `start` / `delta` / `end` | Spinner + "Thinking..." in the status line. Reasoning deltas accumulate into a **collapsed, dim "reasoning" block** shown only if the user toggles it (`Ctrl+T`, default hidden). `end` stops the spinner; phases with no deltas work the same. |
| `text` | Append `delta` to the current markdown segment (see Streaming Markdown). |
| `tool_call` | No visible output by itself (the `dice_roll` event follows for dice). Closes the current markdown segment. |
| `dice_roll` | Render a dice block (see Dice Rendering). Closes the current markdown segment. |
| `status` | Show `message` in the status line in place of "GM is writing..." (with the spinner) until a `status` with `done: true`, or until the turn ends or fails. Nothing is added to the transcript. This is the pause while the world is built after Session 0. |
| `phase_change` | (When history is reloaded after the switch it is three server-inserted messages plus the new play; user messages starting `[System:` are shown as dim system lines, not as player speech.) Update the mode shown in the status line and add a line "Session 0 is over. The adventure begins!" to the transcript. The status line also follows `phase` on `message_start`/`message_end`. After a startup, load or new game, the phase comes from `GET /chat/history` and `POST /chat/new`; the welcome line and prompt placeholder differ in Session 0. Servers that send no phase are tolerated (no mode is shown). |
| `chapter` | Story games. Print a one-line banner "Chapter 2: The road" (or "The story has ended. You can keep playing in this world." for chapter 4) and update the chapter in the status line (`story: Ch 2/3: The road`, or `story: Story over`). `message_end` and `GET /chat/history` carry a `story` summary that sets the same status; if it shows a chapter the client has not announced (the curator moved it between turns) the banner is printed then, once. Endless games and servers that send no `story` show nothing. |
| `message_end` | Finalize the segment (final un-healed render), stop spinner, re-enable input once all held text has been paged through. |
| `error` | Show a red error block with `message`; clear spinner; note the turn was discarded server-side (the user's message needs resending). |
| Unknown event types / unknown fields | Ignored (forward compatibility, as API.md requires). |
| `409` on `/chat` | "A turn is already in progress for this session." (should not occur given input gating, but handled.) |
| `4xx/5xx` JSON errors | Shown as a system line using `error.message`. |
| Client cancel (`Esc` during a turn) | Close the HTTP stream. The server rolls the whole turn back, so the interrupted turn is annotated `[interrupted - turn discarded]` and the user can resend. |

### Save / Load / New game from the UI

These three actions are first-class UI features, reachable three ways: **keyboard shortcuts**, **clicking the footer
hints**, and **slash commands** (which open the same dialogs when arguments are omitted).

| Action | Shortcut | Alias | Slash command |
|---|---|---|---|
| Save game | `Ctrl+S` | `F2` | `/save [NAME] [--overwrite]` |
| Load game | `Ctrl+O` | `F3` | `/load [NAME]` |
| New game | `Ctrl+N` | `F4` | `/new` |

The `F` keys exist because some terminals intercept `Ctrl+S` (XOFF flow control); Textual runs the terminal in raw mode
so it should work, but this is to be verified on macOS Terminal/iTerm and common Linux terminals.

**When available.** All three are available whenever no chat turn is in flight, *including while held text is waiting to
be paged* (the user need not read everything first). While a turn is streaming they show a hint instead ("Wait for the
GM to finish, or press Esc to cancel the turn"), because the server rejects save/restore/new with `409` during a turn.

**Unsaved-changes tracking.** The client keeps a `dirty` flag: set when a turn completes (`message_end`) or the user
sends a message, cleared on a successful save, load, or new game. It drives the `*` in the status line and decides
whether destructive actions need a warning. A freshly started client that repopulated history from the server starts
`dirty = false` if the server's history is empty, otherwise `true` (it cannot know whether it was saved).

All dialogs are Textual `ModalScreen`s: `Esc` cancels, `Tab`/click moves between controls, `Enter` activates the default
button. Server errors appear inline in the dialog (red text) without closing it.

#### Save dialog (`Ctrl+S`)

```
┌─ Save game ───────────────────────────────┐
│ Name: tavern-brawl_                       │
│                                           │
│ Existing saves:                           │
│   > tavern-brawl    14 msgs  Oct 15 18:22 │
│     act-1           52 msgs  Oct 14 21:03 │
│                                           │
│            [ Save ]   [ Cancel ]          │
└───────────────────────────────────────────┘
```

- Name field is prefilled with the current game name, or a suggested `game-YYYYMMDD-HHMM` for a game that was never
  saved. Names are validated client-side against the server's `[A-Za-z0-9_-]{1,64}` rule with an inline message.
- The existing-saves list comes from `GET /history`; selecting one copies its name into the field.
- On Save the client calls `PUT /history/{name}/save` **without** `overwrite`. If the server answers
  `409 already_exists`, the dialog switches to an inline confirmation: *"'tavern-brawl' already exists. Overwrite?"*
  with `[ Overwrite ]` / `[ Back ]`; Overwrite repeats the call with `?overwrite=true`. (Relying on the server's answer
  rather than the listing avoids races.)
- On success: dialog closes, `dirty = false`, current game name set, a dim system line "Saved as 'tavern-brawl' (14
  messages)" is added to the transcript.

#### Load dialog (`Ctrl+O`)

```
┌─ Load game ─────────────────────────────────────────┐
│ > tavern-brawl    14 msgs  Oct 15 18:22             │
│   act-1           52 msgs  Oct 14 21:03             │
│                                                     │
│ Preview: "A **17** -- your blade bites deep!"       │
│                                                     │
│ ⚠ Unsaved changes in the current game will be lost. │
│        [ Load ]   [ Delete ]   [ Cancel ]           │
└─────────────────────────────────────────────────────┘
```

- List from `GET /history`; highlighting a row fetches `GET /history/{name}` (without messages) for the preview line, so
  nothing is loaded until confirmed.
- The unsaved-changes warning is shown only when `dirty` is true. When it is, `Load` first asks a one-step confirmation
  (*"Discard current game and load 'tavern-brawl'?"* `[ Load anyway ]` `[ Back ]`).
- `Load` calls `POST /history/{name}/restore`, then refetches `GET /chat/history` and rebuilds the transcript; the view
  opens on the last page of the restored conversation (scrollback available), input is shown, `dirty = false`, current
  game name set.
- `Delete` asks for confirmation, calls `DELETE /history/{name}`, and refreshes the list. It never affects the live
  game.
- Empty list: "No saved games yet" with only `[ Cancel ]`.

#### New game dialog (`Ctrl+N`)

```
┌─ New game ────────────────────────────────┐
│ Start a new game?                         │
│ The current game has unsaved changes.     │
│                                           │
│  [ Save first... ] [ Discard ] [ Cancel ] │
└───────────────────────────────────────────┘
```

- If `dirty` is false, the dialog is a simple confirmation (`[ Start new game ]` / `[ Cancel ]`); if the transcript is
  empty it skips the dialog entirely.
- `Save first...` opens the Save dialog and, on a successful save, continues straight to the new game.
- `Discard` calls `POST /chat/new`, clears the transcript and held text, resets current game name to none,
  `dirty = false`, shows a system line "New game started.", and focuses the input.

#### Slash commands

Typed at the prompt; anything not starting with `/` is sent as a chat message. The save/load/new commands open the
dialogs above when the name is omitted, and run directly (still with the destructive-action confirmation when `dirty`)
when it is given.

| Command | Calls | Notes |
|---|---|---|
| `/new` | `POST /chat/new` | Same flow as `Ctrl+N`. |
| `/save [NAME] [--overwrite]` | `PUT /history/{NAME}/save[?overwrite=true]` | No name opens the dialog. On `409 already_exists` without `--overwrite`, shows the overwrite confirmation. |
| `/load [NAME]` | `POST /history/{NAME}/restore` | No name opens the dialog. |
| `/saves` | `GET /history` | Prints the list of saved games into the transcript. |
| `/info NAME` | `GET /history/{NAME}` | Prints metadata and last-message preview. |
| `/delete NAME` | `DELETE /history/{NAME}` | Confirms first. |
| `/story` | `GET /debug/story` | Debug servers only: prints the whole story plan (spoilers) into the transcript. |
| `/context` | `GET /debug/context` | Debug servers only: opens the context viewer (same as `Ctrl+K`). See below. |
| `/thinking [on\|off]` | `PUT /debug/thinking` | Debug servers only: turns the model's thinking on or off, or flips it (same as `F6`). The status line shows `DEBUG (no thinking)` while it is off. |
| `/help`, `/quit` | local | |

### Context viewer (debug servers only)

Shows exactly what the model will be sent for the next message. The design is in [CONTEXT.md](CONTEXT.md); the
server side is `GET /debug/context` in [API.md](API.md).

- **Availability.** `/health` reports `debug`. The client reads it at startup (and on `/reconnect`). When it is not
  `true` (or the field is missing, as on older servers) the viewer does not exist: `Ctrl+K` is unbound, so the prompt
  keeps its own `Ctrl+K` (delete to end of line), the footer does not list it, and `/context` prints "The server is not
  in debug mode (start it with --debug)" without calling the server. On a debug server the status line ends with
  `DEBUG`, the footer lists `Ctrl+K Context`, and `/help` mentions `/context`. `Ctrl+K` has priority over the prompt
  there.
- **Screen.** A full-screen modal with a header (phase, model, turn, estimated tokens), a scrollable tree and a key
  hint line. Each row is `▾ title  kind · ~N tok` in the node's color, with a bar in that color down the left of its
  expanded text. Kinds: system and prompt files blue, tools cyan, briefing yellow, player green, GM magenta, thinking
  dim magenta, tool calls and results orange, the input placeholder bold on white. Every row also names its kind, so
  color is never the only signal. `--ascii` replaces the glyphs (`▌ ▸ ▾ ● ──`) with `| > v * --`.
- **Defaults.** The four top-level groups (system prompt, tools, history, next message) are open, showing one row per
  child. Prompt files, tools, history messages, thinking, tool calls and results and the briefing start closed. A
  message's text blocks show as soon as the message is opened. The input placeholder is always visible and cannot be
  closed; the prompt-cache breakpoint is drawn as a rule under it.
- **Keys.** `Enter`/`Space` open or close the row under the cursor (a click also does), `↑` `↓` move, `PgUp`/`PgDn`
  and `Home`/`End` jump, `e` opens everything, `c` goes back to the defaults, `r` fetches again, and `Esc`, `q` or
  `Ctrl+K` close. Open and closed rows are remembered by node `id` across refreshes within one opening, and forgotten
  when the viewer closes.
- **History reduction.** When the server shortens the history it sends (docs/HISTORY.md), the viewer shows what
  the model gets: old turns marked `(trimmed)`, the digests of the oldest turns as one purple `digest` block, and a
  second header line "History reduced: N turns as digests, M trimmed, ~K tokens saved".
- **Turn timings.** On a debug server, each finished turn ends with a dim line from `message_end.metrics`: time to the
  first visible text, total time, input tokens (with how many came from and went to the prompt cache), output tokens
  and the number of model calls. Servers without `metrics` print nothing.
- **Draft.** Opening and `r` send the text typed in the prompt so far (`draft`), so the briefing preview matches what
  the next message would bring in. The prompt itself is not changed.
- **Errors.** A `404` (a server restarted without `--debug`) shows "This server does not offer the context view.
  Start it with: aigm --debug"; other failures show the error text in the viewer.
- **Code.** `context_model.py` is pure (the tree, collapse state, cursor, and the colored lines for a width) and has
  its own tests; `context_screen.py` holds the thin Textual widgets; `ApiClient.context(draft)` makes the call. Unknown
  node kinds are shown as plain text.

### Rebuilding the transcript from `/chat/history`

History is Anthropic content blocks. Mapping to display blocks:

- `user` + `text` → "You:" block.
- `assistant` + `text` → markdown block.
- `assistant` + `tool_use(roll_dice)` → the call's `narration` as a markdown block (as it was shown live), then, paired
  with the following `tool_result`, a compact dice line using the result string (the structured `dice` data is **not**
  stored in history, so historical rolls show less detail than live ones).
- `thinking` / `redacted_thinking` blocks → skipped.
- `tool_result` with `is_error: true` → short dim "roll failed" line.

## Streaming Markdown (the key requirement)

Streaming chunks arrive mid-word and mid-construct (`**bo`, `` ``` ``, `[link](htt`). Naively rendering each chunk as it
arrives is wrong; naively re-parsing the buffer is *almost* right but flickers. The approach:

1. **Never render chunks; render the accumulated text.** Each markdown segment keeps its full raw text. On every update
   (coalesced to ~30 fps) the whole segment is re-parsed and re-rendered. Raw text is never mutated, so the final render
   after `message_end` is always identical to rendering the complete reply in one shot.

2. **Heal a copy for display (`heal.py`).** A CommonMark parser treats an unclosed `**` as literal asterisks until the
   closer arrives, so the user would see `**bol` flash and then snap to **bol**. Before rendering, apply a pure function
   `heal(text) -> text` to a *copy* that provisionally closes constructs still open at the end of the buffer:
   - Unclosed fenced code block (` ``` ` or `~~~`): append the closing fence. Inside a fence, **no other healing is
     applied**.
   - Unclosed inline code span (odd number of backticks on the last line): append a backtick.
   - Unclosed emphasis (`*`, `_`, `**`, `__`, `~~`): append the matching closers in reverse order, tracking nesting;
     ignore `_` inside words and `*`/`_` used as list bullets or in math-like text (`2 * 3`).
   - Dangling link/image: `[text](partial-url` renders as just `text`; a bare trailing `[` or `![` is dropped.
   - Dangling trailing marker characters that can't yet be classified (a lone final `*`, `` ` ``, `#`, `>`, `-`, or
     digits followed by `.`) are **held back** from display until the next chunk disambiguates them (they are still in
     the raw text).
   - Headings, lists, blockquotes need no healing; line-level constructs parse correctly on the partial line.

3. **Only the tail is volatile (optimization deferred in v0.1).** Split a segment into top-level blocks (paragraphs,
   lists, fences, tables) separated by blank lines outside fences. All blocks except the last are *settled*: rendered
   once per terminal width and cached. Only the last block would be re-parsed per update, keeping long replies cheap.
   *v0.1 simply re-renders the whole segment on each (30 fps-coalesced) update, which is fast enough for
   narrative-length replies; per-block caching is deferred because splitting a list or numbered list across blocks
   changes how it renders.*

4. **Known, accepted wrinkles.** A table appears as plain text until its header-delimiter row arrives, then reflows to a
   table. Setext headings (`Title` then `===`) reflow when the underline arrives. These are inherent to streaming
   markdown and are minor for narrative GM output.

5. **Renderer.** Rich's `Markdown` (markdown-it-py underneath) rendered through `Console.render_lines()` at the current
   viewport width, producing exact lines (lists of styled segments). Exact line counts are what make paging possible;
   Textual's own `Markdown` widget has no line-level control, so it is not used for the transcript.

### Tests for this (most important test suite)

- **Split-point fuzz**: for a corpus of GM-style markdown (bold/italics/nested, lists, headings, code fences, inline
  code, links, tables, blockquotes, emoji), feed the text in at *every* split point and char-by-char; assert (a) no
  exceptions, (b) the render after the final chunk equals the one-shot render, (c) healed intermediate renders never
  contain literal unmatched `**`/`` ` ``/`~~` that the full text would show as formatting.
- **Heal unit tests**: table of `(partial input → healed text)` cases including negatives (`2 * 3 = 6`,
  `snake_case_name`, `5 * 4 * 3`, a lone `*` bullet, fences containing `**`).
- **No-regression of settled blocks**: lines of settled blocks are byte-identical across updates (so the screen doesn't
  jitter).

## Dice Rendering

`dice_roll` renders as one compact, styled block between markdown segments (a `tool_call`/`dice_roll` ends the current
text segment, so the model's text before and after a roll are separate paragraphs; this is acceptable for v0.1):

```
  🎲 4d6kh3+2  →  [1] [6] [1̶] [3]  +2  =  12
```

- Use the structured `dice` array: kept dice shown normally, dropped dice dim and struck through.
- `crit: "crit"` is green/bold, `crit: "fail"` is red/bold; `total` is bold.
- If `dice` is empty (e.g. `5+3`) or the field is missing, fall back to the server's markdown `result` string.
- Emoji prefix is configurable off (`--ascii`) for terminals that render it poorly.

## Pager (page-at-a-time display)

### Model

`transcript.py` owns:

- `blocks`: the ordered block model (user lines, markdown segments, dice blocks, errors, system notes).
- `lines`: the flattened rendered lines for the current width. Settled blocks are cached; the last block is re-rendered
  on update. Re-rendered on terminal resize.
- Pager state:
  - `page_start`: index of the first line of the current page.
  - `page_height`: visible rows of the transcript view (viewport height minus the pager bar row).
  - `revealed_end = min(len(lines), page_start + page_height)`: lines the user may see. Lines at or beyond it are
    **held**.
  - `held = len(lines) - revealed_end` (drives the "MORE (N lines buffered)" indicator).

### Behavior

1. **Continuous flow.** The conversation is one unbroken stream: the user's own message is echoed into the transcript
   (styled distinctly, with a blank line before and after) **between** GM replies, and the next reply continues directly
   below it. Nothing is cleared when a message is sent. The pager does not reset on send: new lines fill whatever room
   is left on the current page, and only when the page is full does the pager hold the rest. (If the page happens to be
   exactly full when the user sends, sending counts as the user's page turn: `page_start` moves to the echoed message.)
2. As events arrive, lines are appended and reveal up to `revealed_end`; the view shows the page top-down (anchored at
   `page_start`), so text visibly fills the page.
3. When `held > 0`, the pager bar shows **MORE**. Incoming events keep being applied to the model; nothing is dropped or
   delayed on the network side.
4. **Advance** (Space, Enter, PageDown, or a mouse click on the transcript): the new page starts **three lines before**
   the end of the old one (`page_start = revealed_end - 3`, fewer on tiny screens), so the last three lines you read
   lead the new page for continuity. The view does a quick 150 ms ease-out slide from the old page to the new one rather
   than jumping; the sliding window never extends past the new page, so held lines are not revealed early. Repeats until
   `held == 0`.
5. When `held == 0`, the stream is finished (`message_end`/`error`), and the user has paged through everything, the
   input prompt is shown and focused.
6. The last, partial line of the stream is revealed as it grows. Only the tail block can change, so earlier lines never
   move. If a tail reflow pushes a line past the page boundary, that line becomes held again; since the user is still on
   the same page, nothing they have already read is retracted.
7. Resize: re-render lines at the new width, then recompute `page_start` by keeping the same *source block and offset*
   so the user does not lose their place.

### Scrollback

- `PageUp` / `PageDown`(when not paging) / `↑` `↓` / mouse wheel / `Home` scroll freely through **revealed** content
  (everything before `revealed_end`), including history from earlier turns. Held lines cannot be scrolled into; that
  would defeat paging.
- While scrolled back, the view does not jump when new lines arrive; the pager bar adds "(scrolled back, `End` to
  return)".
- `End` jumps back to the current page. `Space`/`Enter` while scrolled back first returns to the current page, then a
  second press advances.
- Scrollback holds the whole session in memory in v0.1 (no cap; history overflow is a server-side later milestone as
  well).

### Key bindings

| Key | Action |
|---|---|
| `Space`, `Enter`, `PageDown` (when held lines exist), click | Advance one page (while held text exists; the input is hidden then, so these keys never type) |
| `↑` `↓` `PageUp` `PageDown` `Home` `End`, mouse wheel | Scrollback. While scrolled back the prompt is disabled so `End`/`Space`/`Enter` act as page keys; `End` or `Space` returns to the current page |
| `Esc` | Cancel the in-flight turn (or cancel a confirmation) |
| `Ctrl+S` / `F2`, `Ctrl+O` / `F3`, `Ctrl+N` / `F4` | Save, Load, New game dialogs |
| `Ctrl+T` | Toggle display of reasoning text (hidden by default) |
| `Ctrl+K` | Open or close the context viewer (debug servers only; not bound otherwise) |
| `Ctrl+Q` / `/quit` | Quit |

### Input gating

The input box is only shown when (a) no turn is in flight (`message_end` or `error` received) **and** (b) `held == 0`.
This guarantees Space/Enter are page keys while text remains and typing keys are never swallowed mid-page, and it also
prevents sending a second `/chat` during a turn (the server would return 409). Typed text is not accepted while gated;
there is no type-ahead in v0.1. The save/load/new shortcuts and the footer are *not* gated by held text (only by an
in-flight turn), as described above.

## Error Handling

- **Server unreachable / connection dropped mid-stream**: show an error block, discard nothing already displayed,
  re-enable input. Because the server rolls back the turn, annotate the partial text as interrupted.
- **Malformed SSE data** (bad JSON): skip the event and log at debug level; continue the stream.
- **Stream ends with no terminal event**: treat as an error with "connection closed unexpectedly".
- **Slash command errors**: always shown as a system line, never a crash.

## Testing Strategy

- `test_sse.py`: parser against golden byte streams, including chunk boundaries that split a line, `\r\n` line endings,
  multi-line `data`, comments/pings, and unknown events.
- `test_heal.py` and the split-point fuzz (above).
- `test_transcript_pager.py`: deterministic simulation: append lines to a transcript with a given `page_height`; assert
  held counts, advance behavior, scrollback bounds, resize anchoring, and that the stream is never blocked by a held
  page.
- `test_commands.py`: parsing and endpoint mapping using `httpx.MockTransport`.
- `test_dialogs_pilot.py`: save (new name; `409 already_exists` -> overwrite confirm -> `overwrite=true`), load
  (preview, dirty warning, transcript rebuilt, last page shown), delete from the load dialog, new game (dirty vs clean,
  `Save first...` chaining), shortcuts disabled with a hint while a turn is in flight, and `dirty`/`*` transitions.
- `test_app_pilot.py`: Textual `Pilot` end-to-end against a fake server (an ASGI app replaying scripted SSE): page fills
  → MORE appears → Space advances → input appears at the end.
- Manual smoke test against the real backend with `curl -N` side by side.

## Build Order

1. Scaffolding: `client/` uv project, package, `python -m aigm_client` launches an empty Textual app, `/health` check.
2. `sse.py`, `events.py`, `api.stream_chat()` with tests (no UI).
3. `heal.py` plus the split-point fuzz suite (the riskiest piece; do it early).
4. `blocks.py` and `transcript.py` (rendering to lines, pager state machine) with tests.
5. `widgets.py`: `TranscriptView` drawing lines, pager bar, scrollback, key bindings.
6. Wire chat: input, worker, event application, thinking spinner, dice blocks.
7. Save / Load / New-game dialogs (`dialogs.py`), dirty tracking, shortcuts and footer; slash commands; history
   repopulation.
8. Polish: resize handling, cancel, error cases, `--ascii`.

## Known Limitations / Future Work

- No type-ahead and no editing of past messages.
- Long sessions keep everything in memory; scrollback is uncapped.
- Text before and after a dice roll appear as separate paragraphs because the roll splits the segment.
- Historical dice rolls (after `/load` or restart) have less detail than live ones because structured roll data isn't
  saved in history.
- Single session at a time (the `--session` flag selects which); no session switcher UI.
- Web or richer GUI front end is a likely later step; the pure-logic modules (`sse`, `heal`, pager rules) document
  behavior a TypeScript client would need to reimplement.

## Open Questions

None outstanding. Settled decisions: replies flow continuously with the user's messages echoed between them; reasoning
text is hidden by default; Space and Enter both advance a page.
