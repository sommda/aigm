# AIGM Compendium: Design

Status: built (server and client). Differences from the first draft are noted in section 9.

This is the design for a player-facing compendium: a running list of the characters, locations and other things
(factions, concepts) the player has learned about, with the details they know, a mark for what is new, and a server API
and client screen to browse it.

## 1. Goal

- The player can open a list of **locations**, **characters** and **other** things (factions, concepts) at any time and
  read what their characters know about each.
- It shows **only what the player has been told**. Nothing hidden is ever sent to a client, not even as a name.
- It **grows as the player learns**. When something new is learned, an entity appears; when something more is learned
  about an entity, it is marked as updated.
- The server holds the data and the rules; the client only draws it.

### Non-goals (v1)

- Editing: the player cannot add, rename or delete entries, or write notes. The compendium reads the world; it never
  writes to it, apart from the "seen" marks (section 4).
- Items, creatures, quests, the map, a timeline, or the party's own sheets. Quests are the story's business (STORY.md),
  and the party is in the campaign record.
- Images, portraits, relationship graphs.
- A search over fact text. Names and aliases only.

## 2. What already exists

The world knowledge base (WORLD.md) is nearly all of this already:

- `Entity` has a `kind` (`location`, `npc`, `faction`, `concept`), `aliases`, a `parent` (containment for locations)
  and a cached `discovered` flag.
- `Fact` has a `disclosure` (`hidden`, `hinted`, `known`), an `aspect` (the checklist slot, such as `appearance`),
  `revealed_turn`, and `status` (`active`, `superseded`).
- A fact becomes `known` when the GM states it with `establish`, or when the curator sees the narration reveal a hidden
  fact. `discovered` is set on every entity a known fact is about.
- WORLD.md 2.3 and section 10 say there is deliberately no client-visible world in v1. This design is the exception
  that note anticipated ("the `known` subset would make a natural player journal").

What is missing is a **filtered, read-only view**, a way to know **what changed since the player last looked**, and an
API and a client for them.

## 3. What the player may see

The one rule: **a client is shown a fact only if it is `known` and `active`**, and an entity only if it is
`discovered`. Everything below follows from that. It is enforced in one place, `aigm/compendium.py`, which is the only
code that turns world data into compendium responses, so a leak cannot come from a route forgetting a check.

| World data | Shown? |
|---|---|
| Entity that is not `discovered` | Never. Not in lists, and its id answers `404` exactly like an id that does not exist |
| Fact that is `hidden` or `hinted` | Never |
| Fact that is `known` and `superseded` | No. The newer fact that replaced it is shown (and counts as new) |
| Fact that is `known` and `active` | Yes, with its text, aspect and the turn it was learned |
| The entity's name | Yes once discovered |
| An alias | Only if the player has met it: it appears (case aside) in the text of one of the entity's known facts |
| The `parent` of a location | Only if the parent is itself discovered; otherwise the location is shown without one |
| Children of a location | Only the discovered ones |
| Related entities (sharing a known fact) | Only the discovered ones |
| `source`, `created_at`, `superseded_by`, anything about the GM's notes or the story plan | Never |

Two risks the rules cannot remove, and what to do about them:

- **A name can be a spoiler.** If the world calls an entity "The Traitor, Captain Vael" and a known fact mentions her
  in passing, the entry's name would give it away. The mitigation is in the prompts, not the filter: entity names are
  what the characters would call them, with the secret in facts. This is already the instruction for `establish`; the
  prompt check is part of build step 6.
- **A known fact can name an undiscovered entity** only if the curator wrote it badly, since marking `discovered` covers
  every entity a known fact is about. The filter never shows an entity that is not discovered, and the fact text is
  shown as it is (it was narrated to the player already).

## 4. New and updated: the "seen" state

The player should see at a glance what changed since they last looked. Two design questions: what counts as a change,
and where the "last looked" state lives.

### 4.1 What counts as a change

Each fact gets a **learned sequence number**, `learned_seq`, taken from a counter on the world (`World.learn_seq`) at
the moment the fact becomes known: when it is created already known (`establish`, extraction), or when `reveal`
flips it. The counter only goes up and is never reused. The turn number is not enough: several facts are learned in
one turn, and a view can fall between them.

