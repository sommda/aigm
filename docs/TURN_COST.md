# AIGM Turn Cost and Speed

Status: **brainstorm, no code**. Part of the graphical app design; start with [APP.md](APP.md). A subscription product
lives or dies on cost per turn and on how fast a turn feels. This document starts from what the metrics show today,
lists the levers, and says what to build first. It extends [HISTORY.md](HISTORY.md) (which shrinks the history) and
depends on [CHOICES.md](CHOICES.md) (which changes the shape of a turn).

Numbers here come from `server/saves/metrics/default.jsonl` (504 recorded turns, the last 30 adventure turns used for
medians, with Haiku as the GM). They are one developer's play, not a population. Prices are deliberately not quoted:
fill in current prices in section 6.

## 1. What a turn costs today

Median of the last 30 adventure turns, with the worst case beside it:

| Measure | Median | Worst |
|---|---|---|
| Model calls per turn | 2 | 6 |
| Input tokens (all) | 69 k | 215 k |
| of which read from cache | 49 k | 169 k |
| of which not cached | 8.3 k | 25.8 k |
| Cache writes | 1.3 k | 38 k |
| Output tokens | 0.9 k | 3.3 k |
| Time to first narration text | 3.8 s | 16.7 s |
| Total turn time | 8.0 s | 27.5 s |

One typical three-call turn (turn 55), per request:

| Request | Input | Cache read | Uncached | Output | Thinking | Time | Ends with |
|---|---|---|---|---|---|---|---|
| 1 | 46.6 k | 41.5 k | 4.3 k | 0.67 k | 2.9 s | 4.3 s | tool call |
| 2 | 47.3 k | 42.3 k | 4.3 k | 0.65 k | 4.4 s | 5.4 s | tool call |
| 3 | 48.0 k | 43.0 k | 4.3 k | 0.94 k | 4.0 s | 6.1 s | final reply |

Recorded composition of each request (estimates in the metrics): system prompt 7.3 k, tool schemas 6.9 k, history sent
15 k of 35 k stored, briefing 2.8 k.

## 2. What the numbers say

1. **The number of model calls is the multiplier.** Every tool call is another full request that re-reads about 45 k
   tokens and re-pays the same ~4.3 k of uncached input. A turn with three calls costs about three times one.
2. **The first narration text arrives late** when bookkeeping comes first. The reply only starts after the model has
   made its `set_scene`, `update_character` and `recall` calls. Time to first text is 3.8 s at the median and 16.7 s
   at the worst, and the player stares at a spinner for it.
3. **Uncached input per request is a fixed ~4.3 k,** even when the history is cached. The briefing (2.8 k) sits after
   the cache breakpoint and is re-sent, and re-processed, on every request of the turn, including the continuation
   requests that follow a tool result.
4. **About 14 k of every request is fixed prefix** (system plus tools). It is cached, so it is cheap, but it is 30
   percent of each request and part of every cache write.
5. **Thinking costs seconds on every call** (about 3 to 4 s in the sample above). Over three calls that is more than
   half the turn.
6. **Output is the slow, expensive part per token,** and the narration is the output. A page of text per turn is not
   what a phone player wants anyway (CHOICES.md section 9).
7. **Rough weighting.** Using typical ratios (cache read about a tenth of base input, a five-minute cache write about
   1.25 times, output about five times; check the current price sheet), the median turn is about 19 k base-input
   equivalents: roughly 8.3 k uncached, 4.9 k for cache reads, 1.6 k for writes and 4.5 k for output. So the cache
   reads, which look large, are a quarter of the cost. **The uncached input and the output are the targets.**

## 3. Principles

1. **Fewer calls beat cheaper calls.** Remove sequential model calls from the critical path first.
2. **Put work in the player's reading time.** A phone player takes ten seconds or more to read a short turn. Anything
   that can run during that time (choices, bookkeeping, art, digests) is free in speed terms.
3. **Do in code what code can do.** Dice, damage, hit points, DC tables and scene bookkeeping that follow from a
   choice do not need a model.
