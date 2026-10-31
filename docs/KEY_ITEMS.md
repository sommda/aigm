# AIGM Key Items: Design

Status: **spec; build steps 1 to 6 (section 13) are done; step 7 waits for the playtests**.
Fourth step toward graphics, after the Looks ([LOOKS.md](LOOKS.md)), the portraits ([PORTRAITS.md](PORTRAITS.md)) and
the places ([PLACES.md](PLACES.md)). It adds a new kind of thing to the world, the **key item**: a quest object the
party can obtain, such as a key, a map or a ledger. A key item has a written description, a picture, a place in the
compendium and a record of what became of it. Key items also give the story plan ([STORY.md](STORY.md)) two new kinds
of quest: find the item, and a quest that opens only once the party has an item.

## 1. Goal

The GM can create key items at any time, but the player sees one only once it enters play. An item enters play in one
of two ways: the party **learns of it** (it is sought but not yet found) or **acquires it** (it is in hand). Either
way it has an entry on a new **Key Items** tab of the compendium. An item that is in hand also has a picture and a
description of how it looks. If the party later **uses it up or loses it**, the entry says so and keeps the picture and
everything learned, so the player can still reread a clue.

### Non-goals (this step)

- Ordinary inventory: weapons, armor, coin, rations, potions, trade goods, loot. These stay on the character sheet
  ([STATUS.md](STATUS.md)) and never become key items.
- Mechanics. A key item has no stats; the GM plays what it does. The record says what it is, not what it grants.
- Who in the party carries an item. The party holds it as a whole; a per-character holder is a later addition.
- Items in the status tab, equipping, trading between players or dragging items around. The player does not edit the
  world ([STATUS.md](STATUS.md) 1).
- Descriptions or pictures of items the party has not got. An item the party only knows of has an entry with its facts
  and nothing else, not even a placeholder.
- The terminal client's pictures. It gets the tab and the text, as for people and places.

## 2. Decisions already taken

| Decision | Source |
|---|---|
| Key items are quest-specific objects the party can obtain: keys, maps, evidence, and the like | the product owner |
| Each has a detailed description and an image, as people and places do | the product owner |
| They can be created at any time; the player sees none until it enters play | the product owner |
| A new Key Items tab in the compendium shows them | the product owner |
| An item acquired and later lost or used up stays in the compendium, noted as such | the product owner |
| Standard inventory is not key items; a scenario may still start the party with one (a map given in advance) | the product owner |
| A **known** state: the party knows the item exists but has not acquired it, for find-the-item quests | the product owner |
| A known item is in the compendium but has no description (Look) and no picture | the product owner |
| The story plan can generate find-the-item quests, and quests that need an item before they are offered | the product owner |
| Gaining a key item should usually result in an award | the product owner |
| No holder for now: the party holds the item as a whole | the product owner |
| The picture's shape varies by item: landscape for a map, portrait for a document, square when unclear | the product owner |
| Items are created with `establish` and handed over with a separate `key_item` tool | recommended, accepted |
| Statuses are few (`used`, `lost`), with the reason in a note | recommended, accepted |
| On acquisition only `appearance` and `purpose` facts become known; the rest are revealed in play | recommended, accepted |
| The curator safety net (5.4) waits for the playtests | recommended, accepted |
| Existing games are not retrofitted | recommended, accepted |

## 3. Terms

- **Key item**: a world entity of kind `item`. It is a quest object whose absence or presence changes what the story
  can do. The test the GM is given: *if the party never had this, would some path of the story stop or change?* A
  sword is not a key item; the sword that is the only thing that can open the vault is.
- **Holding**: the record of the party's relationship to the item (section 4.2): `unfound`, `known`, `held`, `used` or
  `lost`, with the history of changes.
- **Known** (of an item): the party has been told the item exists, and perhaps something about it, but does not have
  it. Not to be confused with a fact's disclosure `known`, which means the player was told that fact.
- **Acquired**: the party has the item in hand, as the GM or the narration says. Seeing it in a vault, or being told of
  it, does not count.
- **Item Look**: the written description of how the item appears, the same record as a person's or place's Look
  ([LOOKS.md](LOOKS.md) 3) with tags suited to objects (section 7).

## 4. The model

### 4.1 Entity and kind

`item` joins the entity kinds (`location`, `npc`, `faction`, `concept`) and the kinds that have a Look. Everything an
entity already has applies: aliases, facts with a `disclosure` (so a ledger's forged page is a `hidden` fact until the
players find it out), `discovered`, and the usual `recall` and `establish` handling. Item aspects, the checklist slots
a fact can fill:

