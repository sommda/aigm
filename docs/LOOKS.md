# AIGM Character Looks: Design

Status: **spec; build steps 1 to 6 (section 12) are done**.
First step toward graphics ([ART.md](ART.md), [APP.md](APP.md)): give every
character a detailed, stable description of how they look, written when they first come into the game. Later steps feed
those descriptions to an image model, keep a library of the images, and find the closest existing image for a new
description. This document covers only the descriptions and the data around them. It builds on [WORLD.md](WORLD.md)
(entities, facts, the curator), [STATUS.md](STATUS.md) (sheets, which are written by a similar step) and
[OPENING.md](OPENING.md) (Session 0 and the campaign record).

## 1. Goal

1. **Every character has a Look** from the turn they are created: a detailed written description of their appearance,
   plus a few structured tags. "Character" means both **player characters** (the party) and **NPCs** (entities of kind
   `npc`).
2. **A Look exists before any facts do.** A person can be named in passing, with nothing recorded about their role or
   history, and still gets a Look.
3. **The GM stays consistent with it.** What the narration says about someone's appearance never contradicts their Look,
   and what the narration commits to (a scar, a green cloak) ends up in the Look.
4. **The Look is built to be used later**: as the core of an image prompt, and as the key for a similarity search over
   an image library. This spec fixes the data for that, not the pipeline.
5. **It is cheap and never blocks play.** One small curator-model call per few characters, in the background, except
   at the start of the adventure where the player already waits.

### Non-goals (this step)

Generating or storing images; any client display of NPC looks; the similarity search itself (only the data it needs, in
section 6); places, items, creatures and combat foes (the record is written so they can follow, section 11); a way for
the player to edit a Look; disguises and shapeshifters beyond a note in section 11.

## 2. Terms

- **Look**: the record in section 3, attached to one character.
- **Creation**: the moment a character first exists in the game's data: an NPC entity is added to the world (by the
  GM's `establish`, by the world bootstrap, by the curator's extraction or expansion), or a party member is recorded by
  `begin_adventure`. This is "first mentioned" in the sense of the request: the person is named before anything is known
  about them. Whether the player has met them is a separate matter (`Entity.discovered`).
- **Describer**: the new curator step that writes Looks (section 5), a sibling of the sheet writer.

## 3. The Look record

```jsonc
{
  "summary": "A stooped old woman with a milky left eye and a shawl the color of wet slate.",
  "description": "Marta Venn is a woman of about seventy, short and stooped, with ...",
  "tags": {
    "ancestry": "human", "age": "elderly", "gender": "feminine", "build": "slight", "height": "short",
    "skin": "pale, weathered", "hair": "white, thin, tied back", "eyes": "left eye clouded, right grey",
    "marks": ["clouded left eye", "tremor in the right hand"], "clothing": "slate-grey wool shawl, patched brown dress",
    "carries": ["walking stick", "ring of keys"], "archetype": "innkeeper", "expression": "wary"
  },
  "rev": 1,                // bumped whenever the text changes
  "state": "provisional",  // provisional | fixed (section 7)
  "source": "generated"    // generated | session_zero | narration (section 4)
}
```

| Field | Meaning and rules |
|---|---|
| `summary` | One sentence, at most 25 words. What a stranger notices first. Shown to the GM and used in captions. |
| `description` | 80 to 160 words of plain prose for an image model. See the writing rules below. |
| `tags.ancestry`, `age`, `gender`, `build` | **Controlled values** (section 3.2). The server rejects others. |
| other `tags` | Short free text, at most 12 words each; `marks` and `carries` are lists of at most 5 short items. |
| `rev`, `state`, `source` | Bookkeeping. The image step will record which `rev` a picture was made from. |

### 3.1 Writing rules for `description`

The description is the main input to an image prompt, so it is written for a painter, not a reader:

- **Only what an observer in the fiction could see**, standing in front of the person in good light: face, hair, body,
  age, clothing, gear in view, posture, bearing. No backstory, no names of other people, no secrets, no role that
  cannot be seen. A fact the player must not know (a hidden brand, a disguise) is not part of the Look.
