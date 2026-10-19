# Streaming roll narration (spec)

Status: proposed. Nothing in this document is implemented yet. It builds on the roll `narration` field (BACKEND.md,
Tools, `roll_dice`; API.md, Tool: `roll_dice`).

## 1. Problem

Every `roll_dice` call carries a `narration`: the lines the player reads just before the dice land. Today the server
shows it only after the model has finished its whole response, because it lives inside a tool call and the loop runs
tool calls after the response completes. The player sees the GM stop, wait through the rest of the generation, and then
get the narration in one piece, followed at once by the dice. That breaks the rhythm of the game, which depends on text
arriving as it is written.

Plain reply text already streams word by word. The goal is for the narration inside a tool call to stream the same way,
so a roll feels like ordinary narration that happens to end in dice.

## 2. Goals and non-goals

Goals:

- Narration streams to the player as the model generates it, as ordinary `text` events, in order with the rest of the
  GM's text.
- The dice appear after the narration has finished, with the existing roll pause between them.
- Time to first visible text counts the first narration characters (the metrics already measure first visible text;
  thinking does not count).
- Nothing the model wrote is lost, shown twice, or shown for a turn that is rolled back differently from today.
- The whole path works in test mode (no network), so it is covered by tests.

Non-goals:

- No new SSE event type and no client protocol change (section 7).
- Not streaming any other tool's input. `establish` and `set_scene` are bookkeeping and stay as they are.
- Not changing what the model is asked to write. The prompts and the `narration` field stay as they are, apart from
  the field order (section 5.3).

## 3. What the API gives us

Facts about the Messages API, checked against the installed SDK (`anthropic` 1.15):

- A tool call streams as `content_block_start` (a `tool_use` block with its `id` and `name`, input empty), then any
  number of `content_block_delta` events whose delta is an `input_json_delta` with a `partial_json` string, then
  `content_block_stop`. The SDK surfaces the deltas as `input_json` events (`partial_json` and a `snapshot`, the
  tolerant parse of everything so far).
- **By default the API buffers and validates each parameter** before it sends any delta for it. A `narration` string of
  a few hundred characters would arrive in one or two bursts, not as a stream. Setting `eager_input_streaming: true` on
  the tool turns that buffering off: fragments arrive as they are generated. The tool param type in the SDK has the
  field.
- The price of eager streaming is that the API no longer guarantees the JSON is valid. The accumulated input can be cut
  off at `max_tokens` or malformed, and the SDK's final parse of it is tolerant, so bad input may come back as a
  silently truncated object. So the server must validate the input itself before running the tool, check the stop
  reason, and handle the SDK's `ValueError` for JSON it cannot parse at all.
