# AIGM History Reduction: Options

Status: **options A, B and E are implemented** (sections 10 and 11). The rest of this document is the brainstorm
they came from; C, D, F, G, H and I are still open ideas. It builds on [BACKEND.md](BACKEND.md) (turn loop),
[WORLD.md](WORLD.md) (the world store and briefing) and [CONTEXT.md](CONTEXT.md) (the viewer we can measure with).

## 1. The problem

Every request resends the whole conversation: the system prompt, the tools, and every earlier message of the
adventure. A long campaign therefore gets slower and more expensive with each turn, even though most of what is
resent is old and rarely needed. Three costs grow with the history:

- **Latency.** Time to first token rises with input length, even on a cache hit (cached tokens are cheaper, not free).
- **Money.** Input tokens are billed on every request. A turn that uses tools makes several requests (one per
  model call in the tool loop), and each one resends the full history.
- **Quality.** Very long contexts dilute attention. Old, superseded details compete with the current scene, and
  the model can lean on stale facts instead of the briefing.

## 2. Where the tokens go (to measure, not assume)

I have not measured a real campaign. The expected shape of one request, largest first:

1. **Assistant narration.** The GM writes pages per turn, and all of it is kept. Probably the bulk of the history.
2. **Thinking blocks.** Stored verbatim (with signatures) and sent back. Their size depends on effort. Whether the API
   charges for earlier turns' thinking depends on the model, so this must be checked, not assumed.
3. **Tool traffic.** `tool_use` and `tool_result` pairs for dice and the like. Small each, but frequent in combat.
4. **Fixed cost.** The system prompt (about 3.5 to 5k tokens per ruleset, see [RULESETS.md](RULESETS.md)) plus the tool
   schemas. This does not grow, but it is paid every request.
5. **The briefing.** Capped by `AIGM_WORLD_BRIEFING_TOKENS` (2000), appended to the last user message. Not history.
6. **Player messages.** Short.

Step 0 below is to find out the real split. The context viewer already estimates it per node.

## 3. What already helps

- **Prompt caching.** `request_params` puts a cache breakpoint before the briefing, so the history prefix is
  read from cache on later requests. This cuts cost and latency a lot, but the history still has to be
  *processed* when the cache is cold, still counts against rate limits, and still grows without bound.
- **Session 0 compaction.** `begin_adventure` already replaces the whole Session 0 history with a campaign record. This
  is a working precedent for "replace old messages by a distilled record".
- **The world store.** The curator keeps facts (places, characters, clock, threats) outside the history and injects
  the relevant ones as the briefing. That is what makes it *safe* to shorten the history: the facts that matter
  are not only in the old messages any more.

## 4. The catch: caching limits what we can edit

Caching matches an exact prefix. Changing anything early in the request invalidates the cache from that point
on, and the next request pays to write the whole prefix again (cache writes cost more than ordinary input, reads
cost far less). The cache also expires after a few minutes idle (5 by default, with a longer TTL available at a
higher write price), which a slow player will hit regularly.

This rules out the obvious trick. **A sliding window that drops the oldest message every turn changes the start of
the history every turn, so it never hits the cache.** It can cost more than doing nothing. Every option below
must be judged on this: it should leave the prefix *byte-identical* for as many consecutive requests as possible.

The pattern that works is **batching with hysteresis**: let the history grow to a high-water mark, then shrink it
in one step to a low-water mark, and leave it alone until it grows back. The cache is rewritten once per
shrink, not once per turn. For example: compact when history passes 40k tokens, down to 12k. That is a
rewrite every 25k or so of growth, which is several dozen turns.

## 5. Options

They are not exclusive. Section 6 combines them.

### A. Measure first

Log the real numbers, so every later choice is grounded.

- Per request: input, output, cache read and cache write tokens (the client already logs this line; make it structured
  and add the turn number and phase).
- Per node breakdown from the context viewer: share of system, tools, narration, thinking, tool traffic.
- Time to first token, and how it correlates with input size and cache hit.

Cost: small. Risk: none. This is a prerequisite, not an alternative.

### B. Trim what the model barely needs from old turns

Keep the messages, drop the dead weight inside them.

- **Old thinking blocks.** Strip them from turns before the current one, if the API allows it for the model in
  use. (There may be a constraint that thinking blocks must be passed back unmodified within a tool loop, so only
  turns that are complete would be trimmed. To verify against the API docs.)
- **Old tool traffic.** A dice roll's `tool_use`/`tool_result` pair can become one line of text ("Rolled 1d20+5 for
  the attack: 17"), or disappear when the narration already states the outcome. Pairs must stay balanced, or the API
  rejects the request, so remove both halves together.