- **Concrete nouns and colors**, not judgments: "a notched left ear and a pale scar from brow to jaw", not "a dangerous
  man". Moods only as a visible expression ("wary, lips pressed thin").
- **Specific enough to be distinct**: at least one memorable feature (a mark, a color, an accessory) for every
  character, so two guards do not get the same face.
- **Fits the setting**: clothes and materials of the region and technology level in the campaign record.
- **No product names or trademarked creatures or settings** ([LAUNCH_RULESETS.md](LAUNCH_RULESETS.md) 5.3); generic
  words for fantastic ancestries ("a stocky, bearded mountain-folk smith") when the ruleset's own name is a
  product term.
- **Third person, present tense, no pronoun confusion**; the character's name appears once at the start.
- No "you", "the party", or game terms (level, class, HP). Skin and ancestry are described plainly and without
  stereotypes; the describer prompt carries the content rules of the style bible ([ART.md](ART.md) 7), including that a
  character who is a minor is never described in a sexualised way.

### 3.2 Controlled tags

These are the tags a similarity search will filter on, so their values come from short fixed lists in code (the lists
are a starting point to settle during the build):

| Tag | Values |
|---|---|
| `ancestry` | human, elf, dwarf, halfling, gnome, half-elf, half-orc, orc, tiefling, dragonborn, goblinoid, beastfolk, construct, undead, other |
| `age` | child, youth, adult, middle-aged, elderly, ageless |
| `gender` | feminine, masculine, androgynous |
| `build` | slight, lean, average, sturdy, heavy, towering |
| `height` | short, average, tall |

`ancestry` is a visual category, not a ruleset term: the describer maps the ruleset's own species (and any setting
specific folk) to the nearest value and says what is distinctive in the free text. `gender` is the **presentation** the
picture should show, which can differ from what the sheet says. `other` is allowed so that an odd character does not
fail validation, and a count of `other` is logged so that the lists can be improved.

## 4. Where Looks come from

There are three sources, which are recorded in `Look.source`.

### 4.1 `session_zero`: what the player decided

In Session 0 the player makes the party and agrees the key people of the setting, so appearance can be asked about and
should be written down by the GM. `begin_adventure` gains two inputs ([OPENING.md](OPENING.md) 3):

- Each **party member** gets a required `appearance` string (at least 60 characters): age, build, coloring, hair,
  notable features, usual clothing, and anything the player asked for. The GM proposes one when the player says "you
  decide", as it already does for backgrounds.
- A new optional list **`characters`**: the **key NPCs** created in Session 0 (a patron, a rival, a companion, the
  villain the GM has in mind). Each has `name`, `role` (one sentence), `appearance` (optional), and `known` (true if
  the player has already been told about them in Session 0). It is a short list, at most 8 entries. Everything counts
  toward the existing size limit of the record. Without it, bootstrap would have to find these people in free text and
  could miss a name the player cares about.

These are the player's words and are never rewritten for style: the describer expands and normalizes them (adds the
tags, fills in what was left open) but keeps every stated detail, and the Look is created `fixed` (section 7) for party
members and `provisional` for NPCs. A key NPC whose `known` is false is entered with its facts `hidden`, as the GM's
private notes already are.

### 4.2 `generated`: invented by the server's pipeline