Facts that exist when the adventure starts (the bootstrap seeds from Session 0) get `learned_seq = 0`, which means
"known from the start, never new". The player has just spent a whole session setting those up.

### 4.2 What is "seen"

`GameState.compendium` holds the player's reading state, and is saved and copied with the game:

```jsonc
{
  "all_through": 0,                // everything learned up to this sequence number has been seen
  "seen": { "e007": 41, "e003": 58 }   // per entity: facts learned up to this number have been seen
}
```

A known fact is **unseen for an entity** it is about (as subject or as a mention) if
`learned_seq > max(all_through, seen.get(entity_id, 0))`. Each entity page judges its own facts, so a fact about two
entities can be new on both pages until each has been read. This is what makes an entity that was only ever mentioned
show up as new when it is first discovered.

From that, an entity's **status** is derived, not stored:

| Status | When |
|---|---|
| `new` | It has unseen facts and **all** of its known facts are unseen: the player never looked at it, or it has only just been discovered |
| `updated` | It has unseen facts and some seen (or from-the-start) ones |
| `null` | Nothing unseen |

A category's `new` count is the number of its entities whose status is `new` or `updated` (they are counted together
as "unseen entities"; the two are split in the response so a client can style them).

### 4.3 Where it lives, and why

Server-side, in the save, rather than in the client:

- It follows the game: a saved game restored later, or the same game opened from another terminal, shows the same
  marks. A client-side set would be lost with the client's state and could not be tied to a save.
- It reuses the save and staged-turn machinery. A turn that fails and is discarded takes its facts, its learned
  numbers and their effects with it.

Marking things seen is a write, so it is a separate call (section 6.5), never a side effect of `GET`. The client
makes it explicitly, after it has actually drawn what it marks.

**Marks made during a turn.** A turn works on a copy of the game state and replaces the live one when it ends, so a
change to the live `compendium` mid-turn would be overwritten. The same issue exists for curator results, and the
rule is the same: `POST /compendium/seen` while a turn is running is accepted, queued on the session
(`Session.pending_seen`), and applied with the pending curator work between turns (`drain_pending`). The marks only
ever raise a number, so applying them late, or twice, is harmless. Because the call is accepted either way, the client
never has to care.

**Save format 6** adds `compendium` and a `learned_seq` on each fact (and `learn_seq` on the world). Older saves load
with `learned_seq = 0` everywhere and an empty reading state, so an old game opens with nothing marked new. The first
revelation after loading is the first thing to be new.

## 5. Server design

### 5.1 Categories

The player's three groups map from the world's four kinds:

| Category id | Title | Kinds |
|---|---|---|
| `locations` | Locations | `location` |
| `characters` | Characters | `npc` |
| `other` | Other | `faction`, `concept` |

Every entry also carries its `kind`, so the client can tell a faction from a concept inside "Other" (a small label).
Adding a world kind later (items, creatures) means adding it to this one table.

### 5.2 Module

`aigm/compendium.py`, pure functions over a `World` and a `Compendium` (the reading state), with no I/O:

- `Compendium` (dataclass): `all_through`, `seen`; `to_dict`/`from_dict` with the same validation habits as `Hero`;
  `mark_seen(entity_ids)`, `mark_all(world)`, both only raising numbers.
- `entries(world, comp, category, *, q=None, status=None, sort="name")` returns the list rows.
- `detail(world, comp, entity_id)` returns the detail, or `None` for an entity that is unknown or not discovered.
- `summary(world, comp)` returns the counts for `/compendium` and for `message_end`.
- `visible_aliases(entity, known_facts)` and `public_facts(world, entity_id)` hold the filter rules of section 3.

Nothing else in the server builds compendium data.

### 5.3 List row