- **Anthropic's server-side context editing** (clearing old tool results and thinking automatically) does the above
  without our code. It is a beta feature, so check availability on the account and model before relying on it.

Pros: no summarizing model, no lost narration. Cons: the gain may be modest if narration dominates; any edit to an
old turn is a cache break, so do it in the batched step, not per turn.

### C. Sliding window with a note

Keep the last N turns verbatim; drop everything before; rely on the world store and briefing for what was lost.

- Simplest to build. Cheapest at runtime. Hard cap on size.
- Lossy in the worst way: anything that never made it into the world store is gone, including *voice* (how the
  GM spoke earlier) and promises ("the blacksmith owes you a favor").
- Needs hysteresis (section 4), and the window must start on a user message so the alternation stays valid.

Probably only acceptable if combined with D or E.

### D. Rolling summary ("story so far")

When the history passes the high-water mark, summarize the oldest part into one block and keep the recent tail
verbatim. The summary sits at the start of the history, as a user-visible-to-model note, like the campaign record.

- **Who writes it:** a cheap model (Haiku, like the curator), in the background after a turn, so the player never
  waits. The result is applied at a safe point, as curator results are today (`drain_pending`).
- **Folding:** each compaction takes the previous summary plus the newly aged-out turns and produces a new
  summary of similar size, so the size stays bounded. Repeated folding drifts and loses detail, so the world store
  remains the long-term memory and the summary is only the narrative thread.
- **Anthropic's server-side compaction** does this inside the API. Simpler and cached for us, but we control
  less of what is kept, and the summary would not be in our saves or the context viewer unless we capture it.

Pros: preserves the story's thread, bounded size, good fit with the existing background-job design.
Cons: a new prompt to get right; lossy; errors in a summary become "history" the GM trusts.

### E. Per-turn digests

Instead of one big summary, give every GM turn a short digest (one or two sentences: who, where, what changed,
what was promised), written once when the turn is curated. When the history passes the mark, aged-out turns are
*replaced by their digests* (in one batch), while the last K turns stay verbatim.

- Each digest is written once and never re-summarized, so there is no drift from folding.
- Granular: a digest can be dropped, merged or kept when space is tight, and it is checkable.
- Can ride on the existing curator call (it already reads each stretch of narration), so the marginal cost is low.
- The digest log is also the substance of a "recap" feature and a reasonable save-file field.

Cons: more bookkeeping (which turns are digested, which are verbatim); the digest list itself grows, slowly, so
eventually it needs grouping into chapters (F).

### F. Chapters (hierarchical summaries)

Combine D and E over scene or session boundaries. Digests cover the recent past, scene summaries the middle,
chapter summaries the far past. The GM could mark a boundary with a tool (`end_scene`), or the curator could detect
it (a location change plus a time jump). This is the most scalable and the most work. Treat it as a later
refinement of E, not a first step.

### G. Retrieval instead of retention

Treat the full transcript as an archive on disk and pull old passages back in when relevant, the way the briefing
pulls in world facts. The curator already matches names mentioned in the player's text and the last reply
against the world, so the same trick could match old digests or passages.

Pros: nothing is truly lost; the context holds only what the scene needs. Cons: retrieved text lands in the
briefing, which is the uncached tail, so it costs full price every turn; retrieval misses are silent; most
complex. The world store plus E gets most of the value more simply.

### H. Reduce what is added each turn

Shrink the growth rate instead of pruning later.

- **Narration length.** The prompt can ask for tighter turns outside set pieces. This trades the "pages of prose"
  experience, which the user may value; a product decision, not a technical one.
- **Fewer model calls per turn.** The tool loop resends the history on every call. Rolling several dice in one
  call, which the dice prompt already allows, cuts requests, and so cuts the repeated input cost.
- **Thinking effort.** Lower `AIGM_EFFORT` on routine turns means smaller thinking blocks and faster replies.

### I. Make the fixed part cheaper

Not history, but it is paid on every request.

