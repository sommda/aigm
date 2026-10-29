# AIGM Campaigns: Predesigned Adventures, the Designer, and Distillation

Status: **brainstorm, no code**. Part of the graphical app design; start with [APP.md](APP.md). This document adds a
library of **campaign packs**: partly authored adventures that the AI plays differently each time. The first packs are
**short campaigns** (one sitting or two) set in a few **shared worlds**, section 3. It also covers the tools to make
them (a scenario designer that can run in Claude Code) and a way to **distill** reusable material out of existing game
transcripts.

It builds on [STORY.md](STORY.md) (the story plan), [WORLD.md](WORLD.md) (the knowledge base and curator),
[OPENING.md](OPENING.md) (the opening and character knowledge), [NEXT_TALE.md](NEXT_TALE.md) (the chronicle) and
[ROLEPLAY.md](ROLEPLAY.md) (motives).

## 1. Goals

1. **Better stories.** Human-designed structure, cast, secrets and set pieces, with the AI doing what it does well:
   voice, improvisation, reacting to the player. This is the product's differentiator.
2. **Reusable assets.** Because a pack has a known cast and known places, its portraits, illustrations and maps can be
   made once and reused in every playthrough ([ART.md](ART.md)).
3. **Replayability.** The same pack should play out differently: different culprits, routes, allies and endings, plus
   whatever the player's own choices and the AI's improvisation add.
4. **A pipeline, not a pile of files.** A designer (you, using AI help) can produce a pack in hours to days, and can
   mine real play for material.

Non-goals for the first release: a public authoring tool for players, a marketplace, and packs in languages other than
English.

## 2. Why AI games feel thin, and what packs change

The common failures of AI-run stories, and the part of the design that answers each:

| Failure | Cause | Answer |
|---|---|---|
| Generic fantasy flavor | the model's average output is the average of its training data | an authored **voice and style guide**, authored names, places and set pieces |
| No real mystery | the model invents the answer as it goes, so nothing was ever hidden | secrets, clues and culprits fixed **before** play (the hidden-fact machinery in WORLD.md already supports this) |
| Meandering plot | no structure, or structure invented once and forgotten | the milestone graph and endings from STORY.md, authored, with pacing rules |
| Flat NPCs | NPCs invented mid-scene with no wants | authored **motives, tells and voice samples** per NPC ([ROLEPLAY.md](ROLEPLAY.md)) |
| Everything is easy or everything is a fight | no sense of stakes or escalation | authored escalation, set-piece scenes and cost-bearing choices |
| Nothing pays off | clues and callbacks are forgotten | a **clue graph** and a list of planted setups with required payoffs |
| Sameness across sessions | the same prompts and no variation | **variation points** resolved at the start, plus a pool of twists |
| Prose tics | the model repeats phrases and rhythms | style guide with banned phrases and sample passages; an automated tic check on output |

The model remains the narrator. Humans decide *what is true and what matters*; the AI decides *how it is told and what
happens when the player does something unexpected*.

### 2.1 Narrative quality is also a runtime concern

Packs are necessary but not sufficient. Other levers, each cheap compared with the cost of a bad story:

- Spend tokens where story quality shows: a stronger model and thinking on for chapter openings, reveals,
  confrontations and endings; Haiku for routine turns ([TURN_COST.md](TURN_COST.md) section 4.7).
- A **style guide in the prompt** (voice, sentence rhythm, banned phrases) kept short and stable so it caches.
- **Authored set-piece text** delivered at the right moment (section 5).
- A short **"story state" note** each turn for the narrator: active tension, what the player suspects, what is about
  to pay off, from the clue graph.
- A **critic pass** in testing (section 9), not in play: a stronger model reads transcripts and scores them against a
  rubric.

## 3. World packs, campaign packs and short campaigns

### 3.0 Decision: start short, in shared worlds

The first campaigns are **short**: the `short` length in [STORY.md](STORY.md) (two or three quests per chapter, three
chapters), about 2 to 4 hours of play in total, or 60 to 120 turns. Several campaigns share one **world**.

Why this is a good start:

- **Cheap to make and to test.** A short campaign needs 5 to 10 authored scenes, a cast of 6 to 12, and 3 to 6
  illustrations. `pack sim` can cover it in a few hundred bot runs.
- **Cheap to run.** About 100 turns per playthrough; a complete story fits the free tier or one purchase.
- **Fast learning.** You find out in weeks, not months, whether the pack format, the variation and the style guide
  produce better stories.
- **Replayable by design.** Two or three slots with real consequences give different stories within one evening.
- **Art is shared.** The world's map, places and recurring cast are made once and serve every campaign in it.
- **A path to depth.** The chronicle ([NEXT_TALE.md](NEXT_TALE.md)) lets a character carry on from one short campaign
  into the next, so a series feels like a long campaign made of episodes.

The cost of short: less room for a slow-burn mystery or a convoluted route, so each campaign must have one strong idea
and a clear first scene. The long-game ideas in STORY.md (a convoluted path, large quests) wait for later.

### 3.0.1 Two kinds of pack

| Kind | Holds | Used by |
|---|---|---|
| **World pack** (`worlds/<world-id>/`) | the setting's history and tone, the style guide, the map and places, the recurring cast and factions, the shared art, the lore a player can learn | every campaign in that world |
| **Campaign pack** (`campaigns/<id>/`) | one story: premise, the cast that is new, the plot graph, clues, scenes, variation slots, and the new places and assets it adds | one adventure |

A campaign names its world (`world: dawn-reach@1.2`) and may use any of its places and people, add new ones, and
**override nothing** in the world's fixed facts. The world pack is the canon; campaigns are episodes set in it.

Shared-world rules:

1. **Canon is fixed.** A campaign never contradicts the world pack. If it needs a change (a ruined bridge), that is a
   new world version, or a *campaign-local* fact that holds only in that campaign.
2. **Every campaign starts from canon,** not from the results of another campaign. Playing campaign A does not change
   campaign B's world for the same player by default, which keeps each pack testable. An optional **carry-over**
   brings the character (level, gear, a few named flags such as "the player spared the smuggler") through the
   chronicle.
3. **A campaign declares which places and cast it uses,** and they come with their art. The world pack decides their
   appearance facts; campaigns may add *situation* facts (where Captain Fenn is this week) but not change who they
   are.
4. **Each campaign has its own timeline slot** in the world ("the spring after the flood"), so recurring characters do
   not need to be in two places at once.
5. **World versions** are semantic: a patch fixes prose, a minor adds places or cast, a major changes canon. Campaigns
   pin a version range and the loader refuses an incompatible pairing.

### 3.1 Three layers

| Layer | What it is | Examples | Who decides |
|---|---|---|---|
| **Fixed** | always true in every playthrough | the setting's history, the main cast's appearance and personalities, the places, the voice, the set-piece prose, the clue structure | the designer |
| **Variable** | chosen from authored options when the game starts | who the traitor is (one of three candidates), where the artifact lies (one of four sites), which faction is the ally, the final twist | a seeded random choice, then checked for coherence |
| **Generated** | invented during play | minor people and places, dialogue, the player's own subplots, consequences of unexpected actions | the AI under the existing world rules |

The line between fixed and variable is the main design decision in each pack. More fixed means better prose and art
reuse; more variable means more replay value. A good default: fix the **world, the cast and the places**, vary **the
secret, the route and the ending**.

### 3.2 Layout on disk

A campaign pack is a folder in the repository (`campaigns/<pack-id>/`), human-readable and reviewable in a pull
request. World packs (`worlds/<world-id>/`) use the same layout for the parts they share (`style.md`, `cast/`,
`places/`, `factions.yaml`, `assets/`, plus `lore.md` and a `timeline.yaml`):

