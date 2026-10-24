# AIGM Opening: Character Knowledge and the Setting Overview

Status: built (server and client). Differences from the first draft are in section 14.

This is the design for a better start to a new adventure: the characters arrive knowing things, the compendium shows it
from the first turn, and the player gets a short picture of the setting before the action begins.

## 1. Goal

- **Characters know their world.** A rogue called the "Ghost of the Docks" knows the docks, the people who work there
  and the trouble to avoid. A character raised near the court knows the castle and the habits of the nobility. What
  each one would plausibly know is written into the world as `known` facts at the start of the game.
- **The compendium shows it at once.** The first time the player opens it, it already holds the places, people and
  groups the party's backgrounds make familiar, with what they know about each, and says whose knowledge it is.
- **Backgrounds shape the world.** The locations and NPCs created at the start take the party's backgrounds into
  account. They are not generic scenery plus a note about the characters.
- **A short overview comes first.** Before the opening scene, the GM gives a brief picture of the setting, so the
  player is oriented before they are asked to act.

### Non-goals

- Per-character knowledge in play. The compendium stays one list for the whole party (COMPENDIUM.md): the player
  controls every character, so what any one of them knows, the player knows. Section 4 only records *whose* knowledge
  a starting fact was.
- Rebuilding the world of a game already under way. This applies to adventures that begin after the change; existing
  saves can be given the knowledge with the backfill (section 9).
- Character sheets, stats or abilities in the world. Only the people, places and groups around a character are
  recorded, never the character.
- New dice mechanics for "knowing". There is no lore skill check for the starting knowledge; it is simply given.

## 2. What happens today, and why it falls short

Traced through the "docks" save (`saves/docks-20261023-1225.json`):

1. **The backstory never reaches the server.** The party sheets hold species, class, scores and gear. "Toby" is a
   level 1 rogue with no mention of the "Ghost of the Docks". Session 0 does not ask for a background, the
   `begin_adventure` tool has no field for one (only `name` and `sheet`), and Session 0 is thrown away at the start. Any
   background discussed there is lost unless it happens to be in the sheet.
2. **The bootstrap prompt is cautious by design.** Its "Character ties" rule records the people and places a background
   *names*, and says "do not invent anything beyond the record and the notes". With no background in the record, there
   is nothing to record.
3. **Expansion hides everything.** The world-builder runs around the opening place and writes `hidden` facts only (the
   rule in WORLD.md 5.5, which is right for the rest of the world). In the docks save, 15 of the 18 facts after
   bootstrap are hidden, and the 3 `known` ones are one line each (Droon, the castle, the Sunken Anchor).
4. **The compendium therefore starts nearly empty**: three entries with one sentence each, and no characters.
5. **The first reply is straight into the scene.** The begin cue is "Open with the first scene", and the style prompt
   says one to three short paragraphs. The setting was told to the player in Session 0, but the game itself never
   restates it, and a replay or a loaded save starts cold.

## 3. Overview of the change

Four changes, in the order the data flows:

1. **Session 0 captures a background per character** and `begin_adventure` carries it (section 4).
2. **A new curator step, the familiarity pass,** runs during bootstrap. It turns each background into named places,
   people and groups, with `known` facts attributed to the characters who know them (section 5).
3. **The briefing and the compendium use the attribution** (section 6).
4. **The first reply opens with a setting overview**, then the scene (section 7).

The independence rule (the world exists without the party, WORLD.md 5.4) is kept. The familiarity pass writes facts
about the world, not about the party. The link to a character is metadata (`via`), not part of the fact text.

## 4. Backgrounds

### 4.1 Session 0

The party section of the Session 0 prompt (`system/session_zero/02_party.md`) gains a step: after the mechanics, give
each character a short **background** and tie it to the setting. The GM asks for it, or proposes one when the player
says "you decide". A background covers, in a few sentences:

- where the character comes from and what they did before (trade, upbringing, calling);
- reputation, nicknames, contacts, debts, enemies: the people and places that *know them*;
- which part of the setting is home ground, and which parts they know only by hearsay or not at all.

Rules for the GM, so the party reads as part of the setting rather than pasted onto it:

- **Tie each character to the setting.** Every character has at least a passing link to the starting region, unless
  the player wants an outsider (a stranger knows little, and that is allowed; section 5.3).