- Use the longer cache TTL for the system prompt and tools, so a slow player does not pay the rewrite.
- Trim prompt files that repeat each other (the viewer's token counts show which are large).
- Offer tools only in the phases that need them (already done for `set_ruleset`).

## 6. Suggested direction (taken: A, then B, then E)

Build in this order, stopping when the numbers say it is good enough:

1. **A: measure.** Structured usage logging and a baseline from a scripted long campaign.
2. **B: trim old thinking and dice traffic**, in the same batched step as the rest. Cheap, lossless for the story.
3. **E: per-turn digests with high/low watermarks.** Last K turns verbatim, older turns as digests, one cache
   rewrite per compaction. Digests are produced by the curator's existing background pass.
4. **Later, if needed:** F (chapters) when the digest list itself gets long, or the API's server-side
   compaction if it proves good enough that owning this code is not worth it.

C alone is rejected as too lossy, and G is deferred because its cost lands on the uncached tail.

Why E over D: it needs no repeated re-summarizing, a bad digest damages one turn rather than the whole past,
and it keeps what the player sees in the transcript untouched.

## 7. Design constraints for any option

- **Transcript and model context become two things.** The client shows the full adventure (`/chat/history`); the
  model sees a reduced view. Today one message list serves both (to verify). The reduced view should be *derived*
  (full transcript plus digests and watermarks), never a destructive edit of the transcript, so a bad compaction
  can be undone and the player never loses their story.
- **One source of truth.** The reduction must live in `Game.describe`/`RequestDescription`, so the context viewer
  shows the reduced history automatically, with digests and summaries as their own colored nodes.
- **Valid message structure.** Messages alternate roles, every `tool_use` has its `tool_result`, and the reduced
  history must start with a user message. A test should check this for every reduction.
- **Atomic and rollback-safe.** Compaction commits with the turn, like curator ops. A failed turn changes nothing.
- **Cache-stable.** Between compactions the history prefix is identical request to request. A test should assert it.
- **Saves.** New fields (digests, watermark position) must be optional, so old saves load unchanged as "no
  reduction yet", and the save version stays compatible.
- **Config.** High-water mark, low-water mark, verbatim tail length (K), and an off switch, in the style of the
  existing `AIGM_*` settings. Off must mean exactly today's behavior.

## 8. How we would know it works

Cost and speed are easy to measure. Quality is the real risk, so the spec needs an evaluation:

- **Cost and latency:** the step A numbers before and after, over the same scripted 100-turn campaign.
- **Continuity probes:** after compaction, ask the GM about early facts (a name, a promise, an item, an NPC's
  attitude) and score whether it answers consistently. Plant these facts at known turns.
- **Voice:** compare a few turns before and after for tone and period flavor (the ruleset's era feel lives in the
  system prompt, so it should survive, but the verbatim tail carries style too).
- **No regressions in rules:** the system prompt and ruleset are untouched, so mechanics should not change; the
  probes should include "what is my AC / HP / inventory", which must come from the character sheet and notes.
- **Test mode:** the scripted client can generate long histories without an API key, for the structural tests.

## 9. Open questions (asked before building; see 11 for what was decided)

1. What matters most to you: the bill, the delay, or the long-campaign quality? It changes how aggressive the
   compaction should be.
2. How much of the *voice* of earlier narration must survive verbatim? That sets K, the tail length.
3. Is a lossy past acceptable if the full transcript stays on screen and on disk, or must the model be able to
   recover anything from the full text?
4. Are Anthropic's server-side compaction and context editing acceptable (less code, less control), or do we want
   the reduction in our own code, visible in the context viewer and our saves?
5. Should the GM have a way to ask for older detail (a `recall` tool that fetches a passage or digest)? It is
   a cheap form of G, and the model decides when it needs it.
6. Should the player see compaction happen (a status line like world preparation does), or should it be silent?

## 10. What was built

### A. Measurements

Every finished turn produces one record (`metrics.py`), sent on `message_end.metrics` (API.md), logged, and appended
to `{AIGM_SAVE_DIR}/metrics/{session}.jsonl` (`AIGM_METRICS=false` turns the file off). It holds, per turn and per model
call:

- **Token use** from the API: input (everything read), uncached input, cache reads, cache writes, output.
- **Time to the first visible text**: from the start of the call (and, for the turn, from the start of the turn) to the
  first `text` chunk. Thinking is not text, so it does not end this clock. `thinking_ms` is reported next to it, so
  `first_text_ms - thinking_ms` is the wait that is not thinking.
- **Total time** of each call and of the turn, plus `pause_ms`, the deliberate pause before dice rolls, so it can be
  subtracted.
- **Request sizes** (estimated tokens): system prompt, tools, history as sent, history as stored, the briefing, and the
  history split by kind (`player`, `gm`, `digests`, `thinking`, `tool_calls`, `tool_results`). This is the answer to
  "where do the tokens go", per request.

A debug server's client prints a dim line after each turn (CLIENT.md).

**First look at a real save** (a 66-turn game, 394 messages, estimated tokens, thinking signatures excluded because
they are opaque data about five times the size of the thinking text): the stored history is about 107k tokens, of
which GM narration 47k, thinking 30k, tool calls and results 27k, player messages under 1k. Trimming alone at the
defaults brings it to about 80k (thinking 3k; tool calls and results are kept, see B), and digests would replace
most of the narration older than the newest 12 to 23 turns. These are estimates (characters divided by
four); the metrics file has the real token counts from the API for new turns.

### B. Trimming old turns

Thinking blocks of old turns are dropped. Tool calls and results are kept exactly as stored. The first version also
folded each call and result into a text note in the GM's message, such as `(Rolled 1d20+5: 1d20 (13) + 5 = 18)`.
In play the model copied the notes and began printing roll summaries itself instead of calling `roll_dice`, so the
folding was removed. Any future compaction of tool traffic must not leave text that looks like a roll or a call.
Applied only to turns older than the trim cut, never to the turn in progress.

### E. Digests

The curator pass writes a digest per finished turn (WORLD.md 4.7). Turns older than the digest cut are shown as their
digests, in a single `<story_so_far>` block at the front of the oldest turn still shown in full. A turn without a
digest is shown in full, and the cut waits at it.

A digest only counts when it covers exactly the turn's messages (`start` and `end`). If a save is edited so a turn gains
or loses messages, its digest goes stale and the cut would wait at that turn for good, because the turn would show no
usable digest. The curator treats such a turn as undigested and its new digest replaces the stale one (and any other
digest that overlaps the turn). A real save with one stale digest at turn 78 kept 40 turns in full (about 100k tokens
per request) until this was fixed.

### Stored in full, shown reduced

The messages are never edited or dropped. Digests are saved in `world.digests` (a list of
`{start, end, turn, text, chars}`) inside the same save file that holds all the original messages, and in the live
session state. Which turns are condensed is decided at request time from the turn count and the settings, so:

- changing `AIGM_HISTORY_DIGEST_KEEP`/`_STEP` or `AIGM_HISTORY_TRIM_KEEP`/`_STEP` changes what an *existing* save
  shows the model from the next request on, without touching the save;
- an old save without digests works as before until the curator has written some (a few passes), and then ages out
  gradually;
- setting both `AIGM_HISTORY_*` switches to `false` restores the old behavior exactly, and the context viewer shows
  the difference (`reduction` in the response, API.md).

### Cache behavior

Both cuts are functions of the turn count that move every `*_step` turns (`history.cut`). Between moves the request
prefix is identical, and a test checks that over 80 turns. A move rewrites the cache from that point on, so with the
defaults (trim every 6 turns, digest every 12) the history is rewritten about every 6 turns instead of every turn. The
steps are the knob: larger steps mean fewer rewrites and more history shown in full on average (the verbatim
tail is between `keep` and `keep + step - 1` turns).

### Tests

`test_history_reduce.py` (cuts, trimming, digest bands, structural validity of every reduction, prefix stability),
`test_digests.py` (storage, saves, the curator stage, catch-up, failures), `test_metrics.py` (the clocks, token
sums, the file), `test_history_integration.py` (what the model is sent, the viewer, test mode end to end), and
`test_history_display.py` in the client.

## 11. Decisions and what is still open

Decided with the user before building:

1. Build A (measure), B (trim), then E (digests), in that order.
2. For E, keep **both** the original text and the digest in the saved state and the save files, so the age-out
   threshold can be adjusted on older saves without harming play.
3. Measure token usage, **time until the first visible streaming text** (thinking blocks do not count as text), and
   total time.

Choices made while building:

- The first turn (the campaign record) is never digested or trimmed.
- Digests are written by the extraction model with the existing pass, not by an extra background job, and they are
  produced for every finished turn, not only those about to age out, so a curator that lags never delays the cut.
- The cuts are turn-based. A token-based cut adapts better to very long or very short turns; it needs state to stay
  cache-stable and was left out.
- Defaults (trim keep 4 / step 6, digest keep 12 / step 12) are a first guess. Use the metrics file to tune them: look
  at `cache_write_tokens` against `history_stored`.

Still open, to check against real play:

- **Thinking blocks.** Dropping the thinking of finished turns is valid for the API as I understand it, but if a model
  or beta treats earlier thinking as bound to its conversation, look at `cache_write_tokens` and quality after a trim
  cut, and set `AIGM_HISTORY_TRIM=false` if it hurts.
- **Digest quality.** The prompt (`prompts/world/digest.md`) has not been run against a live model. Check that names,
  promises and items survive; a bad digest affects one turn.
- **Style carry-over.** Old GM prose is replaced by digests, so the voice of the newest `digest_keep` turns is all the
  model sees. Raise `AIGM_HISTORY_DIGEST_KEEP` if the tone drifts.
- Options C, D, F, G, H and I above, and the `recall` tool for older detail (question 5), were not built.
