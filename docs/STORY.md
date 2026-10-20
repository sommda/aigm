# AIGM Narrative Structure: Design

Status: **step 1 of 8 built** (section 14); the rest is proposal. The questions that were open are settled in
section 12. This builds on
[WORLD.md](WORLD.md) (the knowledge base and the curator), [BACKEND.md](BACKEND.md) (game state, tools, prompts, saves)
and [RULESETS.md](RULESETS.md) (a Session 0 choice that is stored in the game state, which is the pattern this feature
follows).

## 1. Goal

Today a game is an *endless* sandbox: story shape only emerges from what the player does. This feature adds an
optional **structured campaign** with a clear beginning, middle and end, and more than one possible ending depending
on what the party does. It is chosen in Session 0, where the GM always asks (unless the player has already made the
choice clear). An *endless* choice leaves the game exactly as it is today.

The shape is three chapters:

| Chapter | The player's position | What the world does | What the GM does |
|---|---|---|---|
| 1. Setting the stage | Does not yet know the final goal | Wide open: new places, people, factions and quests are added as needed | Seeds hooks and rumors, introduces the world, builds the party up |
| 2. The road to the goal | Knows the goal (a final dungeon, a boss, an artifact...) | Existing places gain detail; **no major additions** | Nudges the player toward the goal; quests keep building the party |
| 3. The endgame | Approaches and tries to achieve the goal | Closed; everything needed already exists | Focuses on the approach, the climax and the resolution |

A game ends in one of several **endings** (triumph, a costly victory, failure, a surprising turn...), decided by the
player's choices and results, not drawn from a hat. After an ending the player may keep playing in the same world as
an endless game.

### Requirements taken from the request

1. Optional. Chosen in Session 0; the GM always asks. Endless play stays exactly as it is now.
2. Three chapters with the rules for the world in the table above.
3. Three lengths: **short** (a session or two; 2 or 3 major quests to advance a chapter), **long** (about ten times
   that), **medium** (between).
4. Quests are there to build up the party until it can do the goal. Except possibly in a short game, the goal must be
   set up so that the party is **too weak to achieve it at the start** of the game.
5. A long game may have a much more convoluted path to the goal, which the player must discover.
6. Multiple endings.

### Non-goals (first cut)

A player-visible quest log or map, branching *chapters* (the order of chapters is fixed), more than three chapters,
changing the length after the game has begun, and a story that rewrites itself on every player whim (the plan is
repaired when it breaks, section 8, not regenerated). Each of these has room in the design.

## 2. Principles