4. **Keep the prefix stable.** Anything in front of the cache breakpoint should change rarely.
5. **Use the smallest model that holds quality, per job,** and measure quality with replays (section 8) rather than by
   feel.
6. **Cap what the player can spend,** by turns per day, typed turns, bespoke art.

## 4. The levers

Ranked by expected value for effort. Each lists the risk.

### 4.1 Narrate first, bookkeep after (the "scribe")

Today the narrator makes its world-keeping calls (`establish`, `set_scene`, `set_motive`, `update_character`,
`set_combat`) before it writes the final reply, so those calls sit in front of the first word the player sees.

Change: the narrator writes the narration and a one-line `next_beat`, nothing more except dice. After the reply is
streamed, a **scribe** call on the cheap model reads the narration, the briefing and the sheets, and makes the
bookkeeping calls (or returns one structured object that the server applies in a single step). The player is reading
while it runs.

- **Gain:** time to first text falls from a median of 3.8 s toward the model's time to first token (a guess of 1 to 2
  s on a cached prefix; measure it); one to three sequential calls leave the critical path; the narrator's tool list
  and prompt shrink (the world bookkeeping rules in the adventure prompt are a large share of it).
- **Cost:** neutral to slightly higher in tokens (a new call), lower in wait. The scribe's context is small
  (narration, briefing, sheets; about 4 to 6 k tokens), so it is cheap, but it cannot share the narrator's cached
  prefix.
- **Risks:**
  - The next turn must not start before the scribe finishes. The server serializes them; the reading time covers it,
    and a turn that arrives early waits for the scribe, not the other way round.
  - The scribe can disagree with the narration (a wound the narrator forgot to mention). Give it the narration as
    ground truth and the instruction "record what the text says, invent nothing", and keep the existing corrections
    mechanism for the cases it misses.
  - The narrator no longer sees the result of its own `recall`, so the facts it needs must be in the briefing. Today's
    "recall before inventing" rule is kept, but `recall` becomes the only world tool in the narrator's list, and the
    briefing is made to cover more.
- **Rollout:** build it behind a setting, run old and new on the same saved games (section 8), compare sheet and world
  consistency.

### 4.2 Server-rolled checks from choices

With choices ([CHOICES.md](CHOICES.md)), the common action already says which skill it uses. The server can roll it
without asking the model to request a roll.

Flow: the player taps a choice with a prebuilt `check`; the server rolls (advantage, bonuses and the roleplay quality
boon from [ROLEPLAY.md](ROLEPLAY.md) included), applies automatic consequences (hit points, conditions, resource use)
to the sheet, and sends the narrator one message: "The player did X. Result: Stealth 17 vs DC 13, success by 4.
Narrate." The narrator makes **one call** and no tool calls. Dice animation plays on the client from the `dice_roll`
event as it does now.

- **Gain:** one call instead of two or three on every checked action; deterministic rules (fewer wrong DCs and wrong
  modifiers); the model cannot "fudge" a roll.
- **Cost:** rules code per ruleset. The existing prompts let the model adjudicate all twelve rulesets in text; this
  lever needs real code for the parts it automates (check formulas, damage, conditions). Both launch rulesets
  ([LAUNCH_RULESETS.md](LAUNCH_RULESETS.md)) are code-driven; typed actions with no prebuilt check keep the
  model-adjudicated path.
- **Risks:** a typed action with no prebuilt check falls back to the old path, so the narrator keeps its roll tool;
  consistency between the two paths needs tests.

### 4.3 The choice writer in the reading window

Described in [CHOICES.md](CHOICES.md) section 6. In cost terms: one small extra call of about 4 to 6 k tokens in and
0.4 to 0.6 k out per turn, hidden in the reading time. Keep its context compact (final narration, last few turns, the
briefing, a short party card), and keep its system prompt small and stable so it can be cached across turns: that
makes its main cost the output, which is also small.

### 4.4 Caching hygiene

