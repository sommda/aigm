# AIGM Persistent World: Design

Status: **implemented** (all seven build steps, section 11). Decisions taken after review are collected in section 10
(all open questions are settled). This builds on [BACKEND.md](BACKEND.md) (turn loop, game state, prompts, saves) and
[API.md](API.md).

## 1. Goal

Give each game a persistent, ever-growing **world knowledge base** (KB) so that the world feels like a pre-existing
place the player discovers, not something improvised around their actions. Concretely:

1. **Consistency.** What the GM said about the ruins in turn 12 is still true in turn 112, and the GM cannot contradict
   it by accident.
2. **Pre-existence.** When the player reaches something, it is already there, with history, neighbors and a reason to
   exist that has nothing to do with the party. The GM does not invent a thing at the moment the player needs it; it
   reveals one that was generated earlier.
3. **Depth ahead of the player.** The world is generated a bit *ahead* of the party (the approach to a mine, how it is
   entered, its first rooms), so the next scene is always already backed by facts.
4. **Bounded cost.** The world is never modeled up front, and only a small, relevant slice of it is in any one request.

The KB is also the natural long-term memory. Once it exists, old chat history can be compacted or dropped without losing
the world (the "memory management comes later" item).

### Non-goals (v1)

Anything that *acts on* world time (places and factions changing while the party is away; the clock itself is in v1, see
2.4), a player-visible journal or any client UI for the world, a map renderer, embeddings/vector search, editing the
world by hand, shared worlds across games. Each is noted below where the design leaves room for it.

## 2. The knowledge base

### 2.1 Facts

A **fact** is one declarative sentence about the world, true in the fiction.

```jsonc
{
  "id": "f0042",
  "text": "The Harrow Mine lies deep in the Thornwood, 3 miles east and 2 miles north of Ashby.",
  "about": ["e007", "e003", "e001"],     // entities it concerns (at least one); the first is the subject
  "aspect": "approach",                  // optional checklist slot this fact fills (section 5.3)
  "disclosure": "hidden",                // hidden | hinted | known  (section 2.3)
  "source": "generated",                 // seed | play | generated | improvised
  "turn": 31,                            // game turn that created it
  "created_at": { "day": 3, "hour": 14 },// world time when recorded (2.4); past history is told in the text
  "revealed_turn": null,                 // turn the player learned it (when known)
  "from_time": null, "until_time": null, // reserved: window of world time when it holds (null = always); unused
  "status": "active",                    // active | superseded
  "superseded_by": null
}
```

Rules for fact text (enforced in the extraction/generation prompts and validated by the server):

- **One claim per sentence**, atomic enough that it can be true or false on its own.
- **Self-contained.** Names, not pronouns; no "the party", "you", "earlier". A fact must make sense with no context.
- **In-world and timeless-ish.** Written as the world's truth, not as a story beat ("The mine was abandoned forty years
  ago after a collapse", not "You discover the mine is abandoned").
- **No player-centric causation.** A fact never exists *because of* the party. (See 5.4.)
- Length: the prompts ask for about 40 words and anything over 60 is refused (a small overrun is kept, because a
  refusal costs the GM a round), plus a per-entity cap, so facts stay cheap to retrieve and cannot hide a paragraph
  of prose.

The two reserved time fields are what later lets a place change on its own ("from day 10 the lower gallery is flooded")
without touching the schema; v1 stores them but nothing reads them. Facts are never edited or deleted, only
**superseded** (a new fact points back at the one it replaces). That keeps a trail for debugging and makes retcons
explicit.

### 2.2 Entities

Facts hang off entities so that retrieval and reconciliation have something to key on.

```jsonc
{
  "id": "e007",
  "name": "Harrow Mine",
  "kind": "location",          // location | npc | faction | concept
  "aliases": ["the old mine", "Harrow"],
  "parent": "e003",            // containment, for locations (region > settlement/site > building > room)
  "discovered": false          // has the player heard of it at all (derived from its facts, cached)
}
```

- The four kinds are the ones asked for: **locations, NPCs, groups (factions), concepts** (a religion, a law, a curse, a
  trade good, a legend). Other kinds (items, creatures) can be added later without a schema change, since `kind` is just
  a tag.
- `parent` gives locations a containment tree, which is what lets the world be navigated and expanded outward (region,
  site, rooms).
