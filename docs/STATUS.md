# AIGM Status Page and Character Sheets: Design

Status: decisions settled (section 10); building in the order given there. Built so far: steps (a), (b) and (c);
(d) remains.

This is the design for a player-facing **status page** (where the party is, who and what is there, how everyone is
doing) and one **character sheet** per player character, shown in a client screen that works like the
[compendium](COMPENDIUM.md): a tab for the overall status, then one tab per character.

## 1. Goal

- **Status tab.** Names and describes the current location. Lists the NPCs present, the key items there, and the
  connections to other places the party knows about. Ends with a table of everyone in the scene: party members, NPCs
  and, in combat, enemies. The columns fit the situation (in combat: HP and condition).
- **Character tabs.** A standard sheet for each player character: stats, defenses, skills, features, spells,
  inventory, coin, conditions, level and XP. The layout follows the ruleset and the class.
- **No LLM call to show any of it.** The location description is written ahead of time (or when first needed) and
  stored in the world as a fact. Opening the page reads memory only.
- Sheets exist for player characters only. NPCs and enemies appear in the status table, never as sheets.
- The server holds the data and the rules; the client only draws it, as with the compendium.

### Non-goals (v1)

- Editing from the client. The player does not change HP or inventory; the GM does, by playing.
- A rules engine. The server does not compute modifiers, attack bonuses or spell DCs. It stores what the sheet says.
- Grids, maps and token positions. Combat stays abstract, as `02_rules.md` already requires.
- Sheets for NPCs or foes. Their status-table row is a few fields, not a character.

## 2. What exists today

| Need | Today |
|---|---|
| Party | `campaign.party`: `name`, a free-text `sheet` and a `background`, written once by the GM at `begin_adventure` |
| Advancement | `GameState.heroes`: level, XP, classes per name, kept by the server (`award` tool) |
| Current place and who is there | `World.scene`: a location id and a list of entity ids; `set_scene` writes it |
| Place facts, connections | World facts by `aspect` (`approach`, `connections`, `inhabitants`, ...); `neighbors()` |
| HP, spell slots, gear, coin, conditions | **Nowhere.** The GM is told to keep track "in the terms of the ruleset", so they live only in the conversation |
| Combat | **Nowhere.** Initiative and wounds are narrated; no tool or state marks that a fight is on |
| Key items | **Nowhere.** There is no item entity, and no aspect for the things lying in a place |
| A place's description | **Nowhere.** Aspects describe a place piecemeal; nothing is a short "what you see" |

So two of the three parts are mostly reading existing data (the scene, the connections, the level). The rest needs
new state, and that is the real work: **structured character state** and **combat state**.

## 3. Structured character state

### 3.1 The sheet record

The free-text sheet stays (the GM reads it every turn through the campaign record). Beside it the server keeps a
**`Sheet`** per party member, with as little structure as will do. The model decides what a sheet for this ruleset
and class looks like; the server never knows what "Armor Class" or "spell slots" are.

- **`headline`**: one line, such as "Human Rogue 3".
- **`hp`** and **`max_hp`**: optional whole numbers. They exist only because the status table and the combat view
  need one comparable number. A ruleset with no hit points (or a character the model cannot read one for) leaves
  them out and the table shows a dash.
- **`conditions`**: a list of short strings.
- **`sections`**: an ordered list of `title` and `lines`, where `lines` is a list of plain strings. That is all.
  Abilities, defenses, skills, attacks, features, spells with their slots, equipment and coin are all just sections
  whose lines the model wrote ("STR 10 (+0)", "1st-level slots: 2/3", "Shortsword, 12 gp").

Nothing about a ruleset lives in the server: a new ruleset, or a homebrew class, needs no schema change, only the
model writing sensible sections. The client draws sections as titled lists, in order.

### 3.2 Where the structured sheet comes from

A **sheet pass** (a curator step, like the familiarity pass in [OPENING.md](OPENING.md)) turns each member's
free-text sheet into a `Sheet` at the end of Session 0, and again for any character added later. Input: the sheet
text, the ruleset's name, the level. Output: JSON matching a schema. The prompt gives the vitals and section rules
and tells the model to copy the sheet and invent nothing. Reasons for a pass over making the GM write structured
data in `begin_adventure`:

- The Session 0 GM already writes a full sheet and works well. Asking it to also write a nested schema makes the
  most delicate tool call in the game harder, and a small local model would fail it more often.
- A failed pass costs nothing the game needs: the sheet tab falls back to the free text, with the level and XP the
  server already has.
- The pass is repeatable (a debug backfill, as for the compendium) and testable with the scripted curator.

### 3.3 Keeping it current

The GM keeps HP and resources straight in the story but nothing records them. Two ways, and the design uses the
first:

1. **A new GM tool, `update_character`.** One call per change: a name, then any of `hp` (a number) or `hp_delta`,
   `max_hp`, `conditions_add` / `conditions_remove`, and `section` (a title and the full new list of lines, which
   replaces that section or adds it). So a spent spell slot, a drunk potion or new coin is a rewrite of the section
   it lives in, which the model does by reading the sheet it was given. It works on the turn's working copy like
   `establish` and `set_scene`, so a failed turn records nothing, and it is refused for a name that is not a party
   member. The prompt tells the GM to call it whenever it states a change ("You take 4 damage (HP 11/15)"), before
   the reply, like `set_scene`. The tool only changes server state; nothing is pushed to the client (section 7).
2. A curator reading the narration after the fact. Rejected: HP arithmetic and "which potion did they drink" are
   exactly what a post-hoc reader gets wrong, and a wrong HP bar is worse than none.

A server that has a sheet the GM never updates is no worse off than today, and the page then shows a **stale**
mark on a vital the GM has not touched for a long stretch only if we choose to (decision 6).

As built: the party's sheets are appended to the end of each request's world notes (at most 1,500 characters each),
so the GM can rewrite a section from what is there. Hit points are held between 0 and the maximum, so a ruleset that
counts below zero (negative hit points, death saves) records "0" and a condition or a line in a section for the rest.
In test mode, `hurt NAME N` and `heal NAME N` call the tool.

### 3.4 Level and XP

Already server state (`heroes`). The sheet's headline and the "Progress" row read them, so an `award` is reflected
with no GM call. Class names on the sheet that disagree with the recorded classes lose to the server.

## 4. Combat state

A small, explicit **encounter** record, set by a new GM tool, `set_combat`:

- `start`: a list of combatants, each with a `name`, a `side` (`foe` or `ally`), a `count` for a group (a pack of
  four wolves is one row, count 4), an optional `health` word, and `conditions`. The party is implied.
- `update`: change a combatant's `health`, `conditions` or `count`, or add or remove one.
- `end`: the encounter is over; the record is cleared.