```jsonc
{
  "id": "e007",
  "name": "Harrow Mine",
  "kind": "location",
  "category": "locations",
  "summary": "An abandoned silver mine in the Thornwood.",   // one known fact, see below; may be ""
  "parent": { "id": "e003", "name": "Thornwood" },            // locations only, discovered parents only; else null
  "depth": 0,                                                // nesting in a `tree` sort; 0 otherwise
  "fact_count": 5,                                           // known, active facts about it
  "status": "updated",                                       // "new" | "updated" | null
  "unseen_count": 2,
  "learned_turn": 31                                         // when the player first learned of it
}
```

`summary` is the text of the entity's most describing known fact: the first known subject fact in this order of
aspect: `role`, `nature`, `goals`, `approach`, `discovery`, `history`, then the earliest known one. It is cut at about
140 characters on a word boundary. It is only a list preview; the detail has everything.

### 5.4 Detail

```jsonc
{
  "id": "e007",
  "name": "Harrow Mine",
  "kind": "location",
  "category": "locations",
  "aliases": ["the old mine"],                    // only those the player has met (section 3)
  "status": "updated",
  "parent": { "id": "e003", "name": "Thornwood" },
  "path": [ { "id": "e001", "name": "Ashby Vale" }, { "id": "e003", "name": "Thornwood" } ],   // discovered ancestors
  "children": [ { "id": "e012", "name": "Lower Gallery", "kind": "location", "status": "new" } ],
  "facts": [
    {
      "id": "f0042",
      "text": "The Harrow Mine was abandoned forty years ago after a collapse.",
      "aspect": "history",
      "label": "History",                           // display label for the aspect; null when it has none
      "learned_turn": 31,
      "new": false
    }
  ],
  "related": [ { "id": "e020", "name": "Thorn Guild", "kind": "faction", "category": "other" } ],
  "learned_turn": 31,                              // first learned
  "updated_turn": 48                               // most recent learned fact
}
```

- `facts` are the entity's known, active facts, subject facts first and facts that merely mention it after, each group
  ordered by the aspect checklist (the order of `ASPECTS` for the kind, so a character reads role, appearance, manner,
  and so on) and then by `learned_seq`. Facts with no aspect come last.
- `related` is every discovered entity that shares a known fact with this one and is not its parent or child, at most
  12, most recently shared first. It is what lets a client link "Thorn Guild" from a location page.
- `children` are the discovered direct children, in the order they were discovered.
- A fact's `new` is `learned_seq` above the entity's seen mark, as in 4.2.

### 5.5 REST API

All calls take the usual `session_id` query parameter. They only read the committed game state, so they are always
safe and cheap, including while a turn is running (they show the game as of the last finished turn).

| Method | Path | Purpose |
|---|---|---|
| GET | `/compendium` | Counts for the three categories and the unseen totals |
| GET | `/compendium/{category}` | The list for `locations`, `characters` or `other` |
| GET | `/compendium/entities/{entity_id}` | The detail of one entity |
| POST | `/compendium/seen` | Mark entities, or everything, as seen |

**`GET /compendium`**

```jsonc
{
  "session_id": "default",
  "phase": "adventure",
  "categories": [
    { "id": "locations",  "title": "Locations",  "count": 6, "new": 1, "updated": 1 },
    { "id": "characters", "title": "Characters", "count": 4, "new": 0, "updated": 2 },
    { "id": "other",      "title": "Other",      "count": 2, "new": 0, "updated": 0 }
  ],
  "new": 1,        // totals across the categories
  "updated": 3
}
```

In Session 0, or with no world yet, every count is `0`; this is not an error.

**`GET /compendium/{category}`** has query parameters `q` (case-insensitive substring of the name or a visible
alias), `status` (`new`, `updated` or `unseen` for either), and `sort` (`name`, the default; `recent`, most recently
learned first; `tree`, locations only: parents before their children, siblings by name). It returns

```jsonc
{ "session_id": "default", "category": "locations", "title": "Locations", "count": 6, "entries": [ /* rows, 5.3 */ ] }
```

`count` is the number of entries returned. An unknown category is `404 not_found`; a bad `status` or `sort` is
`422`, like the other endpoints.