- Other relationships are **facts that mention two entities** ("The Thorn Guild controls the toll road between Ashby and
  the Thornwood"), not a separate edge type. The set of entities that share a fact is the adjacency graph used to find
  what is "near" the party (5.2).
- Entities are cheap stubs: a name and kind are enough to exist. Their substance is their facts.

### 2.3 Disclosure: what the player knows

Every fact is one of:

| `disclosure` | Meaning | Example |
|---|---|---|
| `hidden` | True, but the player has not been told | "The mine's lower gallery connects to the smugglers' cellar under Ashby." |
| `hinted` | The player has heard a rumor, a clue or a partial truth | (the fact is the truth; the hint is recorded as a separate `known` fact: "Ashby folk say lights are seen in the Thornwood at night.") |
| `known` | Narrated to the player (or learned by their characters) | "The Harrow Mine was abandoned forty years ago." |

This split is what allows the "pre-existing world" illusion without spoilers: the GM sees hidden facts and plays
consistently with them, but is told never to reveal them except through play. A fact moves `hidden -> known` when the
curator sees it narrated (section 4.3), and `known` facts are immutable canon. Rumors are modeled as `known` facts about
*what people say*, plus the hidden truth, so a rumor can be false without the KB lying.

The `known` subset would make a natural player journal, but there is deliberately no client-visible world in v1 (section
10).

### 2.4 World state

Besides facts, the world carries a little mutable state, all in the staged game state so it rolls back with failed
turns:

```jsonc
{
  "time": { "day": 1, "hour": 8 },                              // the in-world clock (see below)
  "scene": { "location": "e012", "present": ["e020", "e021"] },   // where the party is, who is with them
  "processed_through": 37,        // number of history messages the curator has digested
  "reported_hours": 0,            // hours the GM moved the clock itself since the last pass (see 4.5)
  "corrections": [],              // notes for the next briefing: {"text", "turn"} (see 6.4)
  "next_id": { "f": 43, "e": 22 },
  "facts": [ ... ], "entities": [ ... ]
}
```

`scene` drives retrieval (section 6).

**World time (in v1, but inert).** The world has a clock, `day` (starting at 1, the first day of the adventure) and
`hour` (0-23), initialized at bootstrap from the opening situation ("dusk" becomes 18). The curator advances it: the
extract step reports how much in-world time the narration covered (a rest, a journey, a night) and the server adds it;
the GM can also report it through `set_scene` (6.3). Every fact is stamped with the time it was recorded. Time is shown
to the GM as one line of the briefing so narration (light, weather, shops open) agrees with it, and that is *all* v1
does with it. The clock, the stamps and the reserved `from_time`/`until_time` fields exist so that later work (places
that change, factions that move, timed events) needs no migration. The clock never goes backward and only moves forward
by whole hours or more, to keep it from drifting on small remarks.

### 2.5 Storage

The KB lives in `GameState.world`, next to `phase` and `campaign`. Consequences, all wanted:

- It is **per game session** and **saved and restored with the game** (save format version 3: `world` alongside
  `messages`; older saves load with an empty world, which the curator then rebuilds from history).
- Staged-turn semantics come for free: a tool that records a fact mid-turn affects only the working copy, committed only
  if the turn succeeds.
- `/chat/new` resets it. Restoring a Session 0 save gives an empty world.
- **Turn digests** (`world.digests`, 4.7) are saved with the world, next to the untouched messages they condense; a
  save without them loads with none, and later curator passes write them.
- Save files are written **pretty-printed** (`indent=2`, UTF-8, readable diffs), never a single line. See 2.6 for the
  debug view of the world.
- It is plain JSON in memory with in-process indexes (entity id, normalized name/alias, token inverted index) rebuilt on
  load. A game that has run for hundreds of turns is on the order of a few thousand facts: a few hundred KB, fine. If
  saves ever get large, the world can move to a sidecar file or SQLite behind the same interface; nothing above the
  repository layer would change.

### 2.6 Inspecting the world (debugging)

There is no client or API view of the world. Instead the server keeps a human-readable **world dump**, a JSON file per
session at `{AIGM_SAVE_DIR}/worlds/{session_id}.world.json` (setting `AIGM_WORLD_DUMP`, on by default), rewritten
atomically whenever the world has changed since it was last written: it is checked after every turn (which covers
bootstrap, the GM's own `establish`/`set_scene` calls and any curator pass that has landed) and after a restore. An
empty world (Session 0) has no file, and `/chat/new` deletes it. Writing is best effort: a failure is logged and never
affects the game. It is also written in `--test` mode. It is formatted for reading, not for round-tripping, and is never
loaded by the server:

- indented (`indent=2`), with a stable key order, so it diffs well between passes;
- **grouped by entity**: each entity lists its kind, parent chain and aliases, then its facts, **one fact per line**
  under a `facts` array of short strings like `"[hidden|approach|f0042 d3h14] The Harrow Mine lies ..."` so an entity
  reads like a page of notes;
- a header with the clock, scene, `processed_through`, counts, and any open correction notes;
- superseded facts in a separate `superseded` list per entity.

The saved game itself contains the same world in canonical form (pretty-printed), so a save file can also be opened
directly. A small helper, `uv run python -m aigm.world.dump SAVE_NAME [--known-only] [--save-dir DIR]` (a save name or a
path), prints the same view from a save file, handy after a game has ended; `--known-only` shows just what the player
has been told, hiding hidden facts and superseded history.

## 3. Where the world enters the system

```
              (player turn)                              (background)
 POST /chat --> run_turn --> LLM --+--> recall / establish tools      Curator
                 ^                 |         |                          |
                 |   world briefing|         v                          v
                 +--- (per request)+--> GameState.world <---- extract -> reconcile -> expand
```

Three cooperating mechanisms:

1. **Briefing** (push): the server assembles a compact world context for every turn from the KB. Reliable, does not
   depend on the model remembering to look things up.
2. **Tools** (pull): `recall` and `establish` for detail beyond the briefing and for on-the-fly improvisation.
3. **Curator** (write-behind): a separate background process that reads recent history, records facts, reconciles them
   and generates the world ahead.

## 4. Populating the KB: the curator

The curator is the "periodically look through the chat, extract, reconcile, expand" loop. It is a **server-side pipeline
of focused LLM calls**, not part of the player-facing conversation, so it can use a cheaper model, different prompts and
structured output without disturbing the GM's context.

#

- **Bootstrap**, once, when `begin_adventure` succeeds: it turns the campaign record (setting, party, opening, and the
  private `gm_notes`) into the first entities and facts, and generates detail around the opening location. See 4.6.
- **Periodically**, after a turn commits, once enough narration has accumulated since the last pass: at least
  `AIGM_WORLD_EVERY_PAGES` (default **3**) pages. Pacing by narration rather than by turns means the curator runs only
  when enough meaningful play has happened; a string of short exchanges ("I open the door." / "It's locked.") costs
  nothing.
  - **What a page is.** Clients differ in size, so the server defines it: `AIGM_WORLD_PAGE_CHARS` (default **1,800**
    characters, roughly 300 words, one printed page). Only the GM's narration counts: the text blocks of assistant
    messages after `processed_through`. Thinking, tool calls and results, the player's own messages and the
    `[System: ...]` notes do not. A typical reply of one to three short paragraphs is a third to two thirds of a page,
    so the default pass comes every five to eight turns.
  - **The check** is a pure function of the history and `processed_through` (sum the narration characters, divide by the
    page size), so it needs no extra saved state and is trivially correct after a restore.
  - There is deliberately no extra trigger for a scene change or a new name. The two exceptions are bootstrap and the
    on-demand case below.
- **On demand**, if a tool signals a gap (for example `recall` finds nothing for a place the party is heading to).
  Because periodic passes are now further apart, this is also the safety net for a party that moves faster than the
  world was generated ahead; it runs regardless of the page count.

It never blocks the player: a pass starts after `message_end` and runs in the background (4.5). A pass digests the
history from `processed_through` to the end.

### 4.2 Pass 1: extract

Input: the unprocessed messages (text only; tool traffic summarized), plus the current scene and a short list of
existing entity names (so it uses canonical names). Output is constrained to a JSON schema (structured outputs,
`output_config.format`, rather than a forced tool call, which the newest models reject):

```jsonc
{
  "entities": [{ "name", "kind", "aliases", "parent_name" }],
  "facts":    [{ "text", "about": ["name", ...], "aspect", "disclosure", "evidence": "short quote" }],
  "reveals":  ["fact id", ...],        // hidden facts the narration just made known
  "scene":    { "location": "name", "present": ["name", ...] }
}
```

Everything the GM narrated that states something about the world becomes a candidate fact, `known` if the player was
told, `hidden` if it was only implied by the GM's own reasoning or notes. `evidence` is kept for debugging and dropped
before storage.

### 4.3 Pass 2: reconcile

The server, not the model, first finds **candidate neighbors** for each proposed fact: existing facts about the same
entities (by id or normalized name/alias) plus a keyword match on the text. It then makes one LLM call with proposals
and neighbors, which labels each proposal:

| Label | Action |
|---|---|
| `duplicate` | Drop. |
| `refines` | Keep as a new fact; the old one stays (both true). |
| `contradicts` | Resolve by the precedence rules below. |
| `new` | Add. |

It also resolves entity identity (is "the old mine" the existing "Harrow Mine"?) and records new aliases.

**Precedence rules** (deterministic, applied by the server after the model labels the conflict):

1. A `known` fact beats everything: the player already heard it. A proposal contradicting a known fact is rejected, and
   the conflict is logged as a *GM error*. Nothing is rewritten, but the next briefing carries a "correct yourself" note
   (6.4).
2. A proposal from play that contradicts a `hidden` fact **supersedes** it: the narration already happened, so the
   story's version is now the truth. Dependent hidden facts about the same entity are flagged for re-review in the
   expand step.
3. Two proposals that conflict with each other in the same pass: the later one wins.

The pass also applies `reveals`, setting `disclosure = known` and `revealed_turn`.

### 4.4 Pass 3: expand (generate ahead)

This is the step that builds the "pre-existing world". It is separate from extraction so it can use a stronger model and
a different mindset (a world-builder, not a note-taker).

**Choosing what to expand (the frontier), done by the server, not the model:**

1. Build the entity graph (parent links plus shared facts).
2. Compute graph distance from `scene.location` (and from entities with an active player interest, such as a quest
   target the player has heard of).
3. Every entity has a **checklist of aspects** by kind (5.3). An entity's *coverage* is the set of aspects its active
   facts fill.
4. The frontier is the entities with missing aspects, ranked by closeness to the scene and by whether the player already
   knows of them. Target depth by distance:

| Distance from the party | Target coverage |
|---|---|
| The scene and its immediate children (rooms here) | Full checklist |
| One hop away, or `known`/`hinted` to the player | Full checklist except deep interior |
| Two hops away | Approach, entry, and one or two features (a sketch) |
| Farther | Nothing yet; just the entity stub |

If the party hears of the Harrow Mine, it enters the frontier immediately, and the next pass writes how to reach it, how
it is found, how it is entered, and its first room or two.

**The expand call** gets: the entity to flesh out, its existing facts, its parent chain, the immediate neighbors' facts,
the missing aspects, the setting from the campaign record, and tone/difficulty. It returns new entities and facts
through the same schema as extraction. Server-side limits: a cap on new facts per pass, a cap on new entities, and a
rule that **every new entity must be connected to at least one existing entity** by a fact or `parent`, so nothing
floats free.

### 4.5 Concurrency and failure

- **Snapshot and ops.** A pass copies the world and the history, runs extract, reconcile and expand against the copy,
  and returns a list of **ops** (`world/ops.py`: add entity or alias, add fact, supersede, reveal, set scene, settle
  time, correct, mark processed). Ops refer to entities by name, and applying an op that no longer makes sense (a
  duplicate, an unknown entity) skips it instead of failing. The ops are then applied to the *live* world, which may
  have moved on meanwhile because the GM called `establish`; a fact both recorded is kept once (near-duplicate check),
  and everything else merges. Nothing is "re-reconciled": the ops are replayed, and the model is not called again.
- **When results land.** A turn works on a copy of the session state and replaces it at commit, so applying ops mid-turn
  would be overwritten. Finished passes are therefore queued on the session and applied only when no turn is running, or
  at the very start of the next turn, before that turn takes its copy. A player's turn is never blocked.
- **Where it runs.** After the response has been sent (a Starlette background task, after the session is released), so
  the player is never kept waiting. At most one pass runs per session.
- **Replaced games.** `/chat/new` and a restore bump the session's `generation`; a pass that finishes for an older
  generation is discarded.
- A pass that fails or returns invalid output changes nothing and leaves `processed_through` alone, so the next
  opportunity retries the same messages. Repeated failure only costs freshness, never the correctness of existing canon.
- **Save** snapshots the committed world and `processed_through`, so a game saved mid-pass restores cleanly and catches
  up after the next turn.
- **Clock accounting.** `set_scene` hours advance the clock at once and are tallied in `reported_hours`. When a pass
  reads the narration it reports how many hours it covered; the clock moves only by the part the GM has not already
  reported, and the tally resets, so time is never counted twice.
- **Corrections** (6.4) are stored in the world and shown in exactly one briefing: the turn that displays them clears
  them when it commits, so a failed turn does not lose them.
- **Rules enforced by the server whatever the curator is** (`world/passes.py`): a clash with a `known` fact is rejected
  and queues a correction; a clash with a hidden fact supersedes it; of two clashing proposals in one pass the later
  wins; a known proposal that repeats a hidden fact reveals it; generated facts are always hidden with
  `source: generated`; new entities must connect to the existing world (via `parent` or a fact) or are dropped with
  their facts; per-pass caps on expanded entities (3), new entities (8) and generated facts (30); the frontier (which
  entities to expand, how deep) comes from graph distance, never from the model.
- **Test mode** uses a `ScriptedCurator` driven by directives in the GM text, such as
  `echo [[fact: Wren:npc | Wren tends the bar.]] [[at: Rusty Flagon]] [[elapsed: 2]]` (see `world/scripted.py`), so the
  whole pipeline can be tried by hand and tested with no network.
- **Model-backed curator** (`world/anthropic_curator.py`, step 5): four structured-output calls, each with its prompt in
  `prompts/world/` (`extract.md`, `reconcile.md`, `expand.md`, `independence.md`, and `aspects/<kind>.md` with one
  `- aspect: meaning` line per checklist slot, which `expand` shows for the missing aspects only). Extraction,
  reconciliation and the independence check use `AIGM_WORLD_MODEL` (Haiku 5.5, effort `AIGM_WORLD_EFFORT`, default low);
  expansion uses `AIGM_WORLD_EXPAND_MODEL` (Sonnet 5.5, effort `AIGM_WORLD_EXPAND_EFFORT`, default medium).
  `AIGM_WORLD_CURATOR=false` turns the whole curator off. The extractor is shown the GM-only facts near the scene (with
  ids) so it can name the ones the narration revealed, and the world-builder is shown every existing entity name so new
  ones are fresh. A refusal, truncation or non-JSON answer raises `CuratorError`, which fails the pass harmlessly
  (retried later).
- **Independence checks on generated facts** (5.4, `world/independence.py`): regexes reject text that addresses the
  player ("you"), mentions "the party"/"the adventurers"/player characters, names a party member, or places its cause
  "recently"/"just now". A batch with any violation is regenerated **once**, with the reasons given back to the model;
  facts still failing are dropped. Afterwards a cheap model call (`judge_independence`) flags subtler dependence on the
  party; its failure is logged and ignored. Extracted facts get the lighter self-containment check (no "you", no "the
  party"); party names are fine there, since facts about play may involve them.
- **Judging quality:** `uv run python -m aigm.world.sample [--passes N]` seeds a small world, grows it with the real
  models and prints every entity with its facts. `tests/test_live.py` has an opt-in live test with checks on the result.

### 4.6 Bootstrap

At `begin_adventure` the world is empty but the campaign record is rich. **The player waits for the world to be seeded
before the first scene.** Inside the same turn, after the tool succeeds and the history is replaced, the loop runs
bootstrap (`run_bootstrap` in `world/passes.py`, via `CuratorService.seed`) and only then asks the GM for the opening:

1. **`status` events** (`{"stage": "world", "message": ...}`) report progress to the client, which shows the message
   with its spinner; a final one has `done: true` (API.md). Messages: "Preparing the world...", "Building the
   setting...", then "Detailing <place>..." for each expansion, then "The world is ready.".
2. **Seed call** (`prompts/world/bootstrap.md`, the cheap model): from the setting, the opening situation, the party
   sheets and the private `gm_notes`, it records the region, the settlement and the exact opening place (each with its
   containing `parent`), the people, groups and ideas named, and the ties in each character's background (a home
   village, a rival, a debt) as entities with `known` facts. It sets the opening **scene** (the place, and who is there)
   and the **clock** (`start_hour`: "dusk" is 18, default 8, day 1). Containers are created before the things inside
   them. Seed facts have `source: seed` and turn 0.
3. **`gm_notes` become hidden facts**: the seed prompt turns each note into one or more self-contained `hidden`
   sentences. They surface through the briefing like any other hidden fact. The `## GM notes` section is now left out of
   the adventure system prompt whenever the world has anything in it. (It is still used when there is no world: the
   curator is switched off, or the game is an older save.)
4. **Expansion** around the opening, with the normal frontier rules but larger caps (5 entities, 16 new entities, 60
   generated facts): the opening place and who is there to full depth, its neighbours to a deeper sketch, as in 4.4,
   with the same independence checks.
5. `processed_through` is set to the length of the new history (the record is already digested), the briefing is built
   from the new world, and the first scene is requested.

If bootstrap fails (the curator errors, or records nothing), the turn fails with a retryable `upstream_error` and rolls
back like any other failure: the game stays in Session 0 with nothing changed and the player can confirm again. Because
the ops are applied to the turn's working state, the seed is committed atomically with the phase change. If the client
disconnects during the wait, the work is cancelled.

### 4.7 Turn digests

Each pass also writes a **digest** of every finished turn that has none: one to three sentences, past tense, naming
people, places, items, promises and the outcome (`prompts/world/digest.md`). They are made by the extraction model
(`AIGM_WORLD_MODEL`) in batches of 8 turns, oldest first, at most 40 turns per pass, through the optional curator
method `digest(DigestRequest) -> list[str]`. A curator without it (or a call that fails, or answers the wrong number
of digests) just leaves those turns without digests; the stage never fails the pass, and the next pass tries again.
A save from before digests is caught up over the next few passes.

A digest is `{start, end, turn, text, chars}`: the message range of its turn, the turn number, the text, and the size
of the original text. It is applied with the `AddDigest` op (a turn keeps its first digest; overlaps are refused) and
saved in `world.digests`. The messages are never removed, so the age-out thresholds (`AIGM_HISTORY_DIGEST_KEEP` and
`_STEP`) can be changed at any time, also for old saves, and the next request simply shows more or less of the
history in full. The first turn is never digested. Only what was said in play is digested, so a digest cannot leak
a hidden fact. `AIGM_HISTORY_DIGEST=false` stops writing them.

## 5. Generating a world that feels pre-existing

This is the central quality concern, so it is spelled out as rules for the expansion prompts (stored in
`prompts/world/`, editable like all other prompts).

### 5.1 The principle

Generate each place as if the world had been running for years without the party. The prompt asks the world-builder
questions about the thing *itself*: Who made it, who uses it, why does it exist, what happened here, who else wants it,
what lives or lies nearby, what would a traveler notice from outside? It is never asked "what would be interesting for
the party to find".

### 5.2 Locality and breadth

Expansion is local to the party's position, so the world grows like a real one gets uncovered: fully where they are,
sketchily next door, not at all far away. Within that, it generates **neighbors that have nothing to do with the current
quest** (a farm, a shrine, an unrelated rival) in a configurable ratio (default roughly one in three new entities). A
world where everything is relevant is the main tell of an improvised one.

### 5.3 Aspect checklists

A checklist per entity kind (files in `prompts/world/aspects/`), so "how much is enough" is concrete and the server can
compute gaps:

| Kind | Aspects |
|---|---|
| location (site) | `approach` (where it is, how to get there), `discovery` (how it is found, who knows about it), `entry` (how it is entered, obstacles, locks), `interior` (first one or two areas), `inhabitants`, `history`, `hazards`, `connections` (other places it links to), `secret` |
| location (settlement) | `layout`, `leaders`, `economy`, `notable_places`, `tensions`, `history`, `connections` |
| npc | `role`, `appearance`, `manner` (voice, habits), `motivation`, `relationships`, `knowledge` (what they know and would tell), `location` (where they are, routine) |
| faction | `goals`, `leaders`, `resources`, `methods`, `rivals`, `presence` (where they operate), `history` |
| concept | `nature`, `origin`, `who_believes_it`, `effects` |

A fact's `aspect` is set by the extractor/expander. Coverage is the set of aspects with at least one active fact. The
checklists are guidance, not quotas: an unremarkable cottage may need three.

### 5.4 Independence rules

Hard rules in the expansion prompt, plus a validator pass:

- No fact may state or imply it exists because of the party or the player's recent actions.
- Dates and causes of generated history precede the game (the mine collapsed "forty years ago", not "recently").
- No fact may refer to the party members.
- Generated NPCs have lives and goals that continue without the player.

A cheap validator (a regex for "the party", "the adventurers", party member names, and "you") rejects violations
server-side, and a rejected batch is regenerated once.

### 5.5 Everything is hidden until played

Generated facts start `hidden`. They become `known` only when the narration reveals them, so the player experiences
discovery, and the GM has a stable truth to be consistent with.

## 6. Using the KB in play

### 6.1 The briefing (automatic)

Before each request the server builds a **world briefing** from the KB, within a token budget (default about 2,000
tokens), in priority order:

0. A line with the world time (`Day 3, 14:00`).
1. The current location: its active facts (known and hidden), and its parent chain (the region and settlement it is in).
2. The NPCs present (`scene.present`): their role, manner, motivation, and what they know.
3. Adjacent places: name and one line each, with how they connect (what the party might walk toward).
4. Facts matched to the player's message (names, aliases, keywords) and to the previous GM message.
5. Pinned facts: anything marked quest-critical or recently revealed.
6. Pending corrections (6.4).

**Hidden facts are included** (decided): for the current location, the NPCs present and the adjacent places, they are
labeled so the GM can tell them from what the player knows:

```
## World notes
Location: The Harrow Mine, entrance (in the Thornwood, 3 miles ENE of Ashby)
- [known] The Harrow Mine was abandoned forty years ago after a collapse.
- [GM only, not yet known to the player] The lower gallery connects to the smugglers' cellar under Ashby.
...
```

Where it goes matters for caching. The system prompt stays stable. The briefing is added at request time as an extra
text block on the **latest user message** and is **not stored in history**, so history stays clean and every request
carries exactly one briefing, the current one. It is rebuilt for each request in the turn's tool loop (cheap, and it
picks up what tools changed). Implemented as `Game.request_messages`, which returns the stored history plus the notes in
a `<world_notes>` block; the block before it carries `cache_control`, so the history stays cached while the notes change
every turn (the Anthropic client then omits the automatic top-level breakpoint). The budget is
`AIGM_WORLD_BRIEFING_TOKENS`; sections are added in priority order and everything after the first line that does not fit
is dropped, while the clock and location lines are always kept.

Facts for entities outside the scene (matched from the conversation) include only `known` and `hinted` ones; the hidden
truth about them is available through `recall` (6.2). Pinned and recently-revealed facts and corrections are not in the
briefing yet (they need the curator, step 4).

### 6.2 `recall` (pull)

```jsonc
recall({ "about": "Harrow Mine" })        // by entity name or alias
recall({ "query": "who controls the toll road" })
-> the entity (kind, aliases, containing places, what it contains), up to 25 of its facts with id, label and
   text (known first, GM-only included), and what it is connected to;
   `query` gives up to 8 matching facts. An `about` that names nothing falls back to a text search.
```

For anything the briefing does not cover. The GM prompt says: **before stating a named person, place or fact about the
world that is not in your notes, call `recall` first.** If recall finds nothing, the GM may improvise, but must
`establish` it (6.3). Results are returned as the tool result (so they do show up in history for that turn, which is
fine, and are small).

### 6.3 `establish` and `set_scene` (write, in-turn)

- `establish({ "entities": [{ "name", "kind", "aliases", "parent" }],
  "facts": [{ "text", "about", "disclosure" }], "reveal": ["f0042"] })`
  records what the GM invented or settled, immediately: the GM invented a barmaid named Wren, so she is now in the KB
  before the turn ends. New entities are declared in the same call (a fact may only be about recorded entities or ones
  declared alongside it). Up to 6 entities and 12 facts per call. `disclosure` defaults to `known` (the narration just
  told the player); `hidden` and `hinted` are allowed. `reveal` lists ids of GM-only facts the narration just told the
  player; without it the briefing would keep calling them GM-only until the next curator pass, which is now several
  turns away.
  - **All or nothing:** the call works on a copy of the world; if any item is rejected nothing is recorded and the error
    lists every problem, so the model fixes them in one retry.
  - **Cheap reconciliation, deterministic only:** a name or alias that already exists is reused (an entity of a
    different kind is an error); a fact that nearly repeats an active fact about the same subject (word overlap of 0.8
    or more) is skipped and reported, not an error; invalid text, unknown entities and exceeded caps are errors.
    **Contradictions of known facts are not detected here**: that needs a model and is the curator's job (4.3, rule 1,
    with the correction note in 6.4).
  - Facts are `source: improvised`, stamped with the turn and the world time.