- Fragments are arbitrary pieces of the JSON text. They can end in the middle of an escape sequence (`\` then `n`, or
  half of a `\uXXXX`), in the middle of a key, or between a key and its value.

Not yet verified (the spike in section 9 settles these first): that the model in use accepts the field, how fine the
fragments are in practice, and whether they stream in the order the schema lists the properties.

## 4. Design overview

```
 Anthropic stream
   content_block_start (tool_use roll_dice)  ->  ToolInputStarted(id, name)
   input_json_delta  x N                     ->  ToolInputChunk(id, partial_json)
   content_block_stop                        ->  ToolInputStopped(id)
          |
          v
   run_turn (llm/loop.py): one NarrationStream per roll_dice call
          |  decoded narration text, as it arrives
          v
   TextDelta events  ->  SSE `text`  ->  client (unchanged)
          ...
   Completed -> validate -> dispatch tools -> dice_roll events (after the narration, after the pause)
```

Three pieces:

1. **LLM layer** (`llm/base.py`, `llm/anthropic_client.py`, `llm/scripted.py`): three new normalized events and the
   `eager_input_streaming` flag on the roll tool.
2. **`NarrationStream`** (new, `llm/narration.py`): a pure incremental extractor that turns `partial_json` fragments
   into the decoded text of the top-level `narration` string.
3. **The loop** (`llm/loop.py`): feeds fragments to the extractor, yields `TextDelta`s, remembers how much of each
   call's narration was already shown, and does not show it again at dispatch.

### 4.1 New LLM events

```python
@dataclass
class ToolInputStarted:
    tool_use_id: str
    name: str

@dataclass
class ToolInputChunk:
    tool_use_id: str
    partial_json: str

@dataclass
class ToolInputStopped:
    tool_use_id: str
```

The loop ignores them for every tool except `roll_dice` (the set of streamed tools is a constant in the loop, so a
future tool can opt in). The Anthropic client tracks the block index to tool id mapping from `content_block_start`.
Events for tools that are not streamed may still be emitted; they are cheap.

### 4.2 What the loop does with them

Per model call, a dict maps `tool_use_id` to a `Narrating` record: the extractor, the number of characters already
shown, and a flag that the call's block has stopped.

- On `ToolInputStarted` for `roll_dice`: create the record.
- On `ToolInputChunk`: feed the extractor. For each piece of decoded text it returns, yield `TextDelta`. The first
  piece of a call is preceded by a paragraph break (section 5.2). Update the first-text timings exactly as for a
  `TextChunk`.
- On `ToolInputStopped`: tell the extractor the input is complete. It releases any text it held back (section 5.2) and
  the loop yields the closing paragraph break.
- At dispatch, the existing `outcome.say` is shown only if nothing of that call's narration was streamed. This covers
  a client that never emits tool input events (the scripted client before it is updated, or any future client) and an
  extractor that gave up on malformed JSON, with no change in behavior from today.

The `tail` bookkeeping that keeps paragraphs apart (last two characters of text shown) is shared by the text path and
the narration path.

### 4.3 When the dice are shown

Phase 1 (this spec's required scope): tool calls still run after the response completes. For a single roll that is
exactly right: the narration streams, the model ends its response a moment later, the pause runs, the dice appear.

For a response with several rolls (an attack and its damage) the order the player sees is narration A, narration B,
dice A, dice B, because the dice are only shown once the response is complete. The prompts already ask for the first
roll's narration to set up the beat and for later dependent rolls to carry a short conditional line, so this reads
acceptably, and it matches today's order of reply text followed by dice.

Phase 2 (optional, decided after play-testing phase 1): run each `roll_dice` call as soon as its block stops, so the
order becomes narration A, dice A, narration B, dice B. This needs care:

- The roll runs on the loop's own parse of the accumulated JSON, validated the same way. When the response completes,
  the SDK's final block input must equal the input that was run. If it differs, the response is treated as failed
  (nothing is staged).
- The result is held and put into the tool result message in the original order after the response completes.
- Rolling only changes the dice, not the game state, so running early is safe. A turn that later fails still rolls
  back as a whole, as it does today. The player may have seen dice for a turn that is then discarded, as they may
  see text today.
- The roll pause then sits inside the stream consumption loop and holds the stream for about a second. It must not
  hold the stream so long that the connection times out. This needs a check in the spike.

## 5. The narration extractor

### 5.1 Contract

```python
class NarrationStream:
    def feed(self, partial_json: str) -> str: ...   # decoded narration text that is now safe to show
    def finish(self) -> str: ...                    # text still held back when the input is complete
    @property
    def failed(self) -> bool: ...                   # the JSON was malformed; nothing more will be produced
```

It is a pure, synchronous state machine: no I/O, no clock, no knowledge of the loop. Properties it must have:

- The concatenation of everything `feed` and `finish` return depends only on the full input, never on how the input
  was split into fragments. A test splits sample inputs at every possible boundary, and into single characters, and
  compares.
- It produces the decoded value of the top-level `"narration"` key only, and ignores every other key. Braces, quotes
  and the word `narration` inside other string values do not confuse it. A `narration` key nested in another object
  or array is ignored. A duplicate `narration` key marks the stream failed: `json.loads` keeps the last one, so the
  streamed text could differ from the validated input, and the loop falls back to validated dispatch.
- It decodes all JSON string escapes: `\" \\ \/ \b \f \n \r \t` and `\uXXXX`, including surrogate pairs split across
  fragments. A fragment that ends inside an escape is held until the escape completes.
- A `narration` value that is not a string produces no text.
- On malformed input (a bare control character is allowed; an invalid escape, text after the closing brace, and
  similar are not) it sets `failed` and stops producing text. What was already shown stays shown. Final validation
  at dispatch is unchanged and decides whether the roll runs.

### 5.2 Shaping the text

- **Leading whitespace** of the narration is held until the first non-space character, then dropped.
- **Trailing whitespace** is held back until a later non-space character shows it was inside the text; whatever is
  still held when the string closes is dropped. The player never sees trailing spaces.
- **Paragraph breaks.** Before the first character of a call's narration the loop emits `"\n\n"` unless the text shown
  so far is empty or already ends in a blank line. After the last character it emits `"\n\n"`. This is what the
  non-streaming version does today, so the output text is the same.

### 5.3 Property order in the schema

The model writes JSON keys in the order the schema lists them in practice. The `narration` property is therefore moved
before `expression` in the tool schema, and the field description says to write it first. If the model writes
`expression` first, nothing breaks: the extractor ignores it and starts streaming when `narration` begins, the player
simply waits through the expression. The change in the schema order does not change the stored history format.

## 6. Validation and failure handling

Eager streaming moves validation to us. The existing checks stay at dispatch, and these are added or confirmed:

- **Truncated or refused turns.** `stop_reason == "max_tokens"` or `"refusal"` with a `tool_use` block already ends
  the turn with an error and no tool runs (the loop's current "cut off mid tool call" check). The narration streamed
  before the cut stays on the player's screen, then the client shows the error and that the turn was discarded. This
  is the same as for streamed reply text today.
- **Unparseable JSON.** The SDK can raise `ValueError` from the stream iterator for input it cannot parse at all. The
  Anthropic client maps it to a retryable `LLMError` ("The model produced an unreadable tool call"), like other
  upstream failures. The turn is rolled back.
- **Silent truncation.** The SDK may return a truncated object instead of raising. The existing dispatch validation
  catches the realistic cases: a missing or short `narration` is refused, and an invalid `expression` is an error
  result.
- **Narration already shown, call refused.** If the call fails after its narration streamed (an invalid expression),
  the model is told so in the error result: "Your narration was already shown to the player. Call roll_dice again with
  the corrected expression and a one-line narration that does not repeat it." Today an invalid expression shows no
  narration at all, so this note is added only for calls whose narration was streamed.
- **Short narration.** The 10-character minimum is judged on the final input, after the text streamed. A refused short
  narration has already appeared; it is short by definition, so the cost is small.
- **Early stop.** If the stream is cancelled (the client disconnects), the turn is cancelled as today.

## 7. The client

No protocol change and no client change are needed. The narration reaches the client as ordinary `text` events:

- The client appends `text` deltas to the current markdown block, and it starts a new block after a `tool_call` or
  `dice_roll` event. The leading `"\n\n"` separates the narration from reply text in the same block, the trailing one
  closes its paragraph, and the following `dice_roll` ends the block.
- The `tool_call` event for the roll still arrives when the call is dispatched, after its narration, as today.
- History replay already shows the stored narration before the dice line (CLIENT.md, history replay).

A client test checks the sequence of blocks for text, narration deltas, `tool_call`, `dice_roll`, text. If the
play-testing shows that a client wants to tell narration from reply text (for example a different style), the way to
add it is a field on the `text` event (`"source": "roll"`), not a new event. That is left out of this spec.

## 8. Metrics

- `first_text_ms` (per call and per turn) is taken from the first streamed narration piece as well as the first
  `TextChunk`, so a turn whose first visible text is a roll's narration is measured correctly.
- A per-call `narration_chars` (characters of narration streamed) is added to the request record, so it is visible how
  much of the visible text came through tool input.
- No change to the token fields.

## 9. Spike first (before the implementation)

A throwaway script (not committed) calls the real API with the real roll tool schema and a prompt that makes the model
roll with a long narration. It records for each `input_json` event the time and the size of the fragment, with
`eager_input_streaming` off and on. It answers:

1. Does the model accept the flag? (A rejected request is a hard stop for this design: the fallback is in section 12.)
2. How fine are the fragments with it on and off? Streaming is useful only if the narration arrives in pieces of a few
   words, not one burst. The acceptance bar: with the flag on, the first fragment arrives within the model's normal
   time to first token and a 300-character narration arrives in at least 8 fragments.
3. Does the model write `narration` before `expression` when the schema lists it first?
4. For phase 2: whether holding the stream consumer for the roll pause (about a second) is safe.

Its measurements go into this document before the implementation starts.

## 10. Tests

Server:

- `NarrationStream`: every two-way split and the one-character split of a set of sample inputs give identical output;
  escapes including `é` and a surrogate pair split across fragments; other keys with braces, quotes and the word
  `narration`; a nested `narration`; a duplicate key; a non-string value; whitespace shaping; malformed input sets
  `failed` and stops output.
- Loop, with a scripted client that emits tool input events: the narration is yielded as `TextDelta`s before the
  `tool_call` and `dice_roll` events; it is yielded in more than one delta; it is not repeated at dispatch; the
  paragraph breaks are right with and without earlier reply text; first-text timing is set by the first narration
  piece; a client that emits no tool input events still gets the whole narration at dispatch.
- Failure: a call cut off after part of its narration ends the turn with an error and stages nothing; an invalid
  expression after streamed narration returns the "already shown" note; a short streamed narration is refused.
- Anthropic client with a fake stream: `content_block_start`, several `input_json_delta` events and
  `content_block_stop` become the three LLM events with the right ids; `ValueError` from the iterator becomes a
  retryable `LLMError`; the request carries `eager_input_streaming: true` on `roll_dice` and on no other tool.
- Test mode: the scripted `roll` and `multiroll` commands stream their narration in chunks (with `test_delay`), so the
  whole path runs without a network.

Client: the block sequence test of section 7.

Phase 2 adds: dice shown between narrations in a multi-roll response; a final input that differs from the one rolled
fails the turn; results still go back in the original order.

## 11. Documents to update with the implementation

- API.md: the `text` events and `tool_call` event for `roll_dice`; the note that narration streams.
- BACKEND.md: the three LLM events, the loop steps, the `AIGM_` settings if any are added (none are planned), and the
  roll tool's schema (`eager_input_streaming`, property order).
- CONTEXT.md: the tool schema shown in the viewer includes the flag.

## 12. Risks and fallbacks

| Risk | Effect | Fallback |
|---|---|---|
| The model rejects `eager_input_streaming` | No streaming from the API | Keep the buffered tool input; narration still shows at dispatch (today's behavior) |
| Fragments are too coarse even with the flag | Streaming looks like bursts | Same fallback; consider asking for the narration as ordinary text again (see below) |
| The model puts `expression` before `narration` | Narration starts late | Schema order and the field description; no correctness issue |
| Invalid JSON from the model | A turn fails or a roll is refused | Existing validation; retryable `LLMError` for unparseable input |
| Duplicate narration text (shown while streaming, then again) | The player reads it twice | The loop tracks shown characters per call; tested |

If streaming tool input proves too coarse or unreliable, the alternative that gets the same flow without it is to
make the model write the lead-in as ordinary reply text before the roll again, enforced by a server check that
discards a response which rolls before showing any text. That was the earlier approach. The prompt rule alone did not
hold up in play (rolls appeared with no lead-in, often in combat), and the check would cost a whole extra model call
each time it fires, which is why the narration was moved into the call. It is recorded here so the trade-off is not
lost.

## 13. Open questions

1. Phase 2 (rolls run when their block stops): wanted from the start, or only if multi-roll responses read badly in
   phase 1?
2. Should the client style roll narration differently from reply text (section 7), or is one voice right?
3. Should a refused short narration be allowed through when the roll is otherwise valid, since the player has already
   read it? It is simpler to keep the refusal, and the model then writes a longer one.