**`GET /compendium/entities/{entity_id}`** returns the detail (5.4). `404 not_found` for an id that does not exist
**and** for one that exists but is not discovered, with the same message, so the call cannot be used to probe the
hidden world. A malformed id is `422`.

**`POST /compendium/seen`**

```jsonc
// request: exactly one of the two
{ "entities": ["e007", "e012"] }     // these entities, up to every fact learned so far
{ "all": true }                      // the whole compendium
```

The response is the `GET /compendium` summary after the change, so the client can update its indicator without
another call. Ids that are unknown or undiscovered are ignored, not an error. If a turn is running the marks are
queued (4.3) and the response is computed as if they were applied. This is the only compendium call that changes
anything.

**Other additions.** `/health` gains `"compendium": true`, so a client can tell a server that has the feature.
`message_end` gains `compendium: { "new": n, "updated": m }`, the unseen totals after the turn, so a client's
indicator is current without polling. `GET /chat/history` and `POST /history/{name}/restore` report the same object
so the indicator is right after loading a game. All of it is additive; older clients ignore it.

**Freshness.** The curator may reveal a fact at the start of the *next* turn (WORLD.md 4.5, `drain_pending`), so a
`message_end` count can lag a turn behind what the narration just told the player. That is acceptable for an
indicator, and a view that fetches on opening is always right. An `establish` made by the GM is in the turn's own
state and shows at once.

### 5.6 Code touched

| File | Change |
|---|---|
| `world/model.py` | `Fact.learned_seq`, `World.learn_seq`, stamping in `_insert_fact` and `reveal`, save and load |
| `session/state.py` | `GameState.compendium`, copied, saved and loaded |
| `session/persistence.py` | `FORMAT_VERSION = 6`, older versions still readable |
| `session/store.py` | `Session.pending_seen`, applied in `drain_pending`, cleared in `reset_world_work` |
| `compendium.py` | New, section 5.2 |
| `routes/compendium.py` | New, section 5.5; registered in `app.py` for every mode (not debug only) |
| `routes/health.py`, `models.py`, `routes/chat.py`, `routes/history.py` | The additive fields above |
| `world/scripted.py` | The test-mode curator reveals something, so `--test` shows the feature end to end |

## 6. Client design

### 6.1 Entry points

- **Key:** `Ctrl+G` ("guide"), shown in the footer as `^G Compendium`. `F5` is an alias. `Ctrl+G` is not used by
  Textual's input or by anything bound today.
- **Slash command:** `/compendium` (aliases `/journal`, `/c`) opens the screen. `/compendium locations`
  (or `characters`, `other`) opens on that tab, and `/compendium Wren` opens the entry whose name or alias matches
  (a unique case-insensitive prefix or exact match; with several matches it opens the tab with the filter applied).
- **Indicator:** when there is anything unseen, the status line shows `✦ 3 new` (`* 3 new` with `--ascii`) and the
  footer hint is the plain `^G Compendium`. It comes from `message_end.compendium`, `/chat/history`, and every
  compendium call, and disappears when the count reaches 0.
- **Availability:** when `/health` has no `compendium: true`, the key is unbound, the footer omits it, and
  `/compendium` prints "This server does not offer the compendium", as the context view does for non-debug servers.
  Session 0 opens the screen with every tab empty ("Nothing is known yet.").

### 6.2 The screen

A full-screen modal over the transcript, like the context viewer, with the same look and `--ascii` rules:

```
┌─ Compendium ───────────────────────────────────────────────────────────────┐
│  [1 Locations (6) ✦2]   2 Characters (4) ✦2    3 Other (2)                   │
├────────────────────────────────────┬───────────────────────────────────────┤
│ ✦ Ashby Vale                  new  │ Harrow Mine                 location │
│   ▸ Thornwood                      │ in Ashby Vale › Thornwood            │
│     ✦ Harrow Mine         updated  │ also called: the old mine            │
│       Lower Gallery                │                                      │
│   Rusty Flagon                     │ History                              │
│                                    │ ✦ The Harrow Mine was abandoned      │
│                                    │   forty years ago after a collapse.  │
│                                    │ Approach                             │
│                                    │   It lies 3 miles east of Ashby.     │
│                                    │                                      │
│                                    │ See also: Thorn Guild, Wren          │
├────────────────────────────────────┴───────────────────────────────────────┤
│ ←/→ tab  ↑/↓ move  Enter open  / filter  n next new  a mark all seen  Esc    │
└────────────────────────────────────────────────────────────────────────────┘
```