- `set_scene({ "location", "present", "elapsed_hours" })` lets the GM declare where the party now is, who is with them,
  and how much in-world time passed (0 to 720 whole hours; the clock moves forward). Places and people must already be
  recorded. Moving to a new location without giving `present` clears the list, so people are not carried along by
  accident. It is optional, since the curator also derives both; its value is that the very next briefing is right even
  if the curator has not run yet.

These two are cheap, structured, and keep the curator's job to catching what the GM did not record.

### 6.4 Self-correction

If reconciliation finds the GM contradicted a `known` fact, the next briefing includes a short note ("Correction: the
Harrow Mine was abandoned forty years ago, not recently. Reconcile this in your next reply if natural, without breaking
the fiction."). Nothing is retroactively edited. The note is stored in the world and shown in exactly one briefing (the
turn that displays it clears it on commit).

## 7. Interaction with the rest of the system

- **Tool loop / phases:** the world tools are offered in `adventure` only. The briefing is built in the loop alongside
  `game.system(state)` and `game.tools(state)`; `Game` gains `briefing(state, user_text)`.
- **Prompts:** new `prompts/world/` for the curator prompts and aspect checklists; the adventure GM prompt gains a short
  "World notes" section (how to read the briefing, the recall-before-inventing rule, the never-reveal-hidden rule). The
  `gm_notes` section is removed: bootstrap stores the notes as hidden facts (4.6).