```
campaigns/dawn-accord/
  pack.yaml            manifest: id, title, version, world and version range, rating, levels, length, rulesets, tags
  premise.md           the pitch, themes, tone, what makes it distinct (also the library blurb)
  style.md             voice guide for this story, layered over the world's (campaign overrides win)
  uses.yaml            world cast and places this campaign uses, with this campaign's situation facts
  cast/                the cast that is new: look, voice, wants, fears, secrets, motives, relationships
  places/              the places that are new: description facts, connections, secrets, optional site grid
  plot.yaml            goal, milestones with requires, chapters, endings (the STORY.md structure)
  clues.yaml           what is learned where, redundancy, which secrets each clue supports
  scenes/              authored set pieces (section 5)
  variation.yaml       slots, their options, constraints, and the twist pool (section 4.2)
  party.yaml           suggested characters, or the creation rules and the hook for each
  assets/              portraits, plates, maps, with a manifest tying each to a cast member, place or moment
```

### 3.3 Cast and place files

Each file is a short YAML front matter plus prose. A person, for example:

```yaml
id: tobin
name: Tobin
role: kitchen boy
appearance:               # these are "known" facts: the art must match them, so they are fixed
  - about eleven, small and wiry, ash-brown hair he cuts himself
  - an apron two sizes too large, cinched with twine
voice: talks fast and low, interrupts himself, trades gossip like coin
motives:
  - {kind: want, scope: underlying, strength: driven,
     text: wants to be made a proper page of the east wing}
  - {kind: fear, scope: underlying, strength: driven,
     text: fears being sent back to the harbor lanes}
secrets: []               # hidden facts, with ids the clue graph can refer to
portrait: assets/portraits/tobin.webp
```

Existing structures are reused: facts become `known`, `hinted` or `hidden` facts; motives are the motive records
already built; relationships become fact links. The compiler (section 4.1) is the only new code that has to understand
the format.

### 3.4 Two rules that protect art reuse

1. **Art attaches to people, places and moments, never to plot roles.** If the traitor is chosen from three
   candidates, each candidate already has a portrait; whichever is picked, the art is valid. A pack is never allowed
   to put "the traitor's face" in an asset.
2. **Appearance facts are fixed and known.** The narrator must not contradict a portrait. Whatever the art shows is
   written into the pack as a known appearance fact, and the briefing carries it.

## 4. Running a pack on the existing engine

### 4.1 Compile, do not interpret

A pack is **compiled** into the structures the server already runs, at game start. There is no second engine.

| Pack element | Becomes | Notes |
|---|---|---|
| `premise.md`, places, setting | the campaign record (`setting`, `opening`) | replaces what Session 0 would have written |
| Hidden material | `gm_notes` and hidden facts | `source: pack`, a new value beside `seed` and `generated` |
| Cast and places | entities and facts, with motives | the bootstrap seed pass is skipped or reduced to "fill gaps" |
| `plot.yaml` | the story plan (goal, milestones, endings) | the plotter pass is replaced for chapter 1 and **given the pack plan as input** for later chapters, so it fleshes out rather than invents |
| `clues.yaml` | milestone `gives`, hidden facts with `reveal` conditions, and the story note | checked by the linter |
| `style.md` | a prompt section kept stable per pack | cached |
| `scenes/` | scene triggers in the briefing | section 5 |
| `assets/` | art records on entities | no generation at runtime |
| `variation.yaml` | resolved slots, stored in the game state | section 4.2 |

**With a world pack,** the world is compiled first, then the campaign on top. Only the places and people the campaign
lists in `uses.yaml` (plus their neighbors, as places the party might go) are loaded into the game's world store, so
the briefing stays small and the player cannot meet or learn about cast the story does not use. The rest of the world
pack stays available as lore the narrator can be handed by id when the player asks about it. Facts that came from the
world pack carry `source: pack` and a `pack: <world-id>` tag, so the compendium, the chronicle and `recall` treat them
like any other fact.

Pack facts are protected: the curator's reconcile and expand passes treat `source: pack` facts as fixed, may add
around them, and may not contradict or delete them. The "no floating entities" and independence rules of WORLD.md
apply unchanged.

### 4.2 Variation

At game start the server resolves the pack's **slots**:

```yaml
slots:
  traitor:
    options: [captain_fenn, steward_morlowe, liessa_aide]
    weights: [1, 1, 1]
    sets:
      captain_fenn: [secret: fenn_sold_keys, clue_set: fenn_clues, ending_bias: bitter]
  vault_site:
    options: [flooded_cistern, chapel_crypt, kiln_cellar, harbor_warehouse]
    requires: {vault_site != previous_game}
  twist:
    pool: [the_ally_betrays, the_prize_is_a_lie, the_villain_is_right]
    pick: 1
constraints:
  - traitor == liessa_aide implies twist != the_ally_betrays
```