| Aspect | Holds |
|---|---|
| `appearance` | how it looks, to someone holding it |
| `purpose` | what it is for, as the party understands it |
| `whereabouts` | where it is, or who has it: the thing a find-the-item quest is about |
| `origin` | where it came from and who made or owned it |
| `contents` | what it says or shows: the entries in a ledger, the route on a map, the lock a key fits |
| `powers` | anything unusual it does |
| `history` | its past |
| `secret` | what the party does not know (always `hidden` until the story reveals it) |

The aspects are advisory for the GM and used for reading order in the compendium. `contents` is why the tab is worth
having: it is the place to reread what a letter or a ledger said.

### 4.2 Holding

`Entity.holding` is empty for every other kind and, for an item, is:

- `status`: `unfound` (the starting state, hidden from the player), `known`, `held`, `used` or `lost`;
- `since`: the turn the current status began;
- `history`: a list of `{turn, status, note}`, one per change, oldest first. `note` is one short sentence ("Heard of
  from the harbor master", "Taken from the steward's desk", "Burned to open the sealed door", "Stolen by the guard").

The changes allowed:

| From | To | Event | Means |
|---|---|---|---|
| `unfound` | `known` | `learned` | the party is told the item exists |
| `unfound` or `known` | `held` | `acquired` | the party has it in hand |
| `held` | `used` | `used` | spent doing its job: a key left in its lock, a letter delivered |
| `held` | `lost` | `lost` | taken from the party: stolen, dropped, given away, confiscated, destroyed |
| `used` or `lost` | `held` | `acquired` | the party has it again (the thief is caught); the history shows both |

Anything else is refused with a message (a `known` item cannot be `used`; a `held` item cannot be `learned`). The notes
carry the detail that the two end states do not.

### 4.3 Visibility

This is the one place where an item differs from every other entity. **An item is visible to the player exactly when
its status is not `unfound`.** Whatever its facts say, an unfound item has no entry.

- A fact about an unfound item may be `known` (the party overheard it) but the item still has no entry, no row, no
  related-entity link, and its id answers `404`, as an undiscovered entity does. The GM turns the item `known` when the
  party should meet it.
- Every view that lists entities obeys the same rule: related entities of another entry, a location's contents, the
  status tab, search.
- Once visible, an item stays visible, whether `known`, `held`, `used` or `lost`.
- The usual fact rule is unchanged: only `known` and `active` facts are shown. Hidden facts and the `secret` aspect
  never leave the server.
- The compendium's single filter, `compendium._visible`, is where this rule lives; nothing else decides.

Names can spoil, as for people ([COMPENDIUM.md](COMPENDIUM.md) 3): the GM is told to name an item as the characters
would ("the steward's ledger", never "the forged ledger").

### 4.4 Custody facts

Every change in holding also writes (and the previous one supersedes) a `known` fact with aspect `custody`, such as
"The party took the steward's ledger from the vault" or "The party has heard that the Sluice Key exists". This costs
nothing and gives the item the machinery of the rest of the world for free: the compendium's new/updated marks,
`recall`, and the digest. The `holding` record is the source of truth for status; the fact is its sentence.

## 5. How items come to exist and change hands

### 5.1 The GM's tools

- **Creating**: `establish` takes a new entity kind, `item`, with the same fields as for a person. A key item must come
  with `look_notes` (up to 30 words of what it looks like), since a picture cannot be made from nothing, and its
  appearance, purpose, whereabouts and contents go in as facts in the usual way, hidden or known as the story stands.
  At most **two** key items can be created in one `establish` call; the prompt names the test in section 3 and says that
  ordinary gear is not a key item. A created item starts `unfound`, so creating it shows nothing to the player.
- **Changing hands**: a new tool, `key_item`, with a list of events `{name, event, note}` where `event` is `learned`,
  `acquired`, `used` or `lost` (section 4.2). An event on an item that does not exist is an error that tells the GM to
  create it first. The tool returns what the item's record now says, and the follow-ups of section 6.3 (an award is
  due; a quest is completed or unlocked).
- Items may exist before play: a scenario names its starting key items and which are held or known (5.3).

### 5.2 On learning and on acquisition

- **Learned**: the item becomes `known` and a custody fact is written. Nothing is described or painted. The `known`
  facts the GM has already given (a rumor of where it lies, what it is said to look like) now show in its entry.
- **Acquired for the first time** (from `unfound` or `known`):
  1. its `holding` becomes `held` and a custody fact is written (4.4);
  2. its `appearance` and `purpose` facts become `known`, because the party can now see what it holds, which is the
     same rule as a place's arrival aspects ([STATUS.md](STATUS.md) 5);
  3. an item Look and picture are queued (sections 7 and 8).

Other facts (origin, contents, powers) stay hidden until the GM reveals them in the normal way (`reveal`), so a
sealed letter is not read for the player by being picked up. Acquiring an item that was `known` reuses everything the
party was told, which the describer must respect (section 7).

### 5.3 Starting items