- **History reduction:** done with turn digests (4.7, [HISTORY.md](HISTORY.md)); the full messages are kept and what
  the model sees is derived from them at request time.
- **LLM abstraction:** the curator uses its own `LLMClient`-style interface with structured output (JSON-schema
  structured output), configurable per stage, **cheap models wherever possible**: extraction, reconciliation and the
  independence check default to Haiku 5.5 (`AIGM_WORLD_MODEL`), and only expansion (including the bootstrap expand),
  where invention quality matters, defaults to Sonnet 5.5 (`AIGM_WORLD_EXPAND_MODEL`). Everything can be pointed at one
  model for tuning. Prompt caching on the static prompts.

## 8. API additions

Deliberately small: no client sees the world.

- **Save format v3** adds `world` (pretty-printed like the rest of the file); `GET /history/{name}` gains `fact_count`,
  `entity_count` and `world_time`.
- **One new SSE event**, `status`, used during bootstrap:
  `{ "stage": "world", "message": "Preparing the world...", "done": false }`, then a final one with `done: true` before
  the opening scene's `text`. Unknown events are already ignored by clients, so older clients just see a longer pause;
  the Textual client shows the message in its status line.
- No endpoint reads or writes the world. Inspection is the server-side dump (2.6). A debug-only `GET /world` can be
  added later if it is ever wanted.