- **Spread the ties.** Prefer backgrounds that touch different parts of the setting, so that no area is known by
  everybody and none by nobody. In the docks game: the rogue knows the docks and the underworld, another character
  knows the castle and the nobility, a third knows the temples or the guilds. The GM suggests this when proposing
  backgrounds and does not override a player's choice.
- **Name the setting's pieces.** "Grew up on the docks" is a start; the GM should offer the curator specifics to build
  on ("worked the Sunken Anchor pier as a boy; the Silt-Walkers know him by sight").

### 4.2 `begin_adventure`

Each party member gains a `background` string next to `name` and `sheet`.

- It is **required** for new games, with a minimum length (about 80 characters, like the other minimums), and the same
  rejection message style: "'background' is too thin; give where they come from, who knows them, what they know of the
  setting."
- The sheet stays the mechanical record. The background is the fiction: origin, reputation, ties. The tool description
  says that anything in Session 0 about a character's past must be written here, because Session 0 is discarded.
- It is part of the campaign record: `templates/party_member.md` prints it under the sheet, and the GM sees it in the
  campaign record entry like the rest of the party.
- Old saves have no `background`. Nothing reads it as mandatory outside `begin_adventure`.

## 5. The familiarity pass

### 5.1 Where it runs

In `run_bootstrap`, after the seed call has recorded the setting, the opening place and the GM's hidden notes, and
before the expansion of the frontier. A separate call, not a longer seed prompt: the seed call is about transcribing the
record faithfully, and this one is about inventing specific, consistent local knowledge, which is a different job. It
also lets the pass see the seeded world (the names already used, the parents to attach to).

Because the entities it creates are `discovered` (they have `known` facts), the existing frontier rules make the
expander flesh them out next, after the opening place. The expander writes only `hidden` facts, so what a character
knows stays a surface, and the depth is still there to find.

### 5.2 Input

A `FamiliarityRequest`: the setting, the opening situation, the level, each character's name, sheet and background, the
world so far (entities and their facts, with disclosure, so it can avoid contradictions), and the private GM notes so
that it can avoid contradicting or leaking them.

### 5.3 What it writes

For every character, the places, people, groups and ideas that their background makes familiar, as the same entity and
fact proposals the seed call produces, with one addition: each fact lists `via`, the names of the party members whose
knowledge it is.

How much, by how well the character knows the area (the pass chooses; the server only caps the totals):

| Familiarity | Example | Records |
|---|---|---|
| Native, insider | the "Ghost of the Docks" on the docks | 4 to 6 places and people in the area, with 1 to 3 facts each; a handful of regulars by name |
| Educated, connected | a cleric raised in the royal chapel, castle | 3 to 5 places and people; how the court is organised; who matters |
| Passing | has visited the city twice | 1 or 2 landmarks and one well-known figure |
| Stranger | arrived this week | nothing, or only the one thing they came for |

What the facts are:

- **Common knowledge a local would have**: where things are and what they are for, who runs them, who is feared or
  trusted, how the place behaves (the tides, the watch's habits, which gate asks for a pass).
- **People, as the character knows them**: a name, a role, how they look and act, the character's relationship to
  them (aspects `role`, `appearance`, `manner`, `relationships`). A fence, a harbourmaster's clerk, a gate captain, a
  dock gang's foreman.
- **Hearsay is allowed, truth is not required.** A character may know a *rumor* that is false (WORLD.md 2.3 models
  this as a `known` fact about what people say). That is the safe way to include something near a GM secret.

Rules:

- **Known only.** Every fact from this pass is `known`; none is `hidden`. Facts that are secrets belong to the seed
  call (GM notes) and to the expander.
- **No leaks from the GM notes.** A character knows a secret from the notes only if their background plainly gives
  them that knowledge. Otherwise, hearsay at most. When the notes say the harbour official is corrupt, the dock rogue
  may know "people say Vane's men are paid to look away", not the crate's contents.
- **The independence rules still hold for fact text.** One claim, at most 40 words, self-contained, names not
  pronouns, no "you", no "the party", and **no party member's name in the text**. The attribution is `via`, so the
  fact "The Silt-Walkers control the dock labor on the southern quay" stays true if the character is cut from the
  party. Dates and causes lie before the game. The regex check of `independence_problem` is applied; a failing fact is
  dropped with a note, as in expansion.
- **Do not duplicate the world.** New names must not clash with existing entities. When a place or person already
  exists (from the seed call), the pass adds facts to it and does not create it again.
- **Everything attaches.** Each new place has a `parent` that exists, so the compendium tree and the world graph are
  connected. Each new person is tied to a place or group by a fact.
- **Cover the party.** After the pass, the server checks that each character with a background that names something
  local got at least one fact. A missing character gets a second call that is asked for just that character (the same
  feedback-and-retry mechanism the expander uses). If it still produces nothing, the game starts anyway.

### 5.4 Totals and failure

- Caps in `PassConfig` for this pass: 16 new entities and 32 facts for the whole party (`familiar_entities`,
  `familiar_facts`). The prompt carries the per-character sizes.
- The step reports progress ("Recalling what the characters know..."), as other bootstrap steps do.
- **A failed familiarity pass does not fail the bootstrap.** The seed already holds a valid world, and a missing
  flavor step should not stop the game from starting (unlike a failed seed, WORLD.md 4.6). The failure is logged, the
  game starts with what the seed made, and the compendium is thinner. Decision 3 in section 12 covers the other choice.

### 5.5 Seeding the story plan

Story games (STORY.md) are planned after the world is built. The plotter already receives "the world so far". Its
prompt gains one line: prefer to use the known local entities for the opening area's foreshadowing and the first
quests, so the characters' knowledge matters. That is the only change to the plotter.

## 6. Where the knowledge shows up

### 6.1 The world model

`Fact` gains an optional `via: tuple[str, ...]`: the names of party members whose starting knowledge it is. It is
empty for everything else. Properties:

- Set only by the familiarity pass (`AddFact.via`). `establish` and extraction never set it, so mid-game discoveries
  keep their current form.
- A replacement fact (a supersede) does not inherit `via`; the attribution belongs to the original starting knowledge.
- These facts have `source: background` (a new source, next to `seed`). Unlike seed facts they get a `learned_seq`, so
  the compendium shows them as **new** until the player has looked: the knowledge is old to the characters but it is
  news to the player, who has not yet seen it written down (COMPENDIUM.md 4.1).
- Saved as part of the fact. This is a format bump (version 7). Older saves load with no `via`. A save written by this
  version is not readable by an older server, as with the earlier bumps.

### 6.2 The briefing

The briefing label for `known` facts gains the character, so the GM can use it in play:

```
[known] The Silt-Walkers control dock labor on the southern quay. (Toby knows this)
```

The GM prompt (`04_world.md`) says how to use it: a character with first-hand knowledge acts like it. They greet the
regular by name, avoid the watch's blind corner, do not ask where the High Quay is. The GM may let such a character
supply the detail in narration, and must not have a character know *more* than the record says.

### 6.3 The compendium

- **List**: unchanged. Names, hierarchy, tags. The starting knowledge is `new`, so the first open shows `✦` on it and
  the status line starts with a count.
- **Detail**: each fact in the API gains `via` (a list of names, usually empty). The client shows it as a dim suffix
  after the fact ("· Toby"), and nothing for facts with no `via`.
- **Filter**: the `q` search stays name-based. A filter on `via` is not added.
- **No leak surface changes.** `via` holds only party member names, which the player chose. The leak sweep test
  (COMPENDIUM.md 7) gains a check that it never names a hidden entity or a character that is not in the party.

## 7. The opening overview

The first reply of the adventure has two parts: an overview, and then the scene.

### 7.1 Content

A short, vivid picture of the setting as the characters would see it (the "establishing shot"), in the GM's narrator
voice, second person present like the rest of the game:

- 80 to 150 words, one or two short paragraphs. About the region and the city or site: what kind of place it is, what
  is going on in the background of daily life, the mood. The tone and scale agreed in Session 0.
- It draws on the `known` facts and the setting text only, never on `[GM only]` notes, so it spoils nothing and agrees
  with the compendium. A natural touch is to colour it with the characters' familiarity ("To Toby the docks are home
  ground, a maze he has walked since childhood").
- It sets up the scene without delivering the hook. The hook belongs to the scene.
- It then moves on, with a clear break, to the opening scene as today.

### 7.2 Where it lives

Prompt only; no new data and no new event. Changes:

- `templates/begin_cue.md` asks for the overview first, then the scene.
- `system/adventure/01_role.md` replaces "open straight away with the first scene" with the two-part opening and the
  limits above.
- `system/adventure/03_style.md` notes the exception: the first reply may run to four short paragraphs; every later
  reply keeps the one-to-three rule.

A prompt-only overview is the cheapest approach. It is also the weakest (a small local model may skip it or run long),
so the tests check the begin cue and the prompt text, and the live check (section 11) checks the behavior. Section 12
(decision 4) covers the alternative of having the curator write the overview during bootstrap.

### 7.3 Extraction

The overview is narrated like any other turn and the normal pass reads it. Nothing in it is a new fact: it restates
`known` ones. If the GM does mention a hidden fact, the usual `reveal` rules apply, and the compendium would show it as
new, which is a signal that the GM broke the rule rather than something to prevent here.

## 8. Code touched

| Area | Change |
|---|---|
| `tools/begin_adventure.py` | `background` per member; minimum length; error text |
| `prompts/tools/begin_adventure.md` | say that the background must be written out |
| `prompts/system/session_zero/02_party.md` | the background step and the tie rules (section 4.1) |
| `prompts/templates/party_member.md`, `campaign_record.md` | print the background |
| `prompts/templates/begin_cue.md`, `system/adventure/01_role.md`, `03_style.md` | the two-part opening |
| `prompts/system/adventure/04_world.md` | how to use `(X knows this)` |
| `prompts/world/familiarity.md` (new) | the familiarity prompt |
| `prompts/world/bootstrap.md` | narrow "Character ties" to what the background names; the new pass does the rest |
| `prompts/world/plot.md` | prefer the known local entities |
| `world/curator.py` | `FamiliarityRequest`; `Curator.familiarity`; `FactProposal.via` |
| `world/anthropic_curator.py`, `ollama_curator.py` | `familiarity()`, `FAMILIARITY_SCHEMA` (the Ollama curator reuses `_ask`) |
| `world/render.py` | `render_familiarity` |
| `world/passes.py` | `run_familiarity` called from `run_bootstrap`; caps; coverage retry; independence checks |
| `world/ops.py`, `world/model.py` | `AddFact.via`; `Fact.via`; save format 7 |
| `world/briefing.py` | the attribution in the label |
| `world/scripted.py` | a scripted `familiarity()` for tests and `--test` |
| `compendium.py`, `routes/compendium.py`, `docs/API.md` | `via` in the fact |
| `client/.../compendium_model.py` | draw the `via` suffix |
| `docs/WORLD.md`, `COMPENDIUM.md`, `API.md`, `CLIENT.md`, `BACKEND.md` | updated to match |

## 9. Existing games

The docks game and other saves were created before backgrounds existed. Their worlds are already built and the first
scene was played, so the bootstrap does not run again. Options:

The bootstrap does not run again for them, but nothing breaks: `via` is optional and backgrounds are optional outside
`begin_adventure`. To give such a game the same starting knowledge there is a one-off **backfill**, a debug endpoint
(it exists only when the server runs with `--debug`):

```
curl -X POST localhost:8000/debug/backfill -H 'content-type: application/json' \
  -d '{"backgrounds": {"Toby": "Known as the Ghost of the Docks; grew up on the Sunken Anchor pier."}}'
```

- It runs the familiarity pass against the loaded session's existing world and applies the result. The body is
  optional; `backgrounds` maps character names to a background, which is also stored in the campaign record. A
  character without one is judged from the sheet.
- The facts are `known`, `source: background`, with `via`, so they show as new in the compendium.
- Running it twice adds nothing the second time (duplicate facts are skipped). It refuses (409) when there is no
  adventure, the curator is off, or a turn is running; the response lists the facts added and anything dropped.
- The GM's campaign record in the history is not rewritten: the GM learns of the new knowledge through the
  briefing labels.

## 10. Risks

- **Spoilers through the back door.** A character who "knows" the area could be handed a GM secret. Mitigations: the
  known-only rule, the notes-leak rule in the prompt, and a test using a scripted curator that tries to emit a fact
  copied from the notes. Without a model, the check is by text overlap with hidden facts, and it is a heuristic: the
  prompt carries most of the weight.
- **Padding.** A thin background invites generic output. The pass is told to write nothing rather than pad (as the
  expander does), and the tier table sets sensible sizes.
- **Over-familiar characters.** A rogue who knows every named person in the city removes discovery. The caps and the
  "surface only" rule keep it to the first layer, and the expander still holds the deeper facts hidden.
- **Small local models.** The familiarity prompt is longer than the seed prompt and asks for invention. On Gemma-class
  models it may be thin or ignore `via`. The server therefore treats `via` as optional on read (a fact without it is
  still recorded, as party-wide knowledge) and does not fail the game on a weak result.
- **Redundant narration.** The overview may repeat what the player heard in Session 0. That is acceptable: it is the
  game's own restatement, shorter than the Session 0 summary, and it helps when a save is reopened later.
- **Cost and wait.** One more curator call, in the wait the player already has. A coverage retry adds at most one
  more.

## 11. Testing

Server, with the scripted curator unless noted:

- `begin_adventure`: `background` required and length-checked; the record template prints it; a game without a
  background (an old save) still loads and plays.
- Familiarity pass: facts arrive `known`, `source: seed`, `learned_seq` 0, with `via`; names are validated against the
  party; party names in the text are rejected; new entities are attached to a parent; duplicates of existing
  entities merge; caps hold; a character with no facts triggers the retry; a thrown error leaves the seeded world
  intact and the bootstrap succeeds.
- Persistence: format 7 round trip; a v6 save loads with empty `via`.
- Briefing: the `(X knows this)` label for known facts with `via`, and none for others.
- Compendium: seed facts with `via` appear on a fresh game, are not new, show `via` in the detail; the leak sweep
  still passes, and `via` never contains a non-party name.
- Prompts: the begin cue and role prompt mention the overview and its limits (so a change to them is deliberate).

Client: the detail view draws the `via` suffix and tolerates its absence (an older server).

Live (not automated): start a docks-like game with the Anthropic provider and with Gemma through Ollama, and check by
reading: the Ghost of the Docks has named docks places and people in the compendium before turn 1, another character
has castle and nobility entries, the overview appears once and is short, no GM note is in the compendium.

## 12. Decisions to confirm

1. **A separate familiarity pass** (recommended) rather than extending the seed prompt. It costs one more call during
   the wait and gives much better control of the output.
2. **`via` attribution** (recommended) in the model, briefing and compendium. The alternative is to leave facts
   party-wide with no attribution, which needs no format bump, but then "Toby knows the docks" is visible only in
   the first scene and the GM's briefing cannot tell whose knowledge a fact is.
3. **A failed familiarity pass is not fatal** (recommended). The alternative is to fail the bootstrap like the seed
   call, which keeps the quality bar but can block a start on a flavor step.
4. **The overview is written by the GM in the first reply** (recommended). The alternative is for the curator to
   write it during bootstrap and the server to prepend it to the first reply, which is more reliable for local
   models but makes the first message a special case in history and in the API.
5. **Backgrounds are required** in `begin_adventure` for new games (recommended). The alternative is optional, with
   the familiarity pass inferring from the sheet, which is easier on weak models but gives less to work with.
6. **Starting knowledge is "new"** in the compendium until the player has seen it. Decided: it is new to the player
   even though the characters brought it. (Setup facts from `seed`, the setting and the opening, stay not new.)
7. **Existing saves**: add the backfill command (option 2 in section 9). Decided.

## 13. Build order

1. `Fact.via`, `AddFact.via`, format 7, briefing label (the data model; no behavior change without the pass).
2. `begin_adventure` `background` and the Session 0 and template prompts.
3. `FamiliarityRequest`, the curator methods (scripted first), `run_familiarity` and its tests.
4. The familiarity prompt and the wiring in the Anthropic and Ollama curators, plus `plot.md`.
5. Compendium `via` in the API and the client.
6. The two-part opening prompts.
7. Docs, then live checks with both providers, and tuning of the prompts.

## 14. What changed while building

- The source is its own value, `background`, rather than `seed`, so that the facts are new in the compendium (the
  decision in section 12.6). `seed` still means "the setting as told", and is never new.
- Caps are totals for the party, not per character.
- The backfill is `POST /debug/backfill` instead of a command-line subcommand, because it works on a live session.
- The scripted curator reads `[[knows: Subject[:kind] | sentence]]` in a character's background, which is how the
  tests and `--test` mode drive the pass. The scripted test hero knows an NPC, Old Tam.
- A new place whose `parent` is missing is attached to the outermost region of the opening scene.