A scenario or campaign pack's seed may list key items with a starting `status` of `held` or `known`. They are created
before play and set at turn 0, and appear in the compendium from the first moment, with the Looks of the held ones made
by the first catch-up sweep. A held starting item gives no award (6.3). A custom game starts with none; the GM may
establish and give one in the opening.

### 5.4 The safety net

The GM may forget to call `key_item` when the narration hands over the ledger. A later step (section 13) adds a check
in the existing post-turn curation pass: it reads the narration for events on **existing** key items only, never
creating one, and applies them. Whether it is needed is for the first playtests to show.

## 6. Quests and awards

Quests are the story plan's **milestones** ([STORY.md](STORY.md) 3). Key items give them two new relationships, both
written by the plotter and checked by the server, and both are optional on any milestone.

### 6.1 Find-the-item quests

A milestone may name an item it is about: `finds: "<item id>"`.

- The plotter creates the item (as an `unfound` entity) and records its `whereabouts`, and perhaps its `origin` and
  `secret`, as hidden facts, connected to places and people that exist, under the usual no-floating-entities rule.
- When the quest becomes active, the party is meant to hear of the item. The briefing tells the GM that the item
  is to become `known` in this chapter's play, and the GM calls `key_item` with `learned` when the narration does it.
  A game may also make the item `known` earlier, from a rumor.
- The quest is finished by **acquiring** the item, but the server does not close it. The `key_item` result tells the
  GM "this completes [m08]; report it", and the GM reports it as it reports any milestone (`set_scene`'s story field,
  [STORY.md](STORY.md) 8.1). Some quests need more than the find (bring it to someone), so the GM decides.
- `gives` on the milestone names the item, so the plan's check that the party is built up for the goal counts it
  ([STORY.md](STORY.md) 7).

### 6.2 Quests that need an item

A milestone may list items it needs: `needs: ["<item id>", ...]`.

- Such a milestone stays `pending` until every needed item has been **acquired at some point**, in addition to the
  settled `requires` it already has (`story.settle_ready`). "At some point" means a spent or lost item does not take
  the quest away again. It is offered to the GM the turn after the item is acquired: the result of the `key_item`
  call names the quests it unlocks, and the story block of the briefing lists them as active.
- The party may therefore acquire the item **incidentally** (the ledger found in a wrecked office) and meet a quest
  they had no reason to look for. The plotter is told to use this: a clue that comes with its own quest.
- The plan is checked: every needed item exists and is a key item; the item has a way to be obtained, either a
  find-the-item milestone for it or a `whereabouts` fact at an existing place or person; and no required
  milestone can need an item that only a later milestone gives (the same reachability check as `requires`, with the
  item standing for the milestone that finds it). If the party can no longer obtain a needed item (its holder is
  killed), that is a plan break, handled as other breaks are ([STORY.md](STORY.md) 8.2).
- Item quests are ordinary milestones: they count toward the length table's totals and carry a `scale`. The plotter
  makes a few items, not many: about 1 to 3 planned key items in a short game, 3 to 6 in a medium one and 6 to 12 in
  a long one, so the compendium tab stays a shortlist. The GM's own improvised items (5.1) are in addition.

### 6.3 Awards

Gaining a key item should **usually** earn an award, the way a quest, a discovery or treasure does
([PROGRESSION.md](PROGRESSION.md)):

- The `key_item` result for a first `acquired` event says that an award is due and reminds the GM of the `award` tool,
  to be called in the same response, with the item's name as the reason.
- There is no automatic amount: it depends on the ruleset's own scale and on the item's weight in the story, so the
  GM works it out. The prompt says a find-the-item quest's award is the quest's, not a second one on top, and that
  the minor amounts suit an item picked up on the way.
- No award is due for a second acquisition (the item came back), for a starting item, or for `learned`.
- Because a prompt alone has not held in this project, the server records that an award is **owed** on the item's
  history entry. If no `award` call follows in the same turn, the next turn's briefing says "Unawarded: acquiring
  the steward's ledger" once, and then drops it. The GM may decline by saying nothing; "usually" is the rule.

## 7. The item Look

The record is `Look`, as ever, with `summary` (up to 20 words), `description`, `tags`, `rev`, `state` and `source`.
The description is **70 to 120 words**, present tense, about what the object looks like to someone holding it:
shape, size, material, wear, markings, and anything that stands out. Tags, chosen by the validator by kind:

| Tag | Values |
|---|---|
| `form` (controlled) | key, map, document, book, token, container, tool, jewel, relic, other |
| `frame` (controlled) | square, landscape, portrait: the shape of the picture (section 8) |
| `size` (controlled) | tiny, small, handheld, large |
| `material` | free text, up to 12 words |
| `condition` | free text, up to 12 words: new, worn, burnt at one edge |
| `markings` | free text, up to 12 words: a seal, a rune, handwriting, a crest |
| `features` | list of up to 5 short phrases |