## 9. Testing

- **Pure units** (no LLM): fact/entity validation and caps, indexes and retrieval ranking, briefing assembly and budget
  trimming, precedence rules in reconcile, frontier computation from a hand-built graph, the independence validator,
  supersession.
- **Scripted curator:** deterministic extract/expand outputs drive full flows in test mode: bootstrap on `begin`, a pass
  once enough narration has accumulated (and not before), a reveal turning hidden into known, a contradiction rejected,
  concurrent `establish` during a pass.
- **Dump:** the world dump is valid JSON, indented, grouped by entity, one fact per line, and never a single line.
- **Time:** the clock only moves forward, is stamped on facts, and appears in the briefing; reserved fields round-trip.
- **Bootstrap:** `begin` in test mode emits `status` events, then the opening; a bootstrap failure rolls the phase back;
  `gm_notes` end up as hidden facts and not in the system prompt.
- **Persistence:** save/restore round trip including `processed_through`; v2 saves load with an empty world; a save
  taken mid-pass.
- **Staged state:** a failed turn that called `establish` leaves the KB unchanged.
- **Live (opt-in, like `test_live`):** a short real run checking the generated facts pass the validator and fill the
  requested aspects. Quality ("does it feel pre-existing") will need human review of sample worlds; a small script that
  prints a generated world is part of the build.