The steps:

1. **Seeded choice.** Pick values for the slots from a seed stored with the game, honoring weights, constraints and
   per-player memory (do not repeat last time's picks for the same player and pack).
2. **Coherence pass.** One cheap model call reads the resolved slots and the pack and rewrites the connective details
   (one line per affected cast member: what they would be doing, who they distrust), checked against the pack's facts.
   It never changes fixed facts.
3. **Compile** the resolved choices into hidden facts, milestone variants, and the ending set.
4. **Store** the resolved slots and the seed in `GameState.pack_state` with the pack version, so a game can be
   reproduced, saved, restored and migrated.

Replay value then comes from four sources, in increasing unpredictability: slot choices, the player's character and
choices, the twist pool, and AI improvisation. A designer controls the first and third; the AI controls the fourth;
the player controls the second.

**How many variations are enough?** For a short campaign, two or three slots (for example the culprit, the site of the
vault, and the final twist) are enough, with each option changing how the story feels, not only a name. For longer
packs, three to five slots with three to four options each give a few hundred combinations, far more than a typical
player will exhaust. More slots multiply authoring and testing work faster than they multiply perceived variety;
prefer fewer slots whose options change the *feel* of the story, not only a name.

### 4.3 What the player picks

At start the player chooses a world and a campaign from the library, and a character (a pregenerated hero from
`party.yaml`, or the creation flow with the pack's hook). The long Session 0 conversation disappears for pack games. A
custom game (today's Session 0) stays as another entry in the library, with its place in the tiers (section 8).

### 4.4 Versioning and saves

A pack has a version. A save records the version it started on. Minor edits (prose fixes) apply to running games; a
major version is a new pack id or leaves running games on their old copy. The loader keeps old versions available.

## 5. Authored scenes (set pieces)

A scene is a human-written moment the AI is asked to deliver faithfully.

```yaml
id: lantern_passage_descent
when:
  location: sealed_passage
  first_arrival: true
  requires: [lamp_lit]
mode: guided            # verbatim | guided | beats
read_aloud: |
  The stair goes down further than the lamp can follow. Somewhere below, water is counting the seconds.
beats:
  - the walls change from palace brick to older pale stone
  - the party notices a bronze plate stamped with a lantern
  - a low hum starts, felt more than heard
npc_objectives:
  oswin: stay silent unless addressed; he is listening for the guards
outcomes:
  - when: the party reads the plate
    sets: [clue.lantern_mark]
choices:                # optional authored cards (CHOICES.md)
  - {label: "Read the bronze plate", kind: look}
  - {label: "Listen to the hum", kind: look}
```

Modes:

- **verbatim**: the exact text is shown (as a chapter opening, a letter, a prophecy), then the narrator continues. For
  moments where the prose must be right.
- **guided**: the narrator is given the read-aloud text as the target, the beats as required content, and the NPC
  objectives, and writes it in its own flow. The default.
- **beats**: only the beats and objectives; the narrator invents the words.

The server decides when a scene is active (its `when` conditions over location, milestones, clues, time) and adds it
to the briefing for that turn. It marks the scene done when its outcomes are reported, so it fires once. Authored
`choices` are offered to the choice writer as required or suggested cards.

Scenes are the main place human prose enters the product, so give them the designer's time: a pack of 40 hours of play
may need only 10 to 20 scenes to feel authored.

## 6. Art reuse

A pack ships its assets, made once ([ART.md](ART.md) sets the small scope):

- one **portrait** for each new speaking cast member (recurring cast come from the world pack);
- a handful of **plates** tied to named moments (the opening, each chapter's turn, each ending, a few set pieces);
- a **region map** and a few **site plans** for places that matter (mostly owned by the world pack);
- an **asset manifest** linking each file to its cast member, place or moment, with alt text.

Because art is tied to people and places, every playthrough uses all of it regardless of variation. Generic and minor
characters use the shared portrait library. This is the main reason the art budget can stay "just enough": a pack's
art cost is paid once and amortized over every playthrough and every player.

Shared worlds multiply the saving. The **world pack owns the region map, the place plates, and the portraits of the
recurring cast**; each campaign adds only its new cast, a few moment plates (4 to 6 for a short campaign) and any new
places. By the third campaign in a world, most of the art a player sees is already made. The cost of this is a
constraint on designers: reuse the world's places and people when you can, and add a new place only when the story
needs it.

## 7. The scenario designer

An AI-assisted workflow, run in Claude Code, that turns an idea into a validated pack. The human decides; the AI
drafts and checks.

### 7.1 The workflow

Each stage ends with files in the pack folder and a human review.

0. **World** (once per world, then rarely): the setting's history, tone, map, recurring cast and factions, the shared
   style guide, and the art list. Treat this as the larger design job; every campaign inherits it.
1. **Brief**: the pitch, tone, themes, target level and length (short), the central question, and which world places
   and cast it uses. The designer writes a paragraph; the AI proposes three directions and asks questions.
2. **Premise and style**: `premise.md`, `style.md` with sample paragraphs the designer edits until the voice is right.
3. **Cast**: the main cast with wants, fears, secrets, motives, voice samples and relationships. The AI checks that
   every secret has someone who guards it and every motive could produce a scene.
4. **Places**: the map of the world, connections, secrets; optional site grids from templates.
5. **Plot**: goal, milestones with `requires`, chapters, endings. The AI checks the same properties the plotter is
   held to (STORY.md section 5): reachable milestones, a goal above the party's starting strength, two to four
   different endings.
6. **Clues**: for each secret, at least three independent ways to find it (so one missed roll or one wrong turn never
   blocks the story), and the order in which they unlock.
7. **Scenes**: the set pieces, with the designer writing or heavily editing the read-aloud text.
8. **Variation**: choose slots and options; the AI proposes twists and checks constraints.
9. **Assets**: the AI produces the shopping list (portraits, plates, maps) and prompts for the art pipeline; a human
   reviews and approves the generated pictures.
10. **Validate, simulate, playtest** (section 7.2 and 9).

### 7.2 The tools behind it

Small command-line tools in the repository, used by the designer workflow and by CI:

| Tool | Does |
|---|---|
| `pack validate` | checks the schema and references (every id exists, every file is present) |
| `pack lint` | checks design rules: unreachable or cyclic milestones, a secret with fewer than three clues, a hidden fact that leaks into a `known` text, an appearance not matched by an asset, too many slots, banned phrases in authored prose, content outside the ruleset's allow-list ([LAUNCH_RULESETS.md](LAUNCH_RULESETS.md)) |
| `pack compile` | produces the world ops, story plan and briefing text for a resolved slot set, so a human can read exactly what the engine will see |
| `pack run` | starts a game from the pack in test mode or with the real model, for hand play |
| `pack sim` | plays the pack with scripted or model-driven **player bots** of different temperaments (thorough, reckless, chatty, stealthy, lazy) over many seeds, and reports coverage and dead ends (section 9) |
| `pack stats` | shows slot coverage, scenes fired, endings reached and cost per run |

### 7.3 Running it in Claude Code

Package the workflow as a Claude Code **skill** in the repository (for example `.claude/skills/scenario-designer`)
with:

- the stages above as a checklist the skill walks through, one at a time, asking before moving on;
- the schema and a worked example pack as reference files;
- subagents for the independent checks (continuity of the cast, clue redundancy, voice consistency against
  `style.md`);
- the commands in 7.2 for the AI to run, so every claim ("every milestone is reachable") is a tool result, not an
  opinion.

Because packs are plain files under version control, every change is a diff you can read, and a pack's history is its
design history.

## 8. Distilling transcripts

The goal: take a game that went well and extract reusable material, without producing a pack that simply replays one
player's story.

### 8.1 Inputs

A save already contains much of what is needed: the message history; the world store with entities, facts and motives
and their `source`; the story plan with milestones, `outcome` notes and the `choices` log; the digests; the
corrections log; and the metrics (stalls, slow turns).

### 8.2 The distiller

A pipeline, run as an offline tool (`pack distill <save>`), with a human review step at the end:

1. **Segment** the transcript into scenes using scene changes, milestone boundaries and digests.
2. **Describe** each scene in a few lines: where, who, what the tension was, what the player did, how it resolved.
3. **Score** scenes. Cheap signals first (the length and variety of player input, successful social checks, reveals, a
   milestone completed, a fight with real stakes, the player's own wording). Then a stronger model reads the top
   candidates and rates them against a rubric (tension, specificity, surprise, voice).
4. **Extract**, by kind, and decide whether each piece belongs to the **world** (recurring, lasting canon) or to a
   **campaign** (belongs to this story):
   - **People**: their facts, the motives that emerged and their tells, sample lines of their voice. Generalize the
     player's character out (replace the player's name with a role).
   - **Places**: facts, connections, secrets, and the map position.
   - **Plot structure**: the milestone graph as played, the clue chains the player followed, the endings, and the
     choices that mattered. Flag where the story stalled or the plan was repaired.
   - **Set-piece candidates**: the best scenes, reduced to read-aloud text, beats and outcomes, with the
     player-specific parts removed.
   - **Twists and complications** that worked, as entries for the twist pool.
5. **Generalize.** This is the step that stops the pack from being a replay. Turn what the player chose into
   **slots**: the culprit the player found becomes one of three candidates; the route they took becomes one of several
   routes; the ally they won becomes a role several people can fill. The model proposes the alternatives; the designer
   approves.
6. **Draft the pack folder**, with a report: what was extracted, what was dropped and why, what looks weak, where more
   variation is needed.
7. **Human review**: a diff-style review of each file, accepting, editing or rejecting. Nothing enters the library
   without review.

### 8.3 The element library

Distillation also feeds a shared **element library** of smaller reusable parts across packs: NPC archetypes with voice
samples, location templates and site grids, encounter patterns, scene templates, twist ideas, clue patterns. The
designer can assemble a new pack partly from tagged elements, and the library grows with every distilled game. Keep
each element's provenance (which game it came from) and its review status.

### 8.4 Rules for using real transcripts

- Distill your own playtests freely. For players' games, the terms of service must say that games may be analyzed to
  improve the product, and the distiller must strip names, personal details and anything the player typed that is
  personal.
- Never copy a player's creative text into a pack without their permission; extract *structure and patterns*, and
  rewrite the prose.
- Keep the review step. A model that summarizes its own earlier output tends to amplify its habits (the same phrases
  and names); the human pass is how those are removed.

### 8.5 A first test: the Aurendell game

The `aurendell` save in `server/saves` is a real example: a structured campaign with a goal (the Dawn Accord), a cast
with motives, a sealed passage and vault, and a played chapter. It is the natural pilot: run the distiller on it,
review the draft pack, and see how much of it survives as something another player could enjoy.

## 9. Measuring story quality

Build the checks before building many packs.

| Measure | How |
|---|---|
| **Structural soundness** | `pack lint`; every milestone reachable; every secret findable by at least three routes |
| **Coverage and dead ends** | `pack sim` over many seeds and bot temperaments; report scenes never fired, endings never reached, stalls (no progress in N turns) |
| **Distinctness** | compare runs of the same pack: milestone order, endings, the set of scenes seen, and a summary-embedding distance. Target: two random runs share the fixed skeleton but differ in secret, route and ending |
| **Prose quality** | a stronger model scores sampled turns against a rubric (specificity, voice match to `style.md`, subtext, restraint, no clichés), with a human spot check; the style guide's banned phrases counted automatically |
| **Hint discipline** | a scan for hidden facts that were stated outright |
| **Continuity** | the corrections log: how many times the world model had to correct the narrator |
| **Real players** | in the beta: completion rate, turns per session, return rate per pack, thumbs on the ending, free-text comments |
| **Cost** | tokens and credits per run, by stage, from the metrics |

The replay harness in [TURN_COST.md](TURN_COST.md) section 8 is the shared bench for these.

## 10. The library as a product

- **Worlds and series**: the library is organized by world. Each world shows its map, its campaigns in a suggested
  order, and the player's progress. A series of short campaigns in one world is a natural unit to sell and to market.
- **Browsing**: cover art (one plate), a blurb from `premise.md`, length, level range, content rating, tags, how many
  endings you have found. Show a "new twists" badge when a pack has been revisited.
- **Replay**: "play again" starts the same pack with new slots and, optionally, the same character carried forward
  through the chronicle ([NEXT_TALE.md](NEXT_TALE.md)).
- **Tiers**: the free tier gets one short campaign, or its first two chapters; a short campaign is a bounded cost, so
  a full story can be free if the numbers allow it. Paid tiers open the library. Whether a pack is included, or an
  add-on sold in credits, is a pricing decision ([APP.md](APP.md) section 8). Custom games (the open Session 0) are a
  paid feature because they cost more per turn (the model plans everything) and carry less polish.
- **Content ratings**: each pack declares one; the store listing and parental controls follow.
- **Seasons**: a steady release of packs is itself a retention strategy. Plan for a pipeline that produces a pack in
  days, not months; that is what sections 7 and 8 are for.

## 11. Legal and ownership notes

- Packs you write are yours; keep a record of what a human wrote and decided. Copyright in purely AI-generated
  material is uncertain in some countries, and human authorship is what is clearly protectable, so the designer's own
  edits and selections matter and the version history proves them.
- Packs must stay within the open content of the launch rulesets and use no publisher settings or creatures
  ([LAUNCH_RULESETS.md](LAUNCH_RULESETS.md)); `pack lint` enforces the allow-list.
- Commissioned or generated art keeps its own license terms; the manifest records the source.

## 12. Build order

1. **Pack schema and loader**, including world packs and the `world:` reference: parse a pack folder and compile it
   into the campaign record, world ops and story plan, with `source: pack` facts protected. Test with a tiny
   hand-written pack in test mode.
2. **Validate and lint**, with the checks that need no model.
3. **Pilot world and campaign from the Aurendell save** (Aurendell as the world pack; the Dawn Accord's first chapter
   as a short campaign), first by hand, to learn what the format is missing. Then write a **second short campaign in
   the same world** to test sharing.
4. **Variation**: slots, constraints, the coherence pass, `pack_state` in saves.
5. **Authored scenes** in the briefing, and the story note.
6. **`pack sim` and the quality measures** with player bots.
7. **The designer skill** in Claude Code, using the lessons of 3 to 6.
8. **The distiller**, then the element library.
9. **The library screens** in the app.
10. **Packs 2 to N** with the pipeline: three to five short campaigns in the first world before starting a second
    world.

## 13. Risks and open questions

| Risk | Mitigation |
|---|---|
| The AI contradicts or flattens authored material | `source: pack` protection in the curator; scenes in verbatim or guided mode; a continuity check in `pack sim` |
| Variation produces incoherent stories | few slots, explicit constraints, a coherence pass, and `pack sim` coverage runs |
| Packs feel railroaded | clue redundancy; every milestone has several ways; the player's free text always allowed |
| Authoring cost is higher than expected | start with short packs; reuse the element library; build the distiller early so real play seeds the next pack |
| Players find the pack's secret online | the variable layer: the secret differs per run |
| The pack format ossifies too early | build three packs by hand before freezing the schema |
| Campaigns in one world drift apart or contradict canon | world packs are canon; `pack lint` checks each campaign against its world; world versions are pinned |
| Short campaigns feel thin | one strong idea each, authored scenes where it matters, and a series with carry-over to give continuity |
| The shared world makes every story feel alike | the style guide layers (campaign overrides world), each campaign has its own tone and central question, and new cast and places are added per campaign |

Open questions:

1. Which world first? Aurendell is a ready candidate because a played game, a cast and a vault already exist.
2. Should a pack control the ruleset, or work under either launch ruleset with a translation table for levels and
   threats?
3. Should the free tier be a whole short campaign, or only its first chapter?
4. Do you want player-facing "campaign journals" (a written recap of the playthrough as a keepsake) built from the
   chronicle and the plates?
5. Who reviews packs for quality: you alone, or a small group of playtesters, and what is the release bar?