It lives next to the scene (a field on `World.scene`'s sibling in `GameState`, saved with the game) and is
cleared by `end`, by a `set_scene` that moves the party, and when a new game begins.

**Foes show a health word, not numbers** (for now; a later setting may choose how much data is exposed). The player is
not told a monster's HP in the story, so the status page must not say it: `unhurt`, `scratched`, `bloodied`,
`near death`, `down`. The GM picks the word. That also means
nothing hidden can leak from this record, because the GM writes only what the player may see. Allies and party
members show real numbers.

If the GM never calls `set_combat`, the status page simply has no combat table. Nothing breaks.

## 5. The location description

A location needs a short "what you see here" paragraph, about 40-80 words, readable on its own.

- **A fact, not a field.** It is an ordinary world fact with aspect `overview` and `source` `generated` (an aspect
  added to `prompts/world/aspects/location.md`), so it is saved, deduplicated and superseded like any other. One
  active `overview` per place.
- **Written in advance.** The expand step that already fills in a location (`world/expand.md`) writes it with the
  rest of the place, and the opening bootstrap writes it for the starting area and its neighbours. The extract step
  also writes one when the GM establishes a new place. So by the time the party arrives, it is already stored.
- **As needed.** If the party reaches a place that has none, the status page shows the place's name and its other
  known facts, and the server asks for a curator pass in the background (the existing `pass_requested` path). The
  description appears on the next opening of the page. The page never waits on a model.
- **Disclosure.** The overview is written as what an arriving visitor can plainly see, so it is `known` when the
  party is in that place and `hidden` before. It is revealed by `set_scene` into the place (the same moment the
  scene changes), so it also appears in the compendium entry for the place. Nothing secret goes in it: the prompt
  forbids it, and a regex check rejects anything that matches a GM-only fact the way `independence_problem` already
  does for extracted facts.
- **Briefing.** The overview is left out of the GM's briefing: the GM narrates the scene itself, and a second
  version in the briefing would invite copying.

## 6. What the status tab shows

All of it is read from the world and the new records; nothing is generated at read time.

1. **Location.** Name, the chain of places that contain it ("The Docks, Port Veyra"), the overview paragraph, and
   the time (`Day 3, evening`, from `world.time`).
2. **Here.** People and groups the scene lists as present, with a line each (their first known fact), and the
   places inside this one that the party knows. Only `discovered` entities with a known fact appear, the same rule
   as the compendium, and it goes through `aigm/compendium.py` so a leak cannot come from a new route.
3. **Key items.** Known facts on this place with aspect `items` (added to the location aspects: notable objects
   lying here, such as "a barred cargo hatch" or "a ship's bell with no clapper"). No item entities in v1
   (decision 4).
4. **Ways out.** The places linked to this one that the party has discovered (`neighbors()`), each with its
   `connections` or `approach` fact when known, so "the Customs House, a short walk up Dock Street".
5. **Table.** One row per party member, NPC present and, in combat, foe and ally.

| Situation | Columns |
|---|---|
| Calm | Name, role (Party, or the NPC's first known fact, shortened), HP for party members, conditions |
| Combat | Name, side, HP or health word, conditions, and for the party: key resources (slots left) |

NPCs outside combat show no HP: the player has not been told it. Party rows always carry real numbers when a
`Sheet` exists, and show only the level when it does not.

## 7. Server API

All read-only, under the same session scoping as the compendium (`?session_id=`).

| Method and path | Returns |
|---|---|
| `GET /status` | The status page: `location`, `time`, `here`, `items`, `exits`, `table`, `combat` (null when no fight) |
| `GET /characters` | The party: name, headline, level, HP, conditions, for the tabs |
| `GET /characters/{name}` | One full sheet: vitals, sections, resources, coin, level/XP, free-text fallback |

The client fetches the tab it is showing each time the screen opens, a tab is selected or the player refreshes;
nothing is pushed, and no SSE event changes. The health check gains `"status": true` so a
client can tell whether a server offers the page, as it does for `compendium`.

A phase of Session 0 has no party yet, so the routes answer `409` there, as other adventure-only routes do.

## 8. Client

A `StatusScreen`, modal like `CompendiumScreen`, opened by `/status` (alias `/s`, and `/sheet NAME` to open a
character's tab) and a key binding (F7; Ctrl+T already toggles reasoning). Layout:

- **Tabs along the top:** `Status`, then one per character (their first names; `[` and `]` or Tab move between them,
  as in the compendium).
- **Status tab:** the sections of section 6 as scrolling text, with the table last. Tables are drawn with Rich, so
  they adapt to terminal width.
- **Character tab:** the sheet's sections in order as titled lists. Headline, HP and conditions at the top; a dim
  "free-text sheet" fallback when no structured sheet exists.
- **Model and screen split**, as for the compendium: `status_model.py` turns server JSON into lines of styled text
  with no Textual import (unit-tested), and `status_screen.py` is the thin widget.
- The screen fetches on open, on a tab change and on a refresh key; it never listens for events.

## 9. Persistence, tests, docs

- **Save format 8.** Adds `sheets` (name to `Sheet`) and `combat` (the encounter or null) to `GameState`. Formats
  1-7 stay readable; a missing key means no structured sheet and no fight. `Fact.aspect` values `overview` and
  `items` need no format change.
- **Backfill.** `POST /debug/sheets` runs the sheet pass for existing games (debug mode, as for `/debug/backfill`),
  and the overview for the current place and its neighbours.
- **Scripted curator and GM.** The scripted curator returns a deterministic `Sheet` from the sheet text, so `--test`
  mode and the test-suite exercise the full path, and the scripted GM calls `update_character` and `set_combat`.
- **Tests (server).** Sheet pass validation and fallback; `update_character` (hp clamps at 0 and at max, unknown
  member refused, conditions dedupe, working-copy rollback); `set_combat` (start/update/end, cleared on move);
  overview aspect (written by expand, revealed on arrival, never leaks a GM-only fact); the status route (calm,
  combat, no sheet, Session 0) and a leak test that a hidden entity or fact never appears in any response.
- **Tests (client).** Model: calm and combat tables, a wide and a narrow sheet, the fallback; screen: tabs, refresh.
- **Docs.** `API.md`, `CLIENT.md`, `BACKEND.md`, `WORLD.md` (the two aspects), and the README link.

## 10. Decisions

Settled, with the reasons in the sections above.

1. **A server-held `Sheet`** made by a curator pass and kept current by `update_character`. Minimal structure:
   a headline, optional HP, conditions, and sections of plain lines (3.1). The model shapes the sheet for the ruleset.
2. **Foes show a health word, never a number,** for now. A configurable level of exposure is future work.
3. **No item entities in v1;** key items are known facts with aspect `items` on the place.
4. **The overview is revealed on arrival** and so also appears in the place's compendium entry.
5. **No stale marks in v1.** If the GM forgets `update_character`, the page shows what it has.
6. **Pull only.** Like the compendium, the client asks the REST API for each tab when it opens (and when the player
   refreshes it) and the server never pushes status over SSE. GM tools change server state and nothing else, so
   the page is right whenever it is asked. The client does no work beyond drawing what it is given.
7. **Build order:** (a) the overview and the location half of the status tab, which needs no new tools; (b) the
   sheet pass and character tabs; (c) `update_character`; (d) combat and the table's combat columns. Each step
   ships working.

## 11. Risks

- **The GM not calling `update_character` or `set_combat`.** The most likely failure with small local models. The
  design degrades to "no live numbers", not to wrong ones, and the prompts will say when to call them. Testing with a
  real model is needed before this is trusted, as with the opening.
- **A sheet pass that gets a ruleset's terms wrong.** The free-text sheet is always shown as a fallback and the
  prompt says to copy, not invent.
- **An overview that contradicts the GM's narration of the same place.** The briefing leaves it out so the GM does
  not echo it; where they differ, the narration wins in play and the next curator pass can supersede the fact.
- **Prompt growth.** Two new tool descriptions and a short paragraph in the rules prompt. The tools are only offered in
  the adventure phase.