Any NPC that the pipeline adds without narration of it: the bootstrap's cast, the expansion pass's people ("generated
ahead"), a person recorded by the curator's extraction from earlier narration. These Looks are written from the
character's role and facts (all that exist so far), the setting and the cast already described.

### 4.3 `narration`: the story got there first

If the GM improvises a person in the middle of a scene, the narration may already have described them ("a tall man
with a braided silver beard"). The describer is given the turn's narration and treats every appearance detail in it as a
**fixed constraint**: the Look includes them, never changes them, and fills in the rest around them. The GM may also
pass `look_notes` in `establish` (section 4.4) so the notes are in hand before the narration is written.

### 4.4 The creation signal: no new tool

The request raised a tool that says a character has been "created". The server already has the signals it needs, so this
spec **does not add a tool**:

| Case | The signal | Look written |
|---|---|---|
| A party member | `begin_adventure`'s `party` | at bootstrap, while the player waits |
| A key NPC from Session 0 | `begin_adventure`'s `characters` | at bootstrap |
| An NPC the GM invents in play | `establish` with an entity of kind `npc` | right after the turn |
| An NPC the pipeline adds | any curator pass adding an `npc` entity | right after that pass |

A second tool such as `create_character` would overlap `establish`, which already accepts an entity with no facts
("entities are cheap stubs", [WORLD.md](WORLD.md) 2.2), and would give the GM one more call to forget. Only two changes
touch the GM:

- `establish` entities accept an optional **`look_notes`** (a line, up to 40 words, only for `npc`): the visible traits
  the GM is about to narrate. It is passed to the describer as constraints and is not stored.
- The prompt for `establish` and the world section say: record every named person the first time they appear, **before
  narrating them**, and when you describe how someone looks, stay within the Look shown in your notes.

The cost of forgetting is small. A named person the GM never records is found by the curator's next extraction pass (the
first comes after one page of narration), which creates the entity, and the sweep below then writes the Look. In the
meantime the narration of that person is still covered by section 4.3.

## 5. The describer

### 5.1 When it runs: a sweep

The need is a pure function of the game state, like the narration pages that decide curator passes:

> **characters needing a Look** = every party member and every `npc` entity that has no Look.

So no extra saved state is needed, a restored save heals itself, and every path that creates a character is covered by
one check. The sweep runs:

1. **At bootstrap**, for the party and the Session 0 key NPCs plus everything bootstrap created, inside the "preparing
   the world" wait the player already sees (a new status stage, "Picturing the characters..."). The first scene is
   written only after this, so the GM has the Looks in its first briefing.
2. **After a turn commits**, if that turn added an NPC entity (in the background, like a curator pass; it never blocks
   the next turn and does not use the curator lock for the world passes).
3. **After a curator pass applies**, if it added NPC entities.
4. **After a load** of a save that has characters without Looks (older saves), on the first following turn rather than
   on the load itself, so that viewing a save costs nothing.

Limits: at most **6 characters per call** and at most **12 per sweep**, in this order: in the current scene; named in
the narration of the last turn; connected to the party's backgrounds; discovered by the player; all others. The rest
wait for the next sweep. A failed call is logged and retried by the next sweep, so a failure never fails a turn.

### 5.2 Input to the describer

One request per batch of up to six characters, so the cast is varied within a call:

- For each: name and aliases, kind, role, **all recorded facts** about them that bear on appearance (aspect
  `appearance`, `role`, `manner`, `location`) of **any** disclosure, and for a party member the sheet and background;
  plus their `appearance` text from Session 0 or their `look_notes`, and the sentences of narration that describe them
  (section 4.3). Hidden facts are given only to prevent contradictions; the describer is told never to put them in the
  Look (3.1).
- The campaign setting, region and the ruleset's name for its species (for the ancestry mapping).
- The summaries of the Looks already in this game, so the new ones differ from them.
- The style and content rules, and the product-name deny-list.

### 5.3 Output and checks

Structured output (the same mechanism as the sheet writer, `Curator.look`), one entry per character: `summary`,
`description` and `tags`. The server checks:

- word counts and the controlled tags (3.2); the name appears in `description`;
- no second-person words, no mention of other characters by name, no game terms or product names;
- no lazy duplicates: a Look whose tags and summary match another character in the game's cast too closely is
  rejected with the other character named, and asked for again once;
- every `narration` constraint is still present (a check on the tags and a keyword check on `marks`, `hair` and
  `clothing`, because the narration will be contradicted if the Look is not).

One retry per failing entry with the problems quoted. An entry that still fails is skipped and logged. The character has
no Look until the next sweep and nothing in the game depends on it.

### 5.4 Cost

A call of six characters is about 1,500 tokens in and 1,000 out on the curator model (Haiku class). A new game with a
party of four and five key people is two calls. In play, new named people arrive roughly every few turns, so the extra
cost is small next to the narration ([TURN_COST.md](TURN_COST.md)). Looks add roughly 25 to 40 tokens per present
character to each briefing (the summary only).

## 6. Built for similarity search

The art plan is to reuse an image when a new character is close enough to one already made ([ART.md](ART.md) 3). This
step stores what that needs and builds none of it.

1. **A canonical search text** is derived from the Look, never stored: a fixed-order string such as
   `human | elderly | feminine | slight | short | hair: white, thin, tied back | eyes: ... | marks: ... | archetype:
   innkeeper | <summary>`. Its format has a version number, so a change of format can be re-embedded in bulk.
2. **Two-stage match** (later): filter by the controlled tags (`ancestry`, `age`, `gender`), then rank the survivors by
   embedding distance on the search text, with `build`, `hair`, `marks` and `clothing` boosting or penalizing. The
   controlled tags exist so the filter is exact and cheap.
3. **A distance threshold** decides between reusing the nearest image and generating a new one, with the rule that two
   characters in one game never share an image.
4. **Provenance**: a future `Look.image` will name an asset and the `rev` and prompt-format version it was made from. If
   the Look's `rev` moves on (section 7), the image is stale and the match runs again.
5. **Tags are written for matching, not display**: short, consistent vocabulary ("white", not "snowy"), and the
   describer prompt carries a short glossary for hair, skin and clothing colors.

## 7. Staying true: revisions

| `state` | Meaning | May change |
|---|---|---|
| `provisional` | No image exists and the player has not been told much | yes, to fold in narrated details, once per sweep |
| `fixed` | A picture has been made, or the player chose it in Session 0 | only by an explicit **change of look** |

- A party member's Look is `fixed` from the start: the player chose it.
- An NPC's Look turns `fixed` when an image is made from it (a later step). Until then, if the narration states a
  visible detail that the Look lacks or contradicts, the next sweep **revises** it: the narration wins, because the
  player was told (the same rule as for facts, [WORLD.md](WORLD.md) 4.3), `rev` goes up, and the change is logged.
- Lasting changes in the story (a scar from a fight, a haircut, aging between chapters, a lost hand) are recorded by
  the same step when the extraction sees them stated, and produce a new `rev` even when `fixed`. A temporary condition
  (muddy, bleeding) is not a change of look.
- The GM sees the current Look in its briefing and is told to treat it as true. If the narration contradicts a fixed
  Look, the GM gets a correction note on the next turn, as it does for contradicted known facts.

## 8. Storage and format

- **NPCs**: `Entity.look`, in the world, so it is saved with the world, rolls back with a failed turn, and is
  reset by `/chat/new` ([WORLD.md](WORLD.md) 2.5). The world dump shows it under the entity.
- **Party members**: `GameState.looks`, a map from character name to Look, next to `sheets`. They are not entities
  ([WORLD.md](WORLD.md) 4.2), and a party member's name is the key everywhere else.
- Both share one `Look` dataclass in a new module, `looks.py`, with `to_dict`, `from_dict`, `copy` and the validation of
  section 5.3, so a client or a test sees one shape. Saves bump their format version; an older save loads with no
  Looks and the sweep fills them in (section 5.1). A malformed Look in a save is a corrupt save, like a malformed sheet.
- Order of precedence when text conflicts: narration beats `look_notes` beats Session 0 text beats generated text.

## 9. What the GM and the player see

**The GM** gets, in the world briefing ([WORLD.md](WORLD.md) 6), a line per person who is **present in the scene** or
**in the near frontier**: `Marta Venn (innkeeper): <summary>` and the `marks`. The full description is not sent each
turn; `recall` on a person includes the whole Look. The party's Looks sit with the sheets. The prompt rule is: stay
within it; add details freely when they do not conflict, and expect them to be added to the Look.

**The player** sees a Look in two places, under the rule that **a Look is shown only once the character is
`discovered`**. For an NPC, `discovered` is set when the player is told a fact about them or when they are placed in
the scene (the player can see who is there). The NPC's compendium page then shows the Look as "Appearance", and a
person who has been met but has no known facts yet still has an entry, which holds only the Look (its summary is the
list line, and it is never "new"). A hidden person who has not been met has no entry, whatever their Look says.

**Party members**: the status page's character endpoint adds `look` (summary, description) for the player's own
characters, since the player wrote them. Both clients show it as "Appearance" on the character's
tab. **Debug**: `GET /debug/hidden` and the world dump include every Look.

## 10. Changes to prompts and tools

| Where | Change |
|---|---|
| `prompts/system/session_zero/02_party.md` | Ask for each character's appearance; propose one on "you decide". Name the key people of the setting (patron, rival, companion, villain) and describe them too |
| `prompts/tools/begin_adventure.md`, `tools/begin_adventure.py` | `appearance` per party member; optional `characters` list; size and validation rules |
| `prompts/tools/establish.md`, `tools/world.py` | optional `look_notes` on `npc` entities; "record a named person before narrating them" |
| `prompts/system/adventure/04_world.md` | Stay within the Looks in your notes; the Look is visible traits only |
| `prompts/world/describe.md` (new) | The describer prompt: 3.1 rules, tag glossary, deny-list, output schema |
| `prompts/world/bootstrap.md` | Key NPCs are recorded as `npc` entities with the `known` flag respected |
| `world/curator.py`, `world/anthropic_curator.py`, `world/scripted.py` | `LookRequest`/`Look` types; `Curator.look`; a scripted implementation for test mode |
| `world/passes.py`, `world/service.py` | `run_looks` (the sweep), called at bootstrap and after turns and passes |
| `world/briefing.py`, `tools/world.py` | The briefing line; `recall` shows the Look |
| `characters.py`, `routes/` | `look` on a party member's page; world dump and hidden view |

## 11. Beyond this step

- **Other things with a picture**: places, items, creatures and combat foes will want the same record. `Look` is
  deliberately not specific to people: only the controlled tags and the prompt change by kind. Foes named in
  `set_combat` ([STATUS.md](STATUS.md)) are not entities today, so they are out of this step.
- **Groups** (a faction, a squad of guards) can get a Look for their uniform and badge later.
- **Disguise and true form**: a Look is what an observer sees. A shapeshifter or an impostor would carry a second,
  hidden `true_look`, revealed with a scene. Leave the field out until a story needs it.
- **Editing by the player**: a UI to rewrite a party member's `appearance`, which makes a new `rev`.
- **Expressions and poses**: `expression` in the tags is a default; variants are an image-step concern.
- **Pack campaigns**: a campaign pack ([CAMPAIGNS.md](CAMPAIGNS.md)) would supply Looks for its cast, written by its
  designer in this same format, with `source: pack`.

## 12. Build steps

Each step leaves the tests green and is useful alone.

1. **The record.** `looks.py` with the dataclass, validation, controlled tags, the search-text derivation and tests;
   `Entity.look` and `GameState.looks` with save, load and copy; world dump; format version bump; old saves load.
   **Built:** `looks.py` (the dataclass, `problems`/`validate`, `read_looks`, `search_text`),
   `Entity.look` with `World.set_look`, `GameState.looks` with
   `set_look`, save format 10, and the look in the world dump (not in its known-only view).
2. **The describer.** `LookRequest` and `Curator.look`, the Anthropic and scripted implementations, `describe.md`,
   `run_looks` with batching, ordering, validation and retry; unit tests with the scripted curator.
   **Built:** `LookSubject`/`LookRequest` and the optional `Curator.look`; `AnthropicCurator.look` with
   `LOOK_SCHEMA` and `parse_looks`; the scripted curator's deterministic Looks; `prompts/world/describe.md`; the
   `SetLook` op (a person who has a Look keeps it); and `world/describe.py` with `needing` (the order of 5.1),
   `run_looks` (batches of 6, at most 12 per sweep, the content rules, no near-duplicates of the game's cast, decided
   details kept, one retry, never raises) and `LooksResult`. Nothing calls `run_looks` yet; that is step 3.
3. **Wire in the sweep.** At bootstrap with its status stage; after turns and passes, with the ordering of 5.1.
   Briefing line and `recall`. Tests for the "no Look yet" case, for a failed call, and for rollback of a failed turn.
   **Built:** the bootstrap describes the party and the cast while the player waits (status "Picturing the
   characters...", up to 24 characters, a failure only logged). After each turn `CuratorService.run_looks_if_due`
   writes the missing Looks in the background (`Session.pending_looks` for party members, `SetLook` ops for people),
   and backs off for 2 turns when a sweep writes nothing. The briefing has a `Looks:` line under each person present
   and a "How the party looks" block; `recall` gives the whole description; the prompt rule is in `04_world.md`.
4. **Session 0 and `establish`.** `appearance` and `characters` in `begin_adventure` (with checks and bootstrap
   handling), `look_notes` in `establish`, prompt edits, the party page's `look` field.
   **Built:** `begin_adventure` requires an `appearance` (60+ characters) per party member and takes an optional
   `characters` list (at most 8; each has `name`, a one-sentence `role` that uses the name, `known`, and an optional
   `appearance`). Both are kept in the campaign record, and the GM sees them in it. Bootstrap records the key people as
   `npc` entities with their role as a `seed` fact (`known` or `hidden`) before the curator runs, and tells the
   curator who is already recorded. The describer is given the player's appearance for the party (a `fixed` Look) and
   for key people (a `provisional` one). `establish` takes `look_notes` on people (at most 40 words): they are kept in
   `GameState.look_hints` (not saved) until the next sweep, which treats them as decided details and then forgets
   them. A party member's page (`GET /characters/{name}`) has `look`. The prompts for Session 0, `begin_adventure`
   and `establish` are updated.
5. **Narration revisions.** Constraints from narration, the `provisional` rule, contradiction handling and the
   GM correction note.
   **Built:** the describer is given the sentences of the last turn's narration that name a new person, and the two
   after each (description often says "she" or "his"), and told to keep any visible detail in them; such a Look has
   `source: narration`. After each turn, `CuratorService.run_revisions_if_due` checks the narration against the
   Looks of the people it names. A cheap word gate (hair, eyes, scar, cloak...) decides whether a sentence looks like
   description, so most turns cost nothing; otherwise one call (`Curator.revise_looks`, prompt `revise.md`) returns a
   verdict per character: `same`, `adds`, `lasting` or `contradicts`. The server applies section 7: a provisional Look
   takes `adds`, `lasting` and `contradicts` (the story wins, `rev` goes up, the change is logged); a fixed Look takes
   only `lasting`, ignores `adds`, and a `contradicts` becomes a correction note in the GM's next briefing. Revised
   people go through the `ReviseLook` op, revised party members through `Session.pending_revised`; both are skipped
   if the Look changed meanwhile. The check runs once per turn and is not retried on failure.
6. **Live pass.** Play a new game and read the Looks: are they distinct, consistent with the narration, and free of
   hidden facts and product terms? Tune the prompt. Then update [ART.md](ART.md) and this document to what was built.
   **Done** on the Aurendell save `aurendell-20261026-1242-1` (a version 9 save with one party member and 41 people, so
   it also exercised the old-save path), with `claude-haiku-5-5` at low effort. Results:
   - **Quality.** All 42 characters got a Look. Descriptions averaged 134 words (114 to 153), were visual and
     specific (a pewter fish brooch, a notched ear, a lamp-keeper's iron hook), fit the setting, and were free of "you",
     game terms and product names. A scan for secrets found only hidden *appearance* facts being used, which is
     intended, and no plot secret in any Look. Variety was good in age, build and dress (13 elderly, 14 middle-aged,
     5 youths and a child) but the cast was 38 human of 42 in a mostly human setting, and pale blue and dark brown eyes
     recur; watch this on a setting that should be more mixed.
   - **First run problems, fixed.** The validator rejected a Look that dropped a title ("Aggie Fenn" for "Saltwife
     Aggie Fenn"), so a name now counts without its first word when it has three or more. The model sometimes wrote
     161 to 166 words, put a list of garments in a tag (over 12 words), or wrote "whatever you are carrying"; the
     prompt now asks for 90 to 140 words, short tags and no "you" even as a figure of speech, and the retry catches
     the rest. In the first run 2 of 42 still failed after the retry (a long tag, and the title and "you" case); in
     the second run none did.
   - **Speed.** Six characters per call took 35 to 40 seconds, and the first run took 3 minutes 50 seconds for 42
     characters. Batches now run concurrently (up to 4), with a second round for Looks that came out too like one from
     another batch: the second run took 1 minute 50 seconds for all 42, about 25 to 30 seconds per sweep of 12. A new
     game's bootstrap (up to 24 characters) therefore waits about 30 seconds.
   - **Revision check.** On the save's 62 real turns, the 44 verdicts it asked for were all `same` (no false
     revisions). The gate first let 41 of 62 turns through, because colors and words like "face" and "short" are in
     most paragraphs; it now uses specific words only and lets 26 of 62 through (one cheap call each, mostly for
     Tobin, Kit and Oswin Pell, who recur). Six synthetic probes: green eyes and a beard for a hazel, clean-shaven
     lord, black hair for a white-haired lamp-keeper, and a tall build for a slight hero were all `contradicts`; a
     fresh scar was `lasting`; a soaked, muddy marshal was `same`. One real bug was found and fixed: a sentence about
     "Lord Corvin Vance" was also attributed to "Lord Steward Hadrian Morlowe" because both begin with "Lord". Titles
     and the first word of a name of three or more no longer identify a person, and the prompt tells the model to
     answer `same` when unsure that a sentence is about the character.
   - **Left for later.** The Looks are not yet drawn, so whether the descriptions make good pictures is a question
     for the image step. The ancestry tag is human-heavy by default; if a setting should be diverse, the setting text
     has to say so.

## 13. Tests

- **Unit**: Look validation (lengths, controlled tags, second person, product terms); the search text is stable and
  fixed-order; `from_dict`/`to_dict` round-trip; old saves; the sweep picks the right characters in the right order and
  respects the limits; a duplicate Look is rejected; a narration constraint that is missing is rejected.
- **World**: a failed turn rolls the Look back; `/chat/new` clears it; a revision bumps `rev` and a `fixed` Look is not
  overwritten by a sweep.
- **Tools**: `begin_adventure` rejects a missing or thin `appearance`, caps `characters`, and records the key NPCs;
  `establish` takes `look_notes` and ignores them for places; a party member's name is still refused as an entity.
- **Disclosure**: the Look text never appears in the compendium or any player-facing event; a hidden fact is never
  copied into a Look (checked on the scripted curator's fixtures and by a live review).
- **API**: the party member's page has `look`; the debug view lists all.
- **Test mode**: the scripted curator writes deterministic Looks so the end-to-end tests of both clients keep working.

## 14. Decisions and open questions

Decided by the product owner:

1. **Full descriptions for every character.** One length (80 to 160 words) for all, minor or not.
2. **The describer runs in the background after the turn.** If the lag between narration and Look becomes a problem,
   revisit it when graphics arrive. Image generation will need to be backgrounded anyway, so the Look is not the
   bottleneck.
3. **No creation tool.** `establish`, `begin_adventure` and the curator's passes are the creation signals (4.4).
   Reconsider only if live play shows the GM naming people without recording them often enough that the extraction
   fallback is too late; the first answer would then be a warning in the next briefing, not a new tool.
4. **The image model is one of OpenAI's image-generation models**, to start. Consequences for this spec:
   - These models take plain-language prompts, so the `description` prose is directly usable as the core of a prompt.
     The structured tags remain for matching and for assembling a prompt in a fixed order, not for the model.
   - The tag lists in 3.2 do not depend on the model's vocabulary, so they can be fixed now and adjusted when the
     library exists.
   - Before the image step, check the provider's current usage policy and commercial terms ([ART.md](ART.md) 7). Some
     descriptions (a minor, a wounded or dead character) may be refused by the provider's moderation. The image step
     must treat a refusal as a normal outcome, with the initials-in-a-frame fallback, and the describer's content rules
     (3.1) should be kept at least as strict as the provider's.

5. **A player sees their own character's Look**, in the party page (section 9), because they wrote it.
6. **The image prompt is assembled in the image pipeline**, not the server, so the server stays free of art concerns.
   The server supplies the Look; the pipeline owns the style bible and the prompt format.

Nothing is open in the spec now. Details to settle while building are noted in the build steps.