- **Tabs** across the top, one per category, each with its count and a `✦ n` for unseen entities. Left and right (or
  `1`, `2`, `3`) switch. Locations show as an indented tree (`sort=tree`); the other two as a flat list by name.
- **Left pane: the list.** One row per entity: the new marker, the name, and a right-aligned `new` or `updated` tag.
  The marker and tag are both shown, so color is never the only signal: `new` green bold, `updated` yellow. The row
  under the cursor also shows its `summary` dimmed on a second line. On a terminal narrower than about 100 columns the
  right pane is dropped and Enter opens the detail full screen, with Esc going back to the list.
- **Right pane: the detail** of the entry under the cursor, loaded on demand and cached for the opening. Facts are
  grouped under their aspect label, new ones marked with the same `✦`. A line of breadcrumb for locations
  (`path`), the aliases, and a `See also` line with the related entities. `Tab` moves into the detail, where `↑`/`↓`
  select a related entity or child and `Enter` jumps to it (switching tab if needed); `Backspace` goes back to where
  it came from.
- **Filter.** `/` opens a one-line filter over the current tab (the `q` parameter, done on the server). `Esc` clears
  it before it closes anything.
- **Keys.** `n` jumps to the next unseen entry (across tabs); `a` marks everything seen (asks nothing, since it only
  clears marks); `r` fetches again; `u` toggles "unseen only"; `Esc`, `q` or `Ctrl+G` close.

### 6.3 When things are marked seen

The marks should mean "the player has read it". Rules, in the model, not the widgets:

- Showing an entity's **detail** (the cursor rests on it for about a second, or Enter) marks that entity seen. The delay
  stops a fast scroll down the list from clearing everything.
- Leaving the screen sends the batch of marks as one `POST /compendium/seen`, and so does a pause of a few seconds
  while open, so a closed terminal loses at most a few seconds of marks. The marks are applied to the screen at once.
- `a` sends `{"all": true}` straight away.
- A mark that fails to send is kept and sent with the next batch. The screen never blocks on it.
- While open, the `✦` markers on rows already read **stay until the screen is closed**, so the player can still see
  what was new when they came in. After closing they are gone.

### 6.4 Code

Following the context viewer, so each part can be tested without a terminal:

| File | Contents |
|---|---|
| `api.py` | `compendium()`, `compendium_list(category, q, status, sort)`, `compendium_entity(id)`, `compendium_seen(ids=None, all=False)` |
| `events.py` | `message_end.compendium` parsed into `MessageEnd` |
| `compendium_model.py` | Pure: tabs, the tree of locations, filter, cursor, the pending marks, and the rendered lines for a width |
| `compendium_screen.py` | The thin Textual screen: key bindings, the two panes, the calls |
| `session.py` | `ChatSession.compendium_new` for the indicator; set from `message_end` and from loading |
| `commands.py`, `app.py` | `/compendium` parsing, `Ctrl+G`, footer and status-line text |
| `tests/fake_server.py` | The new endpoints, with a small sample compendium |

Errors follow the other screens: a failed call shows the message inside the screen with `r` to retry; `404` from an
older server shows the "does not offer" text.

## 7. Testing

Server (`tests/test_compendium.py`, plus additions):

- **The filter.** A world with hidden, hinted, known and superseded facts, an undiscovered entity, and a hidden
  alias. For every category, list, detail, `related`, `children`, `path` and `message_end`, walk the JSON and assert
  that no hidden text, no undiscovered name, and no hidden alias appears anywhere in the serialized response. This is
  the most important test in the feature, and it runs across the whole API rather than one field.