1. **Move the briefing out of the per-request tail.** Today the briefing is attached to the last user message and the
   history is cached up to the block before it. In a tool loop, the last message is a tool result, and the briefing
   moves to the end of it, so each request re-processes the briefing and the new messages. Options to test:
   - Attach the briefing once to the turn's player message and keep it there for the rest of the turn, so continuation
     requests read it from the cache. A world change made mid-turn (for example by `set_scene`) then shows only in the
     next turn's briefing; with the scribe (4.1), mid-turn world changes mostly disappear anyway.
   - Split the briefing into a **stable part** (location, present people, motives: changes only when the scene
     changes) placed before the breakpoint, and a **small volatile part** (time, relevant facts) after it. Expected
     gain: most of the ~4.3 k uncached per extra request. Risk: stale briefing within a turn; test with the existing
     world-tool tests.
2. **Choose the cache lifetime from real pause lengths.** The default cache lifetime is short (minutes). A phone
   player who puts the app down for ten minutes pays a full cache write on return (the whole 40 to 50 k prefix). A
   longer lifetime costs more per write and less per miss. Log the gap between turns, and choose the lifetime per tier
   from the distribution; verify current pricing and options.
3. **Keep the prefix byte-stable.** Order is tools, then system, then messages. Anything that changes the tool list
   (such as showing combat tools only in a fight) changes the very start of the prefix and discards the whole cache,
   so do it only at phase boundaries, not turn by turn. Keep the history reduction's step cuts
   ([HISTORY.md](HISTORY.md)); they already move rarely for this reason.
4. **Warm the cache** deliberately only if measurement shows cold starts are common after a long break; a warming call
   costs a write, so it rarely pays.

### 4.5 Shrink the fixed prefix

- The tool schemas are 6.9 k, almost as large as the system prompt. Many descriptions are long because the model once
  needed coaching. Trim them, move rarely needed guidance into the system text only when relevant, and merge tools
  that are always used together. After 4.1 and 4.2 the narrator needs far fewer tools (recall, a roll tool for typed
  actions, and perhaps `begin_adventure` outside the adventure).
- The system prompt is 7.3 k. The `03_roleplay.md` and world rules are verbose. After the scribe takes over
  bookkeeping, its half of the rules leaves the narrator prompt.
- Measure each reduction by replay (section 8): a smaller prompt that costs quality is not a saving.

### 4.6 Shorter turns, and when to think

- **Narration length** is the largest lever on output, and the choice flow wants 80 to 200 words anyway. Output tokens
  are billed at several times the input rate and produced slowly, so halving the length is the most visible speed gain
  per turn.
- **Thinking** adds seconds per call. Make it a policy by turn type: off for routine narration and for the scribe and
  choice writer; on (low) for social checks, puzzles and chapter turns. Thinking blocks also stay in recent history,
  so turning it off shrinks the history sent. Measure quality on replays before turning it off everywhere.

### 4.7 Model routing

| Job | Model | Why |
|---|---|---|
| Narrator, routine turns | Haiku (current) | fast and cheap; already good enough in your play |
| Narrator, key beats (chapter open/close, reveals, big social scenes) | a stronger model, selectively | quality shows most there; a few turns per hour |
| Choice writer, scribe, digests, extraction | Haiku | structured, small context |
| World expansion, story planning, next-tale | stronger model, off the critical path | rare, and quality matters |
| Image prompts | Haiku | structured transformation |

Because narrative quality is the product's differentiator ([CAMPAIGNS.md](CAMPAIGNS.md) section 2.1), spend the extra
tokens on the turns where story shows (openings, reveals, confrontations, endings, authored set pieces) and save on
the rest.

Routing is a function of the turn type the server already knows (a checked action, a social check, a chapter
boundary). Start with Haiku everywhere and add the stronger model only for named turn types, if replays show a quality
gap.

### 4.8 Batch and background work

Anything the player does not wait for can be cheaper and calmer: digests, curator passes, prefetching the next
chapter's plan, portrait-prompt writing, and bulk generation of the portrait library. Use the asynchronous batch
interface where the answer is not needed within minutes (verify current discounts). Never batch the turn path.

### 4.9 Perceived speed