## 10. Risks and open questions

Risks:

- **Spoilers from hidden facts in the GM context.** The model may leak them. Mitigated by labeling and prompt rules; a
  lighter-weight alternative is to omit hidden facts from the briefing except for the current location and NPCs present
  (the default here).
- **Drift and bloat.** Curator output can be repetitive or inconsistent. Mitigations: caps, mandatory connection to
  existing entities, dedupe, the validator, and keeping facts atomic.
- **Cost and latency.** Roughly one extract and one reconcile call every few pages of narration (several turns) plus an
  occasional expand; all background and on smaller models where possible. Needs measuring with real keys; the per-stage
  model settings, the pass frequency (`AIGM_WORLD_EVERY_PAGES`) and the page size are the knobs.
- **Entity resolution errors** ("the old mine" vs a second mine). Aliases plus the world dump file (2.6) for spotting
  them; merge tooling can come later.

## 10. Decisions

Taken after review of the first draft:

1. **Bootstrap latency:** the player waits. The world is seeded after `begin_adventure` and before the first scene, with
   `status` events so the client can show progress (4.6).
2. **Hidden facts:** included in the GM's briefing for the location, the NPCs present and adjacent places (6.1).
3. **Journal:** none. No client-visible world. Debugging is a server-side, pretty-printed, entity-grouped world dump
   file (2.6) plus pretty-printed saves.