The describer chooses `frame` for what the object is: a map, a chart, a scroll laid open, a plaque: `landscape`; a
letter, a ledger page, a document, a book standing up, a staff or a sword-shaped relic: `portrait`; a key, a ring, a
coin, a box, a gem, a statuette or anything unclear: `square`. When it cannot say, `square` is the default and the
validator replaces a missing or unknown `frame` with it.

Writing rules, in addition to the shared ones:

- **No legible text.** Image models cannot write, and a picture of a map with the wrong words is worse than none. A
  description may say there is a seal, a rune or neat handwriting, never quote what it says. The words belong in the
  `contents` fact.
- **No people or hands.** The object alone.
- The describer sees only what the party knows: the item's `known` facts, which on acquisition include its
  appearance, and the GM's `look_notes`. Never a hidden fact, and never the `secret` aspect. Where the party was
  told what it looks like before finding it, the description keeps to that and adds only detail that does not
  contradict it.
- An item is describable once it has been acquired (status `held`, `used` or `lost`, or a history that includes
  `held`). A `known` item is never described, as the owner decided.

The describer is the existing machinery with a third kind: a `describe_item` curator step, its schema and prompt, run
in the same post-turn pass and in the restore catch-up ([PLACES.md](PLACES.md) 19), with **thinking disabled** like the
other describers and the same retry, de-duplication and batch splitting. Two items that are alike (two brass keys)
must be made distinct in the `features`, since a picture must show which key is which.

## 8. The picture

- **Shape and size**: set by the Look's `frame` tag, and reported as `shape` in the API.

  | `frame` | `shape` | Size | Used for |
  |---|---|---|---|
  | `square` | `"square"` | 1024 x 1024 | keys, rings, boxes, anything unclear (the default) |
  | `landscape` | `"landscape"` | the places' size, 1536 x 1024 | maps, charts, scrolls laid open |
  | `portrait` | `"portrait"` | the places' size turned on its side, 1024 x 1536 | letters, ledgers, documents |

  The sizes are the ones the image model supports, so no new setting is needed; a place size set by
  `AIGM_PLACE_IMAGE_SIZE` fixes both the landscape and portrait items. A Look revision that changes `frame` makes a
  new picture of the new shape.
- **Prompt**: a still life of the single object, centred, on a plain surface with soft light, in the game's art style.
  The framing text says: no people, no hands, no legible writing, nothing else on the surface, the object whole and
  not cropped. A map or a document is shown whole, flat and slightly angled. The art styles gain an `item` variant
  where the plain version would look wrong (the comic style wants a clean outline, the sketch style a pencil study).
- **When**: only after acquisition. Never for `unfound` or `known` items. It is made, kept and served exactly like
  other pictures: same image library, same retry rules, same `GET /portraits/{file}` (shown only for visible items),
  same pending placeholder and catch-up on load.
- **Order**: after the party and the people in the scene, before other people and places, newest acquisition first,
  because a new item is what the player is most likely looking at.
- **A lost or used item keeps its picture.** It is not regenerated; if the story changes the item (a map torn in
  half), that is a Look revision, left for later like the other kinds.
- **Which items**: all of them. The function that picks (`place_wanted` for places) gets an `item_wanted` twin so a
  later limit has one place to go.

## 9. The API

- `GET /compendium` gains a category `items`, "Key Items", between Characters and Other, with its counts like the
  rest. The list is empty, and the tab can be hidden by the clients, until something is visible.
- A **list row** has a new field, `holding` (`known`, `held`, `used` or `lost`; `null` for other kinds), so the row can
  show a chip. (`status` already means new or updated.) Sort order for items: held first, then known (still to find),
  then used and lost, newest first within each; the `recent` sort is unchanged.
- `GET /compendium/entities/{id}` for an item adds:
  - `look` and `portrait` in the existing shapes, both `null` while the item is `known`; `portrait.shape` is
    `"square"`, `"landscape"` or `"portrait"`;
  - `holding`: `{status, since, history: [{turn, status, note}]}` with turns translated to the same form the entry
    already uses for "learned" times.
- `shape` is therefore no longer one of two words. Clients size a picture's frame from it, and treat an unknown
  shape as `square`.
- A change of holding counts as an **update** to the entry for the new/updated marks, through its custody fact.
- `GET /status` is unchanged in this step (section 12).
- The hidden tab on debug servers ([COMPENDIUM.md](COMPENDIUM.md) 11) lists unfound items too, marked as such, so a
  developer can see what the GM has in reserve.

## 10. Context for the GM

The GM needs to know what the party has and what it seeks. The world briefing gains one block, in every request:

- a line per **held** item: its name and summary (the Look's, or its appearance fact before the Look exists);
- a line per **known** item (marked "sought"): its name and what the party knows of where it is;
- unfound items as GM-only entries, in the way hidden facts already are, marked as not yet in play, so the GM can plan
  around them and knows to call `learned` or `acquired` when the story gets there;
- used and lost items only through `recall`.

This keeps the GM from narrating the party holding something it does not, or a held item as lost. The story block
([STORY.md](STORY.md) 10) names, for an active milestone, the item it finds or is unlocked by, and lists a pending
milestone that is waiting on an item (so the GM can plant the item without saying why).

## 11. Clients

- **App, compendium**: a fourth tab, Key Items (hidden while empty). Rows show the name, a small `Held`, `Sought`,
  `Used` or `Lost` label and the one-line summary; held items first. The entry opens with the picture, in its shape
  (portrait shape up to 240 px wide by 360 high, landscape up to 360 wide by 240 high, square as a person's portrait),
  then a **Description** block (the Look text), then a status line:
  - held: "Carried by the party since day 3";
  - known: "Not yet found", with no picture, no description and no placeholder; its known facts follow, which is where
    the player reads what they have heard of it (its whereabouts, what it is said to look like);
  - used or lost: "Used on day 5: burned to open the sealed door", "Lost on day 7: stolen by the harbor guard",
    greyed, in the same place;
  - a history list below it if there is more than one entry;
  then the known facts in the aspect order above.
- The app's picture component learns the portrait shape, beside square and landscape.
- A picture still being painted shows the quiet pending frame in the picture's shape once the Look has chosen it, and
  a square one before that, "Painting an object...".
- **Terminal client**: the tab, rows with the status, and the entry's Description, status and facts.
- No new status-tab content in this step.

## 12. Beyond this step

- **A strip of held items on the status tab**, thumbnails of what the party carries.
- **The curator safety net** (5.4).
- **Item Look revision** when the story changes the item.
- **Items in scene pictures or on maps**, once those exist.
- **Per-character carrying**, if the party is large enough for it to matter.
- **Limiting pictures** to important items (section 8).
- **A player-visible quest log** ([STORY.md](STORY.md) non-goals): known items are the natural first entries of one.

## 13. Build steps

1. **Model.** `item` kind and aspects, `Entity.holding` with the five statuses and its transitions, the ops
   (`LearnItem`, `Acquire`, `Relinquish`) with the custody facts and the acquisition reveal, save format 12 with its
   load checks, `establish` accepting `item` with its limits, the `key_item` tool and prompt, the briefing block, the
   debug dump. Tests: visibility, transitions, history, re-acquisition.
2. **Compendium.** The visibility rule in `_visible`, the `items` category, list status and sort, entity `holding`,
   new/updated marks; the terminal client's tab; the app's tab and entry without a picture (including the known
   state). Tests include the leak cases of 4.3.
3. **Item Looks.** Tags and validator for the kind (including `frame`), the curator step with schema and prompt, the
   sweep (for acquired items only), the scripted curator, the restore catch-up, the Description in the entries.
4. **Pictures.** The item framing and style variants, the three sizes, the job order, the `item_wanted` hook, the
   pending placeholder, the app's portrait shape and display, with a live run on a few sample items (a key, a map, a
   letter) before the step is called done.
5. **Quests and awards.** `finds` and `needs` on milestones with their reading and validation, `settle_ready` and the
   reachability check, the plotter's schema and prompt, the story block lines, the `key_item` follow-ups, the owed
   award record and its one-time reminder. Tests against scripted plans.
6. **Starting items.** The scenario seed field and its handling.
7. **The safety net**, if the playtests show the GM missing events.

## 14. Tests

- **Visibility**: an unfound item with `known` facts is absent from the list, search, related entities, a place's
  children and the status response, and its id is `404`; after `learned` it is present as `known`; after `acquired`
  it is present as `held`; after `lost` it is present with its status.
- **Known state**: a `known` item has no `look`, no `portrait`, no sweep job and no placeholder, whatever the
  configuration; acquiring it produces both.
- **Secrets**: a hidden fact and the `secret` aspect never reach a response, a describer request or a picture prompt,
  before or after acquisition.
- **Transitions**: every allowed change in 4.2, and every refused one with its message; acquired, used; acquired,
  lost, acquired again; the notes and turns come back in order; a second `acquired` on a held item changes nothing.
- **Tool**: `key_item` on an unknown name, on an entity that is not a key item (a person), with a missing event; the
  cap of two new items a call; `look_notes` required.
- **Compendium**: the category order and counts, status in rows, the sort, the new/updated marks on each change.
- **Look and picture**: the tag validation, `frame` defaulting to `square`, the size chosen for each frame, no-text
  rules in the prompt, the picture only after acquisition, the order of jobs, the pending placeholder, restore
  catch-up for a game that already holds items.
- **Quests**: a milestone with `needs` stays pending until the item is acquired (and stays unlocked after the item is
  used or lost); a `finds` milestone is not closed by the server; plan validation rejects a missing item, an
  unobtainable item and a required cycle through an item; the owed award is reminded once and cleared by an `award`
  call; no award is owed for a second acquisition or a starting item.
- **Saves**: an old save loads with no items; a new one round-trips.

## 15. Decisions and open questions

All of the first round's recommendations were accepted (section 2). What remains:

1. **Closing a find-the-item quest.** Section 6.1 leaves the closing to the GM, with a nudge from the tool result,
   because some quests need more than the find. The alternative is for the server to close a plain find automatically.
   **Recommended**: the nudge, and revisit if the GM forgets to report.
2. **How strictly awards are enforced.** One reminder in the next briefing, then silence (6.3). A stronger form,
   such as holding the next narration back until an `award` is made, would be heavy-handed for "usually".
3. **`learned` through rumor.** Only the GM (or later the safety net) makes an item `known`; the server never infers
   it from a fact. **Recommended**, since inference would risk showing an item the story meant to keep hidden.
4. **Frame choice.** The describer chooses `frame` from the object. If it proves unreliable, the `form` tag could set
   it by rule (map: landscape; document or book: portrait; the rest square), which is simpler and more predictable.
   **Proposed**: model's choice first, with the rule as the fallback when the model's answer disagrees with the form
   by an obvious margin (a key framed as a map).
5. **Spending.** Items add one image per acquisition. The per-game image cap remains deferred.

## 16. Step 1 findings

What was built, and where it differs from the text above:

- **Model** (`world/model.py`): kind `item` joins `KINDS` but not the new `CURATOR_KINDS`, which the curator's schema
  and the extraction and expansion passes use, so the curator can neither create an item nor flesh one out
  (`frontier` skips them). `Entity.holding` is a `Holding` (`status`, `since`, `history` of `HoldingChange`). The
  transitions are `HOLDING_EVENTS`, and `World.set_holding` applies them, writes or supersedes the `custody` fact
  (known, so it carries a `learned_seq` and counts as an update) and, on the first acquisition, reveals the item's
  `appearance` and `purpose` facts. A repeated event is a quiet no-op; an impossible one raises `WorldError`.
- **Discovered**: for an item, `discovered` is not set by known facts (`_mark_discovered` skips items) but by learning
  of it or getting it, so a known fact that mentions an unfound item shows nothing. `compendium._visible` already
  honours the holding; the `items` category itself is step 2.
- **`establish`** takes kind `item`. `look_notes` is required (2 to 30 words, a phrase completing "It is ...") and is
  stored as a **hidden `appearance` fact**, "Sluice Key is a heavy brass key.", so nothing new is needed to keep it
  until the item is acquired, and it becomes known with the rest of the appearance. The cap of two new items is per
  call, not per turn. A new item is a detail, so chapters 2 and 3 allow it (`addition_allowed`).
- **`key_item`** (events `learned`, `acquired`, `used`, `lost`, each with a `note`) is all or nothing like `establish`
  and is described by `prompts/tools/key_item.md`; `04_world.md` has a paragraph on key items. The award and quest
  follow-ups of section 6 are step 5.
- **Briefing**: a block of the items the party has, the ones it seeks (with what is known of where they are), and the
  unfound ones as a GM-only list that can be cut for space; used and lost items are left to `recall`.
- **Save**: format 12; saves without a holding load, and an item gets an `unfound` one. The debug dump shows it.
- **Tests**: `tests/test_key_items.py`.

## 17. Step 2 findings

- **Server** (`compendium.py`): category `items`, "Key Items", between Characters and Other. `_visible` is true for an
  item whenever its status is not `unfound`, so related entries, children and search all follow without further
  checks. List rows and details carry `holding`; the rows of the `items` category sort held, then known, then used or
  lost (newest first), and the summary prefers the appearance, then the purpose and whereabouts, and leaves the custody
  sentence for last. The debug hidden tab's rows say what an item's holding is.
- **Naming**: a list row's `status` already means new or updated, so the item's standing is the separate `holding`
  field; section 9 is corrected.
- **Turns, not days**: an entry says "Held by the party since turn 4" rather than a day, because a holding records the
  turn. The wording in section 11 is a sketch.
- **Terminal client**: the tab (key `3`, which moves Other to `4` and Hidden to `5`), row labels (held, to find, used,
  lost), the standing line and the history; a `Description` heading is ready for step 3's Look.
- **App**: the same, with the standing logic in `core/compendiumModel.ts` (`holdingView`).
- **Tests**: `tests/test_key_items.py` (the visibility and leak cases, ordering, new/updated marks, HTTP), the
  client's model and screen tests and the app's unit test. The end-to-end test checks the tab exists; no end-to-end
  game yet has a key item to show.

## 18. Step 3 findings

- **Look record** (`looks.py`): a third kind of Look, `ITEM`, chosen by `look_kind("item")`, with the tags of section 7
  (`ITEM_CONTROLLED_TAGS`, `ITEM_TEXT_TAGS`, `ITEM_LIST_TAGS`), descriptions of 60 to 140 words (`word_limits`; the
  prompt asks for about 90 and never more than 120) and a name check as loose as a place's. `frame` is the one tag the
  validator does not insist on: `frame_of(look)` reads a missing or unknown one as `square`, and the sweep writes the
  resolved value into the stored Look. `LOOK_KINDS` now includes `item`, so the world, the save and `set_look`
  accept it.
- **The describer** (`world/describe_items.py`) follows the places': `describable` is "the party has had it in hand"
  (`Holding.acquired`, so a used or lost item is still described and a known one never is), items named in the last
  narration go first and then the most recently acquired, and the model is shown only **known** facts (the bookkeeping
  `custody` sentences are left out), the note of how the party came by it, and the narration that names it. Batches of
  6, up to 12 an item sweep, one retry with the reasons, one split in two when a batch fails, and a "too alike" rule
  (the same form, material and markings, or nearly the same summary) so two brass keys are told apart.
- **Curator**: `item_look` on the `Curator` protocol (optional, like `place_look`), `ItemSubject`/`ItemLookRequest`,
  `render_item_looks`, `ITEM_LOOK_SCHEMA` and `prompts/world/describe_item.md` for the Anthropic curator, with thinking
  off (the lesson of [PLACES.md](PLACES.md) 19), and a deterministic scripted one for tests.
- **When it runs**: after a turn (`curate`) and in the restore catch-up, through `CuratorService.run_item_looks_if_due`,
  with its own back-off (`Session.item_looks_retry_turn`).
- **Seen by**: the compendium entry's `look` (a `known` item still has none), the GM briefing's line for a held item
  (the Look's summary now stands in for the appearance fact), and the clients' Description heading.
- **A live run** with the real describer on six sample items (two brass keys, a ledger, a sea chart, a sealed letter and
  a reliquary) gave distinct, plausible descriptions of 91 to 100 words in one call. The chart came out `landscape`, the
  ledger and the letter `portrait`, the keys and the box `square`, and nothing from the hidden "secret" fact of each
  appeared. The letter's description says its handwriting is neat without quoting it.
- **Tests**: `tests/test_item_looks.py`.

## 19. Step 4 findings

- **Prompt** (`art.build_item_prompt`, `ITEM_FRAMING`): the style's object variant, the still-life framing (one object,
  whole, centered, plain surface, no people or hands, no readable writing), then "The object:" with the Look's
  summary, a short tag line (form, size, material) and its description, with the item's name and aliases taken out
  ("the object"). Eight styles gained an `item` direction where the plain one speaks of faces, heroes or landscapes
  (gouache, comic, vivid, detailed, clean, sketch, anime, illustration); the other four use their own.
- **Pipeline** (`portraits.py`): a `Job` has a `kind` (person, place, item). Item jobs come after the party, the party's
  place and the people in the scene and before the other people and other places, the most recently acquired item
  first; `item_wanted` is the hook for a later limit. A picture is only made for an item the player can see (so never
  an unfound one) and only once it has a Look, so a `known` item has neither. The size comes from the Look's `frame`:
  square at the portrait size, landscape at the place size, portrait at the place size turned on its side
  (`PortraitService.size_for`), and the API's `shape` follows. A refusal is recorded and not retried or softened, as for
  places. The picture of a lost or used item stays.
- **Pending**: an acquired item without a Look shows `pending` (square, until its Look picks a frame) when the curator
  can describe items and its sweep is not backing off; a known or unfound one shows nothing. `GET /portraits/{file}`
  serves an item's picture only while the item is visible.
- **App**: `core/pictures.ts` (`shapeOf`, `frameFor`, `paintingText`) decides the frame: landscape fills the column at
  3:2, a portrait-shaped picture is 240 by 360 (160 by 240 on a phone), a square one as a person's. An object's
  placeholder shows its name and "Painting an object...". The entry passes its kind, so no component guesses.
- **Test mode**: `item <name> [learned|acquired|used|lost]` makes the scripted GM call `establish` and `key_item`, so
  the browser test plays the whole chain: acquire, described, pictured, shown on the Key Items tab.
- **A live run** with the real describer and the real image model (style `gouache`, three images) on a key, a chart and
  a sealed letter: the sizes were 1024 x 1024, 1536 x 1024 and 1024 x 1536, as the frames said. Each picture was one
  object on a plain surface, whole and uncropped, with no hands, no people and no readable writing. The chart came out
  as an unrolled sheet beside a rolled scroll, with only decorative marks (two compass roses, a dotted route);
  the letter as a folded square with a grey wax seal. The cost was one image call each.
- **Tests**: `tests/test_item_pictures.py`, `app/tests/pictures.test.ts` and the end-to-end test.

## 20. Step 5 findings

- **The plan** (`story.py`): a milestone has `finds` (an item entity id or `null`) and `needs` (a list of ids), saved
  with the story; an older plan loads with neither. `settle_ready(story, world)` opens a pending quest only when its
  `requires` are settled **and** every item it needs has been in hand (`items_in_hand`: `Holding.acquired`, so a spent
  or lost item keeps the quest open and a merely known one does not open it). Without a world a quest that needs an
  item stays pending, so every caller passes the world: a reported quest and a chapter change (`report`,
  `check_story_report`), the `award` tool, a later chapter's plan and the plotter itself.
- **Checks** (`validate_plan`): a named item must be a key item of the world; a quest may not find and need the same
  item; an item a quest needs must be found by some quest or have a `whereabouts` fact; and the graph check treats
  "needs an item that quest F finds" as a link to F, so a cycle through an item is refused and so is a quest that needs
  an item only a later chapter finds. The check that the party is built up for the goal is unchanged.
- **The GM's notes** (`briefing_block`): an active quest that finds an item says where the party stands with it ("the
  party has not heard of it yet: let them hear of it this chapter, then call key_item `learned`", "knows of it and is
  looking for it", "has it"), and a quest waiting for an item is listed as not offered, with the instruction to let the
  party come by the item through play and say nothing of why.
- **`key_item` follow-ups**: on the first time the party gets an item, the result says which active quest that
  completes (to be reported in the next `set_scene` `story` field), or that an award is due, and names the quests the
  item has just opened (the story is changed on the turn's working copy, like the world). The server does not close the
  quest. A second getting, a `learned` or a starting item says nothing about an award.
- **The award**: a first acquisition leaves `Holding.owed` set to the turn (never for a `seed` item, never for one that
  came back), the `award` tool clears it for the current turn, and the briefing of the turn after says "Unawarded: ..."
  once; no later turn nags. The compendium never shows `owed`.
- **The plotter**: `PlotProposal` quests have `finds` and `needs` (item names, resolved to ids and, for a later chapter,
  re-pointed at the live world's items like a quest's entities). The plotter, and only the plotter, may create `item`
  entities (`PassConfig.allow_items`; the plot schema's entity kinds include `item`, the curator's do not). Its
  entity caps rose from 8 to 16 per pass and key items are the last to be cut, because the first live runs lost the
  item to the old cap and then failed the plan; the message sent back for a missing item now says to create it with
  its facts, connected to a place that exists, under exactly the same name. `prompts/world/plot.md` has a Key items
  section.
- **A live run** of the real plotter: a short game gave a find-the-item quest in chapter 2 and a quest that needs it in
  chapter 3; a medium game's chapter 1 gave a find quest ("The Cracked Stone") and a quest that needs the stone
  ("What Lies Under Hollow Weir"), with the item made with appearance, purpose and whereabouts facts. Before the cap fix
  two of three medium runs failed.
- **Tests**: `tests/test_key_item_quests.py`.

## 21. Step 6 findings

- **Where the seed comes from**: this project has no campaign packs yet ([CAMPAIGNS.md](CAMPAIGNS.md) is a design), so
  the one seed there is is Session 0. `begin_adventure` takes an optional `key_items` list (at most four), each with a
  `name`, an `appearance` phrase (2 to 30 words, completing "It is ..."), an optional one-sentence `purpose` and a
  `status` of `held` or `known`. The tool refuses a repeated name, a name a party member or key person already has,
  a thin appearance and any other status, with the reason, and the call changes nothing. The tool's prompt tells the GM
  to list only quest objects and only what the player has been told about. A pack would give the bootstrap the same
  list under `campaign["key_items"]`.
- **The record**: the campaign is saved with the list, and the GM's written record of Session 0 gets a "Key items"
  section (a placeholder in `campaign_record.md`), so the GM knows what the party has and seeks without the notes.
- **The bootstrap** (`run_bootstrap`) makes each one before the curator is asked for anything: the entity, its
  `appearance` and `purpose` as **known** seed facts (the player set them up, so they are never "new"), and a
  `SetHolding` with source `seed` at turn 0: `acquired` for a held item, `learned` for a known one. A seed item owes no
  award. The curator's own bootstrap answer still cannot make an item.
- **Result**: from the first moment the held item is in the Key Items tab, the GM's notes list it, and the first sweep
  describes and pictures it (the restore catch-up does the same for a game loaded from a save made before); a known item
  shows as "to find" with the facts it was given and nothing else.
- **Tests**: `tests/test_starting_items.py`. The real GM has not been run against the new tool field.