- Stream narration from the first token, with a small ink-in effect.
- Play the dice animation while the narrator is already writing the consequence.
- Show choices as soon as they arrive; show the "Continue" tap when there are none.
- Make art placeholders instant; fade pictures in.
- Optimistic UI for the tap: the card highlights and the transcript shows the chosen line immediately.
- Resume after interruptions ([APP.md](APP.md) section 6) so that a lost connection costs nothing.

## 5. Considered and not recommended (yet)

- **Speculative narration for every option.** Generating each choice's outcome in advance multiplies output cost by
  the number of choices and wastes most of it. Only worth it for a single obvious next step ("Continue").
- **A single mega-call that writes narration, bookkeeping and choices together.** Cheapest in calls, but it lengthens
  the wait for the first text, ties three prompts together and makes failures hard to isolate. The three-call split
  (narrator, choice writer, scribe) is easier to tune and to test.
- **Local or cheaper open models for the narrator.** Quality and consistency risk; the current prompts rely on a
  strong instruction follower. Keep as a research track for the scribe and choice writer first.
- **Aggressive history deletion.** The digest scheme already handles it; deleting more risks continuity.

## 6. Worksheet: cost per turn and per subscriber

For each job, with the per-token prices of the model used:

> turn cost = sum over jobs of > (uncached input x P_in) + (cache reads x 0.1 x P_in) + (cache writes x 1.25 x P_in) +
(output x P_out)

Replace the ratios with the current published ones. Then:

> monthly cost per subscriber = turns per month x turn cost + images per month x image price + fixed overhead
(storage, > moderation, billing fees)

Illustrative arithmetic in base-input equivalents (to be replaced by replay measurements):

| Turn design | Calls | Roughly |
|---|---|---|
| Today, median | 2 | 19 k |
| Narrator only, one call, short narration (250 tokens), thinking off | 1 | 10 k |
| plus choice writer (compact context) | +1 | +5.5 k |
| plus scribe (compact context) | +1 | +4.5 k |
| Total of the new design | 3 | about 20 k |

The new design costs about the same per turn as today's while adding choices and bookkeeping, and the wait to the
first word drops. **Do not expect the structure alone to save money.** Savings come from shorter narration, cached
small prompts, a trimmed prefix (4.5), thinking policy (4.6) and, above all, server-rolled checks (4.2), which remove
calls rather than add them. The real figures need replays.

Budget questions the worksheet answers:

- the price per month that gives a target margin at the average player's turns;
- the free-trial length that costs an acceptable amount;
- the daily turn and typed-turn caps per tier;
- whether images or text dominate (with [ART.md](ART.md) section 9).

## 7. Metrics to add

The per-request metrics already record tokens, cache use, thinking time and latency. Add:

- a **job** label per request (`narrator`, `choices`, `scribe`, `curator`, `digest`, `art-prompt`) and a **turn type**
  (`routine`, `checked`, `social`, `typed`, `chapter`);
- an estimated **cost** per request from a price table in configuration;
- the **gap between turns** (for the cache lifetime decision);
- first-text time, choices-ready time and scribe-done time, so the reading window can be seen to cover the work;
- p50 and p95 per job and per tier, not only the mean;
- the retry and fallback counts for the choice writer (validation failures), which are both a cost and a quality
  signal;
- per-user daily totals, for caps and abuse detection.

## 8. A replay harness before changing anything

Every lever above risks quality. Build a harness first:

1. Take saved games (the `saves` folder has many) and extract a sample of real turns with their histories and states.
2. Re-run a turn under a candidate design (new prompt, smaller tools, thinking off, scribe on) with the same inputs.
3. Score: cost and time (from metrics); sheet and world consistency after the turn (the scribe versus the old tool
   calls); a rubric-graded read of the narration for continuity, voice and hint discipline (graded by a stronger
   model, spot- checked by you); whether any hidden fact leaked.
4. Report a comparison table per lever. Ship a lever only when the table says it is a win or a free win.

This is also the test bench for the choice writer ([CHOICES.md](CHOICES.md) section 10).

## 9. Suggested order