4. **World time:** in v1 as a stored clock with timestamps and reserved validity fields, shown to the GM as one briefing
   line, and otherwise inert (2.4). Nothing changes over time yet, but the schema is ready.
5. **Models:** cheap models wherever possible: Haiku 5.5 for extraction, reconciliation and the independence check;
   Sonnet 5.5 only for expansion; all configurable (7).
6. **`gm_notes`** become hidden facts and their prompt section is removed (4.6).
7. **`processed_through`** is the digest watermark, saved with the world, and is the marker history compaction will use
   later (2.4, 7).

8. **Elapsed time:** the narrator is responsible for being precise. The adventure prompt requires the GM to state
   elapsed time at least to the granularity of "a few hours" whenever time passes (rest, travel, waiting), and never to
   leave it as "some time later". The extractor only records a clock advance the narration states or clearly implies at
   that granularity, and otherwise leaves the clock alone. A dedicated tool to pass time without narration is deferred
   to a later version.
9. **Dump in test mode:** the world dump file is also written in test mode, so tests can inspect it.

## 11. Build order

1. (done) Data model, indexes, validation and the repository/save format v3 (pure Python, fully unit-tested).
2. (done) Briefing assembly (including the clock line) and its injection in the loop; adventure prompt additions.
3. (done) `recall` / `establish` / `set_scene` tools and their staged-state behavior.
4. (done) Scripted curator and the pass scheduler (extract, reconcile, apply, concurrency).
5. (done) Real curator prompts and models; expansion with aspect checklists and the independence validator.
6. (done) Bootstrap at `begin_adventure` with `status` events and the client status-line support; removal of the
   `gm_notes` prompt section.
7. (done) The world dump file and helper, docs.