- `404` is identical for an unknown id and an undiscovered one.
- **Status.** `learned_seq` is stamped on creation and on reveal; seed facts are never new; a new entity is `new`; a
  later fact makes it `updated`; a superseding fact shows the new text as new and drops the old one; `mark_seen`
  clears it and never lowers a mark; `all_through` clears everything.
- **Staging.** A failed turn discards facts learned in it and the marks that depended on them; `POST /compendium/seen`
  during a busy turn is queued and applied after.
- **Saves.** Round trip, a version 5 save loads with nothing new, the counter survives restore, `copy` is independent.
- **API.** Categories, `q`, `status`, the three `sort` orders including `tree` with an undiscovered parent, validation
  errors, Session 0 empty, `message_end.compendium`, `/health`.
- Test mode (`--test`) reveals a fact so the scripted game exercises the whole path.

Client (`tests/test_compendium_*.py`):

- The model: tabs, tree order and indent, filter, next-unseen across tabs, the pending marks, lines at several widths
  and in `--ascii`.
- The screen with Textual's pilot against `FakeServer`: opening by key and by `/compendium`, switching tabs, opening an
  entry, the delayed mark and the batch on close, `a`, `n`, narrow layout, an error and the retry, an old server.
- The indicator: set by `message_end`, cleared by marking, hidden when the server lacks the feature.

Both suites must pass, and the docs follow the standard in CLAUDE.md. `API.md` gets the endpoints, `WORLD.md` section
2.3 and 8 get a pointer here instead of the "no client sees the world" text, and `CLIENT.md` gets a screen section.

## 8. Build order

1. World and state: `learned_seq`, `learn_seq`, `Compendium`, save format 6, the loading tests.
2. `compendium.py` with the filter and its whole-response leak test. Nothing else can start before this is right.
3. Routes, `message_end`, `/health`, history and restore fields, the queued marks. API docs.
4. Client model and API calls, tested against the fake server.
5. Client screen, key, command, indicator.
6. Prompt check on entity naming (section 3), the test-mode path, and a playtest with the real model: does the
   compendium fill as the player expects, and does the curator keep names clean?

Steps 1 to 3 are the server and can be tried with `curl` before any client work exists.

## 9. Decisions to confirm

These are the choices I made where the request left room. Each is cheap to change before building.

1. **Reading state lives on the server and in the save**, not the client. The cost is a format bump and the queued
   marks; the gain is that marks follow a saved game.
2. **Hinted facts are not shown.** WORLD.md models a rumor as a separate known fact, so a hinted fact is by definition
   something the player has not been told.
3. **Aliases are shown only once met** in a known fact's text. The alternative, showing all aliases of a discovered
   entity, risks revealing a secret name; the cost of the rule is that an alias the GM used aloud but never recorded in
   a fact does not appear.
4. **Facts from the start of the adventure are never "new".** A new game opens with an empty indicator.
5. **"Other" holds factions and concepts together**, with the kind as a label, as asked. Splitting them later is a
   change to the table in 5.1.
6. **Marking seen is automatic on reading** (the delay in 6.3) instead of only by an explicit key, with `a` as the
   shortcut for everything. A pure manual mark would leave the indicator stuck for players who never learn the key.
7. **No transcript announcement** such as a dim "Compendium updated: Wren" line after each turn. The status-line
   indicator is quieter. If playtesting shows players miss it, that line is a small addition on the client alone,
   driven by `message_end.compendium`.
8. **The party's own characters are not entries.** The compendium is what the party has learned about the world; the
   party is shown in the campaign record and the progression notes (PROGRESSION.md).

## 10. What changed while building

- The footer does not show the unread count (the footer is static text per binding); the status line does.
- An entity that is only *mentioned* by a new fact counts as `updated`, so a new fact about the mine also marks the
  Thornwood page. That follows the rule in 4.2, and it is what makes an entity first discovered by a mention show as
  new, but it can make "updated" more common than "new". If playtesting finds it noisy, the fix is to judge `updated`
  by subject facts only.
- The list rows carry `depth` for the tree sort (section 5.3).
- The Textual keys: the list holds the focus so the screen's keys work, and `Tab` is the screen's own binding for the
  detail's links rather than the usual focus change.