1. Metrics additions and the replay harness (section 7 and 8).
2. Caching hygiene (4.4) and thinking policy (4.6): small changes, measurable at once.
3. Resumable turns and the choice protocol with the choice writer (4.3): needed for the product anyway.
4. The scribe (4.1), then the prefix reductions it enables (4.5).
5. Server-rolled checks for 5.5e (4.2).
6. Model routing (4.7) and batch work (4.8) once the baseline is known.

## 10. Open questions

1. What is the target cost per turn, and what turn volume per subscriber does the price assume?
2. Is a stronger model for key beats a visible quality difference, or can Haiku carry the whole game?
3. Is the scribe reliable enough on sheet changes (damage, spells, items) to replace the narrator's
   `update_character`, or should the server own those numbers outright via 4.2?
4. How long is the median pause between turns on a phone, and does a longer cache lifetime pay for itself?
5. Does turning thinking off hurt the social and puzzle turns (where the hidden-motive reasoning matters)?

## 11. Pricing and metering mechanics

Amounts are decided later, from beta data. This section fixes the shape so that the server can be built to support it.

### 11.1 The model

- **Free tier**, intentionally limited: one short campaign pack (or its first chapters), a small daily turn allowance,
  a handful of typed turns, no custom games, ads or none. It uses the cheapest turn path (Haiku, short narration). Its
  job is to let someone feel the story quality, not to be a game they can finish.
- **Pay as you go**: **credit packs** bought when wanted. Credits do not expire quickly (a long expiry avoids
  regulatory and trust problems; check local rules on stored value).
- **Subscription tiers**: a monthly allotment of credits, plus features that cost little to give: the whole campaign
  library, more typed turns, custom games, cloud saves, a larger carry-over of unused credits.
- Players may mix the two: a subscription's allotment is spent first, then purchased credits.

### 11.2 The unit

Use one user-facing unit, for example **"story points"**, rather than tokens. A player should be able to predict their
spending.

- A normal turn costs 1 point. A **typed** turn costs more, because the model plans unaided; a **key story beat** (a
  stronger model, thinking on) costs more; a turn with a server-rolled check costs the same as a routine turn.
- The weights come from measured cost per turn type ([TURN_COST.md](TURN_COST.md) section 7 metrics), rounded to a few
  simple values. Re-tune them from beta data without changing the unit.
- Show the balance and the cost before a costly action. Never surprise.

### 11.3 The ledger

A server-side **ledger** is the one source of truth.

- Entries: grant (subscription renewal, purchase, promotion), spend (a turn, with its type and the actual token cost
  recorded for analysis), refund (a failed or abandoned turn), expiry.
- A turn **reserves** its price when it starts and **settles** when it ends; a turn that fails on the server's side is
  free.
- The store and web payment systems only add entries or change a tier; they never touch spends. This also keeps the
  app-store and Stripe paths consistent. A subscription-management service (such as RevenueCat) can deliver the
  purchase events.
- Never cut a scene in half: when the balance runs out, finish the current turn and show the choices as read-only
  until the player tops up or waits for the daily allowance.

### 11.4 Store rules

- Credit packs are normally **consumable in-app purchases**; subscriptions are auto-renewable. Store rules,
  commissions and the allowance for external payment links differ by country and have been changing; check the current
  rules, and decide whether the web price differs from the in-app price.
- Provide restore-purchases, clear terms, and a way to manage or cancel.

### 11.5 Abuse and limits

- Require an account (Apple, Google or email) for any play, with email verification before the free allowance, to curb
  throwaway accounts; consider device attestation if abuse appears.
- Rate limits per account and per IP for the free tier; a daily ceiling on spend per account at every tier, with a
  support path to raise it.
- Typed input is length-capped ([CHOICES.md](CHOICES.md) section 5) and moderated.
- Alert on accounts whose cost per day is far above the median, since a script is more likely than a player.

### 11.6 What it does to the design

- Cost per turn type must be known before prices are set: the metrics additions in section 7 come first.
- The free tier works only if its path is cheap: campaign packs help here, since a pack's art and structure are free
  at runtime, and a first chapter is a bounded cost.
- Campaigns can sit in the tiers or be sold as add-ons ([CAMPAIGNS.md](CAMPAIGNS.md) section 10); the ledger supports
  either.