- **A plan the GM follows, not a script.** The server holds a structured plan: a hidden goal, a list of quests
  (called **milestones** here, to keep them apart from the world's `concept` entities), and the endings. The GM sees
  only the slice that matters now and is told to steer toward it, never to force it. A player who wanders gets
  nudged; a player who refuses a path gets another one.
- **The world stays the single source of truth.** Everything the plan names (the final place, the villain, the
  artifact, the allies) exists in the knowledge base as ordinary entities and *hidden* facts, so `recall`, the
  briefing and the independence rules work unchanged. The plan only adds structure on top: what must happen, in what
  order, and what counts as done.
- **The goal pre-exists.** The goal is not invented because the party showed up. It is a thing in the world with a
  history (a lich who has been rising for ten years, a vault that has been sealed for centuries). This also fits the
  independence rules in WORLD.md 5.4, so the world builder can write it without special cases.
- **Server rules, not model discipline, for the hard limits.** Chapter changes follow a rule the server checks.
  The "no major additions" limit of chapters 2 and 3 is enforced in the tools and in the curator, not only
  requested in a prompt (a lesson from the damage-roll rule, which a prompt alone did not hold).
- **Latency stays flat.** The GM does not get a new round-trip for story bookkeeping (see the cost of the bookkeeping
  rounds in BACKEND.md). Progress is reported on a call the GM already makes, and the heavy planning happens in the
  background curator.
- **Bounded context.** Even a long game keeps only the current chapter's active milestones in the GM's request.

## 3. The story plan

Stored in the game state as `GameState.story` (`None` for an endless game), saved with the game.

```jsonc
{
  "length": "medium",                // short | medium | long
  "chapter": 1,                      // 1, 2 or 3; 4 once an ending has been reached
  "chapter_started_turn": 1,
  "last_progress_turn": 1,           // for pacing (section 6.3)
  // titles for the status line, a purpose line for the GM, a level to aim for
  "chapters": [
    { "title": "Ashby and the vale", "purpose": "Learn the vale; build the party", "target_level": 3 }
  ],
  "goal": {
    "title": "Break the Ashen Crown",           // hidden until the end of chapter 1
    "summary": "The Ashen Crown, kept in the sunken Vault of Orrin, is binding the river spirit and flooding the vale.",
    "entities": ["e031", "e044"],               // the places, people and things it involves (ids in the world)
    "revealed": false,
    "min_strength": "Level 7 and at least one ally from the river folk"   // the 'too weak' gap, in plain words
  },
  "milestones": [
    {
      "id": "m03",
      "chapter": 1,
      "title": "Find who is poisoning Ashby's wells",
      "brief": "One or two sentences for the GM: what must happen, and the ways it can happen.",
      "gives": "the party meets the river folk; level 3; clue to the Vault",   // what it builds (section 7)
      "requires": ["m01"],           // milestones that must be done first (ids)
      "status": "active",            // pending | active | done | skipped | failed
      "scale": "small",              // small | medium | large: how much play the quest holds (section 6.1)
      "required": true,              // counts toward ending the chapter
      "entities": ["e017", "e020"],  // where and with whom it lives
      "done_turn": null,
      "outcome": null                // a short note written when it is done: what happened, what the party chose
    }
  ],
  "endings": [
    {
      "id": "end_triumph", "title": "The vale is freed",
      "when": "The party destroys the Crown and the river spirit lives."
    }
  ],
  "choices": [ { "turn": 40, "milestone": "m05", "note": "Spared the smuggler captain" } ]
}
```

- `milestones` is a flat list with `requires` links: a small dependency graph. That gives parallel quests ("do
  these two in any order") and a convoluted long-game path, without a separate graph structure.
- `endings` are described by the *situation* that produces them, in a sentence or two. The GM picks the one that
  fits at the climax (section 9); the server only checks the id and the chapter.
- `choices` is a short running log of the decisions that shape the ending. It is what lets the GM and the
  curator write an ending that reflects what the player did.
- The goal and everything in it is also recorded as entities and hidden facts (section 5), with `aspect: "plot"` where
  one fits.

### Pure logic

The state transitions (which milestones are available, when a chapter is complete, what the next chapter is) are pure
functions in `aigm/story.py`: no clock, no network. This is where most of the tests will go.

## 4. Session 0: choosing the structure

A new Session 0 tool, **`set_structure`**, mirrors `set_ruleset`: offered in `session_zero` only, callable more than
once, and the last call wins.

```jsonc
{ "mode": "endless" | "short" | "medium" | "long" }
```

- **The GM always asks before leaving Session 0**, unless the player's own words already make the choice plain ("an
  endless sandbox", "a short story-driven adventure I can finish this weekend"). The Session 0 prompt (a new
  `session_zero/01b_structure.md`) has the GM raise it once the setting is roughly agreed: a story with a beginning,
  middle and end, or an endless campaign? And if a story, how long: short (one or two sittings), medium, or long. It
  describes each in a sentence. Nothing is assumed on the player's behalf: a vague "whatever" gets a short
  recommendation and a question, not a silent default.
- If the player chose a story they may also steer it in Session 0 ("I want a lich", "something about a stolen crown").
  The GM puts that in `gm_notes`/the setting, and the plotter (section 5) uses it. The GM must not decide the whole plot
  there: the goal stays secret from the player.
- **The server enforces the question.** `begin_adventure` is refused until `set_structure` has been called in this
  Session 0 ("ask the player what kind of game they want, then record it with set_structure"). When the player's
  prompt made the choice obvious, the GM calls `set_structure` itself without asking. The existing tests and the
  scripted model that call `begin_adventure` directly are updated to choose a mode first, endless where they do not
  care. The Session 0 wrap-up prompt lists the choice among the things to confirm in its summary.
- The chosen mode is shown in the Session 0 summary the GM gives before `begin_adventure`, and it goes into the
  campaign record (`campaign.structure`) as one line, so the first adventure request knows it.
- `/new` and the client need no change for this: Session 0 is a conversation.

`GameState` gets `structure: str` (`"endless"` by default, saved; older saves are endless) next to `ruleset`, and
`begin_adventure` creates the empty `Story` when the mode is not endless. The plan itself is written by the plotter.

## 5. The plotter: writing the plan

A new curator pass, **plot**, with its own prompt (`prompts/world/plot.md`) and structured output, using the stronger
model that the expand pass uses (`AIGM_WORLD_EXPAND_MODEL`). It never blocks the player. It runs:

1. **After bootstrap**, once, for a structured game. Input: the campaign record, the private notes, the first world,
   the length. Output: the goal, the endings, the chapter 1 milestones, and a **sketch** of chapters 2 and 3
   (titles and one line each). It also records the goal and the cast around it as new entities and hidden facts through
   the usual ops, so the goal exists in the world from turn 1 and chapter 1 can foreshadow it.
2. **At each chapter change** (1 to 2, 2 to 3), to write the full milestone list of the *next* chapter against the
   world as it has grown. Planning chapter 2 after chapter 1 is played is what lets it use the places and people the
   player actually met. For a **short** game the whole plan fits in the first pass, so only step 1 runs.
3. **To repair the plan** when it breaks (section 8).

Rules the plotter is held to (checked by the server, as the curator's other output is):

- The goal and each milestone must connect to existing entities (the same "no floating entities" rule as expand).
- Milestone counts follow the length table in section 6.1; the server rejects a plan that is far outside it.
- Each milestone has a `scale` (`small`, `medium` or `large`) and its `brief` is sized to match the game's length: in a
  short game every quest is small (one or two combats or challenges, a simple site), in a long game most are large
  (an involved dungeon crawl). The server checks that the scales fit the length; the exact encounter counts are the
  plotter's judgment, guided by its prompt.
- Every `required` milestone is reachable: it has a `requires` path from a milestone that is available at the start of
  the chapter. No dead ends, no cycles.
- The goal's `min_strength` is above the party's starting strength (except for a short game, which may be set to
  "ready by the end of chapter 2"). The server cannot measure strength, so the check is on the plan: the final
  milestone must `require` at least one milestone whose `gives` raises the party (level, ally, item or knowledge).
- At least two endings, at most four, each different in kind (not only "win" and "lose").
- Secrets stay secrets: the plan is `hidden` in the world and the player never receives it (section 10).

A plot pass costs about one expand call. The hidden facts it adds go through the existing independence check.

## 6. Chapters

### 6.1 Length

| | Short | Medium | Long |
|---|---|---|---|
| Target play | one or two sittings | a handful of sittings | a long campaign |
| Major quests to finish a chapter | 2 to 3 | 5 to 6 | 10 to 12 |
| Required milestones, whole game | about 7 to 9 | about 16 to 18 | about 30 to 36 |
| Path to the goal | direct: the goal is known early and few steps away | a few branches; one revelation | convoluted: clues point to clues, false leads, a goal that has to be uncovered in pieces |
| Size of a quest | small: one or two combats or challenges, a simple site (one main room with a band of monsters) | a few encounters; a modest dungeon, a short journey with a complication | an involved crawl: a multi-room dungeon or a long journey with several encounters, choices and a boss |
| Party strength gap at the start | may be small or none | clear | large |

Long is about four times short in quests, and each long quest is itself bigger (the "Size of a quest" row), so a long
game is far more than four times as long in play; medium sits between them. The numbers are the plotter's targets;
`aigm/story.py` holds them as data (`LENGTHS`) so they are tuned in one place after a play test. Optional milestones
(side quests, `required: false`) are in addition to these.

### 6.2 What each chapter changes

**Chapter 1 — setting the stage.**
- The world expands as it does now. The curator's expand pass is also told which milestones are active so that places
  and people they need get generated ahead of the party.
- Foreshadowing: clue facts about the goal are `hinted`/`known` in rumors, in the first quest's findings, in an NPC's
  fear. The goal is not handed over, but an astute player who follows the clues and asks the right people can work it
  out, or be told, before the chapter ends. The GM never lies about it and never blocks a good question.
- **Ends** when the chapter's required milestones are done *and the goal is known to the player.* The last required
  milestone of chapter 1 is a **revelation** by design: the party learns what the goal is, why it matters and roughly
  where it lies. The chapter cannot end without it. The goal's `revealed` flag is set when it is learned (by that
  milestone or earlier, through play), and its hidden facts become `known` as the GM narrates them.
- **The nudge for knowledge.** The pace note (6.3) also covers the goal: while the goal is unrevealed, the briefing
  tells the GM how many of chapter 1's required milestones are done, and as the chapter nears its end the instruction
  to let the goal come out gets stronger: clues become plainer, an NPC who knows speaks up, the next quest's
  findings name it. Once the other milestones are done and the goal is still unknown, the revelation is the only thing
  left and the GM is told to deliver it in the next scenes.

**Chapter 2 — the road to the goal.**
- The GM nudges: every scene may carry a hook toward the active milestone (section 6.3). New *details* are welcome:
  a room, a shop, a rumor, a minor NPC, a hazard on the road. New *major* things are not (section 6.4).
- Quests in this chapter build the party: allies, items, levels, knowledge (section 7).
- **Ends** when its required milestones are done; the last one opens the way to the goal ("the way into the Vault is
  now known and open").

**Chapter 3 — the endgame.**
- The approach, the obstacles guarding the goal, the climax, the resolution.
- The GM gets the endings (section 9) and is told to run toward the best-fitting one, without announcing it.
- **Ends** with an ending, not with a milestone count.

### 6.3 Nudging

The plan is a destination, not a rail. The briefing (section 10) tells the GM, each turn:

- the chapter and its one-line purpose,
- the active milestones (title, brief, scale, where, who), at most three, so the GM sizes each quest to match, and in
  chapter 1 whether the goal is known yet,
- a **pace note** that escalates: nothing while the party is making progress; a gentle "offer the next hook in this
  scene" after the party has gone `AIGM_STORY_NUDGE_TURNS` player turns without progress (default 12); a firm "bring a
  concrete consequence or opportunity to the player now" after twice that. Progress means a milestone changing state;
  turns are counted from `last_progress_turn`.

How to nudge is in the prompt (`system/adventure/05_story.md`): through the world, never by refusing the player.
NPCs ask, rumors circulate, a deadline-free consequence arrives (a messenger, an attack, a clue found in loot), a door
that was closed opens. Never "you cannot go there". A player who does not want a milestone may find another way to
complete it, or the plotter swaps in another (section 8). A player who wants to ignore the whole thing is allowed to:
the pace note is advice, and the game simply stays in its chapter.

### 6.4 "No major additions" in chapters 2 and 3

Enforced where things are created, so it holds whatever the model writes:

- **`establish` (the GM's tool).** In chapter 2 or 3 it refuses a new `faction`, a new `location` that is a region or
  a settlement (a location whose parent is not itself inside a settlement or site, or that has no parent), and a new
  `concept`. It accepts a new location *inside* an existing one (a room, a cellar, a stall, a cave mouth) and any `npc`
  (people are details). The refusal says what to do instead: attach the detail to an existing place or person.
- **The expand pass.** In chapters 2 and 3 `max_new_entities` per pass is reduced (default 3) and new entities must
  be NPCs or locations inside existing sites, by the same rule. It still adds facts to existing entities, which is the
  "add details to existing locations" the request asks for.
- **The plotter's own world additions** at the chapter change are exempt (it is the one place the plan may add what
  the next chapter needs), but it is asked to prefer existing things.
- The check lives in one function, `story.addition_allowed(world, chapter, kind, parent)`, used by both.

Chapter 1 has no such limit.

## 7. Building up the party

The goal's gap is closed by the milestones. Each milestone says what it `gives` the party, in plain words: a level, an
ally, an item, a piece of knowledge or access, a boon from a faction. The plotter is required to distribute these so
that the sum is enough for the goal's `min_strength`.

- **Levels.** The server does not run a ruleset-specific level system. The plan gives each chapter a **target party
  level** (`chapter_levels`, e.g. 1→3, 4→6, 7→9) and a milestone may say "level up". The briefing tells the GM the
  target and which milestone just completed; the GM awards the level using the ruleset's own advancement rules. This
  keeps the server out of edition-specific rules.
- **Items and allies** are recorded as ordinary entities and facts when they are earned (the GM's `establish`).
- **The gap in play.** If the party reaches the goal underprepared, the story does not end. The guardians are strong
  enough that a direct assault fails in an interesting way: retreat, capture, a bargain, a warning from an NPC. The
  GM is told to make the gap *felt* in chapters 1 and 2 (an early glimpse of the goal's power that the party cannot
  match). The briefing in chapter 3 states `min_strength` so the GM scales the climax fairly.
- A short game's gap may be small, since 7 to 9 milestones do not build much. The plotter decides.

## 8. Progress, and when the plan breaks

### 8.1 Reporting progress (no extra round)

`set_scene` already runs whenever the scene or time changes. It gets one optional field:

```jsonc
"story": [
  { "milestone": "m03", "status": "done", "outcome": "The party exposed the miller; the captain was spared." }
]
```

- `status` is `done` or `skipped` (the party bypassed it) or `failed` (it can no longer be done; section 8.2).
- `outcome` is required (one or two sentences) and is stored. If the player made a choice that matters for the ending,
  the GM adds it to `outcome`; the server copies a short line into `choices`.
- The server checks that the milestone exists and is active, applies it, activates the milestones that `requires` had
  been waiting for, and tells the GM in the result what is now active.
- **Chapter completion** is then pure logic: if every `required` milestone of the chapter is `done` or `skipped`, the
  chapter advances. The result tells the GM, and the next briefing gives the new chapter's instructions. If the next
  chapter's milestones are not planned yet, the server requests a plot pass (chapters 2 and 3 for medium and long)
  and the GM is told the chapter begins with a transition scene while the plan catches up.
- **The curator is the backstop.** The extract step is given the active milestones and returns any it sees completed in
  the narration. If the GM forgot, the curator reports it, subject to the same checks, a pass later. The GM tool is
  primary because it is immediate and costs no round.

### 8.2 When the plan breaks

The player will kill the important NPC, burn the bridge, or simply do something else. The GM reports the milestone
`failed` or `skipped` as above. Then:

1. If the chapter can still be completed by the remaining `required` milestones, nothing else happens.
2. If not, the server asks the plotter for a **repair** pass: given the world, the current plan and what happened, it
   replaces or adds milestones to restore a path, keeping the goal and the endings where it can (it may add an ending
   that records the failure). Repair is the only place a chapter's required milestones change after they are written.
3. A failed required milestone with no repair (curator off, pass failed) is marked `skipped` after a timeout of
   `AIGM_STORY_STALL_TURNS` player turns (default 40), so a game can never stick forever.

## 9. Endings

- The plan lists 2 to 4 endings. In chapter 3 the briefing lists them with their `when` lines, and the `choices` log.
- At the climax the GM calls **`end_story`**, a new adventure-phase tool:

  ```jsonc
  {
    "ending": "end_triumph",
    "epilogue": "A paragraph or two: what becomes of the vale, the party and the people they met."
  }
  ```

  The server accepts it only in chapter 3 and when the goal milestone is `done` or `failed`. It sets `chapter` to 4
  (concluded), stores the ending id and epilogue, and the GM writes the final scene. A total party defeat may use an
  ending as well (any chapter, with an ending of the failure kind), so the game is not left hanging.
- If no listed ending fits, the GM may name `end_custom` with a title; the server stores it as is. Plans are advice, and
  the player's actions are the truth.
- **After the ending** the game continues as an endless game in the same world, if the player wants: the story record
  stays (so the ending can be shown) but no more chapters are tracked, the story section leaves the briefing and the
  expansion limits lift. The GM is told to offer, once, to continue.

## 10. What the GM sees

Everything the GM is shown about the story is **private**. The player never sees the plan, unless the GM narrates it.

- **System prompt** (stable, cacheable): `system/adventure/05_story.md`, included only for structured games. It
  describes the three chapters, how to nudge, how to report progress, and the ending protocol. The game's prompt
  selection grows a `structure` key (`Game._system` is keyed by phase and ruleset; it gains the flag), so endless games
  send exactly what they send today.
- **Briefing** (per request, not cached): a new block *above* the world notes, built from the plan by
  `story.briefing_block(story, turn)`:

  ```
  ## Story (private)
  Chapter 2 of 3, "The road to the Vault": the goal is known; steer toward it. No new regions, settlements or factions.
  Active: [m07] Win the river folk's trust (at Lowmeet, with Silt; medium).
          [m08] Find the key to the sluice gate (small).
  Pace: 14 turns without progress. Offer a concrete hook toward an active quest in this scene.
  Party should be about level 6 by the end of this chapter.
  ```

  In chapter 3 it also carries the endings and the choices log. The block respects the briefing's token budget
  (`AIGM_WORLD_BRIEFING_TOKENS`) by being small: at most three milestones and a few lines.
- **Tools:** `set_scene` gains the optional `story` field; `end_story` is added; `establish` gains the chapter rule.
  Endless games see neither new tool nor field (the tool list is already built per phase; it gains the structure).

## 11. Surfaces

- **Save format.** `GameState.to_dict` gains `structure` and `story`. Saves without them load as endless. The save
  `version` is bumped and the old version stays readable, as for every earlier addition. A story record must be valid
  or the save is a `CorruptSave` (known chapter, milestone ids unique, `requires` pointing at existing ids).
- **API.** `GET /chat/history` and the `message_end` of a turn gain a public summary:
  `"story": { "length": "medium", "chapter": 2, "chapter_title": "The road to the Vault", "ended": false }`
  (`null` for endless). No goal, no milestones, no endings: those are spoilers. A new SSE event `chapter`
  (`{ "chapter": 2, "title": "..." }`) is sent when a chapter changes so the client can mark it. See API.md.
- **Client.** The status line shows `Ch 2: The road to the Vault` for a structured game, and a chapter change prints a
  one-line banner in the transcript. `/info NAME` for a saved game shows the length and chapter. A saved game's list
  entry gets the same. Servers that do not send `story` (older ones) change nothing.
- **Debug.** The context viewer gets a "Story plan" section (the whole plan, shown because debug mode already shows
  spoilers), and `GET /debug/story` returns the plan. The thinking switch lets the plotter's effect be compared.
- **Metrics.** The turn's metrics line gains `chapter`; plot passes are logged like other curator passes.
- **Configuration** (all optional): `AIGM_STORY_NUDGE_TURNS` (12), `AIGM_STORY_STALL_TURNS` (40),
  `AIGM_STORY_EXPAND_ENTITIES` (3, chapter 2 and 3 cap). Structured games need the curator; with
`AIGM_WORLD_CURATOR=false`, `set_structure` answers that only endless is available, which also satisfies the
  `begin_adventure` check.

## 12. Decisions

Settled in review:

1. **No default mode.** The GM always asks what sort of game the player wants before leaving Session 0, unless the
   player's prompt already makes it obvious. The server enforces it (section 4).
2. **Long means 10 to 12 quests per chapter** (short 2 to 3, medium 5 to 6; section 6.1).
3. **Levels** stay with the GM and the ruleset, with a target level per chapter and no server tracking (section 7).
4. **The goal** may be learned and hinted at during chapter 1 by an astute player, but it **must be known to leave
   chapter 1**, and the GM's nudges make learning it increasingly likely as the chapter goes on (section 6.2).

Taken as recommended, still open to change in review:

5. **Who ends a chapter.** The GM reports milestones on `set_scene`; the curator is the backstop (section 8.1).
6. **Chapter 2 and 3 additions.** New regions, settlements, factions and concepts are refused; rooms, caves and people
   are allowed (section 6.4). Tune in play.
7. **After the ending** the GM offers to continue as an endless game (section 9).
8. **The curator is required.** Structured games need it; with `AIGM_WORLD_CURATOR=false` the choice is unavailable and
   the game is endless (section 11).

## 13. Testing

- **Pure logic** (`tests/test_story.py`): chapter completion, availability through `requires`, validation of a plan
  (cycles, dead ends, unknown ids, counts per length), the pace note thresholds, `addition_allowed`, `LENGTHS`.
- **Tools:** `set_structure` (session zero only, last wins, rejects bad modes); `begin_adventure` refused until it has
  been called; `set_scene` story field (unknown or
  inactive milestone, chapter advance, outcome required); `end_story` (wrong chapter, unknown ending, success);
  `establish` refusals in chapters 2 and 3.
- **State:** save round trip, old saves load as endless, corrupt story records rejected.
- **Prompts:** endless games' system prompt and tool list are byte-identical to today's (a regression test); structured
  games add exactly the story section.
- **Curator:** scripted plotter in `world/scripted.py`; plan validation rejects a plan with a dead end; a chapter
  change requests the next plot pass; a repair pass restores a broken chapter; expand limits in chapters 2 and 3.
- **Whole game:** a scripted run through all three chapters of a short game to an ending, through the HTTP API, with the
  public summary and the `chapter` events checked and no plan text anywhere in a public response.
- **Client:** status line, chapter banner, servers without `story`.
- **Live play (not automated):** one real short game to look at pacing, whether nudges feel like nudges, and whether the
  plotter's plans are interesting. This is the real test and decides the tuning in 6.1 and 6.3.

## 14. Build order

1. **State and pure logic.** *Built.* `GameState.structure` and `story`, `aigm/story.py` (plan validation, chapters,
   pace, addition rule, `LENGTHS`), save and load (format version 4; older saves are endless). No behavior change.
2. **Session 0.** `set_structure`, the prompt, the campaign record line, the summary. Structured games begin with an
   empty plan; a stub plan for tests.
3. **The plotter.** Prompt, structured output, validation, scripted version; first pass after bootstrap, goal and cast
   in the world.
4. **The GM side.** Story system prompt, briefing block, `set_scene` field, `end_story`, the pace note.
5. **Chapter rules.** Chapter transition (including the plot pass for the next chapter), `establish` and expand
   limits, curator backstop in extract.
6. **Surfaces.** API summary and `chapter` event, client status line and banner, debug plan view, metrics.
7. **Repair.** The repair pass and the stall timeout.
8. **Live play and tuning.**

Steps 1 to 4 give a playable first cut for a short game; 5 to 7 complete it for longer games.
