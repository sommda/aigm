# AIGM Next Tale: Rolling a Finished Game into a New One

Status: **proposed**. Related: [STORY.md](STORY.md) (endings), [OPENING.md](OPENING.md) (what the adventure's start
builds), [PROGRESSION.md](PROGRESSION.md) (levels), [WORLD.md](WORLD.md), [STATUS.md](STATUS.md) (sheets).

## 1. Goal

When a structured story ends, the player is offered, explicitly, a way to carry on: a **new tale** in the same world
with the same characters. It begins with a new Session 0 that starts from what the game has become, and ends, as
always, in chapter 1 of a new story.

In the new Session 0:

- The ruleset stays as it is.
- The characters stay, with their levels, XP and gear as they now are.
- The world stays, with what the party discovered and did.
- The player picks a new campaign length (or endless play).
- The player may move the starting place, and may let time pass before the new tale opens.

### Non-goals (first cut)

- Changing the ruleset, or swapping characters in or out (the party can be edited by hand in Session 0, because the
  GM rewrites the sheets anyway, but nothing is built for it).
- Going back to the finished game. Saves are the way to keep it.
- Anything that needs the client to hear about it from the server: it is a pull flow (section 5).

## 2. Today

- A story ends with `end_story`: `chapter` becomes 4 and the ending and epilogue are stored. The GM is told to offer to
  keep playing "as an endless game" (STORY.md 9). Play continues in the same phase with no story tracked.
- `POST /chat/new` is the only way back to Session 0, and it throws everything away.
- A world can only be seeded from Session 0's campaign record. `begin_adventure` replaces the history, then the
  curator's `seed` builds the world from nothing, writes sheets and plans the story.
- `GameState.from_dict` rejects a Session 0 save that has a world, a story or a campaign.

## 3. Design

### 3.1 The offer

A game is **finished** when `story.ended` is true (an ending was reached, including a party defeat). The server says
so in the data it already gives (`GET /chat/history`'s `story` block has `ended`, and a new `can_continue` flag
says the new tale is possible). The client:

- shows a one-time notice when it sees `ended` turn true: "The tale is told. /next starts a new one with the same
  party and world; or keep playing here."
- adds the command `/next` (alias `/newtale`), which asks the player to confirm (it is a one-way move for this game;
  save first) and calls `POST /chat/next`.

The GM's closing message already offers to keep playing; its text gains a second offer. The player's choice is the
command, never a tool call by the GM (the player decides, and the client stays dumb).

### 3.2 `POST /chat/next`

Allowed only when the game is finished (409 otherwise, and 409 during a turn). It builds a **carry-over** and puts the
game back into Session 0:

- `phase` becomes `session_zero`. `ruleset` stays. `structure` and `story` reset (the structure is asked again).
- `world`, `heroes`, `compendium` and `campaign` are **kept** (the campaign becomes the *previous* record, see 3.3).
- `sheets` are kept for the GM's reference but rewritten when the new tale begins.
- The old tale is **archived**: `tales` is a new list of `{title, length, ending, epilogue, turns}` that grows each
  time. It is shown to the GM in Session 0 and in the briefing afterwards.
- The message history is replaced by one carry-over note (section 3.3). The old transcript is not kept in the live
  history. (The server's history store has its own rules, see [HISTORY.md](HISTORY.md); this adds none.)
- The response is like `POST /chat/new`'s: the new phase and the counts, so the client reloads its transcript.

The state invariant ("a Session 0 save has no world, story or campaign") becomes "a Session 0 save has no story; it may
have a world and a campaign only when `tales` is not empty".

### 3.3 The new Session 0

A different system prompt part (`system/session_zero/05_next_tale.md`), used when `tales` is not empty. The GM:

- is handed a **carry-over note** (a message, like the campaign record): the setting, the ruleset, each character's
  current sheet and level (from the sheet and `heroes`), the last tale's ending and epilogue, the places the party has
  been, the people and groups they know, and the current day and place. The world notes the briefing builds are
  included too, so the GM does not have to recall.
- does not rebuild the party or the setting; it asks what is **new**: the length (`set_structure`, as before), whether
  to start where the party is or somewhere else already in the world (or a new place), and how long to let pass
  ("a few days", "the winter", "a year", or nothing), and offers brief interludes for what the characters did meanwhile.
- finishes as before: summary, explicit "ready?", then `begin_adventure`.

`begin_adventure` is unchanged in shape (setting, opening, level, party with sheets and backgrounds, notes) with these
differences when `tales` is not empty:

- `setting` may be short ("as before") and is kept as is if so (the previous one is used); it may also add to it.
- The party must be the same names unless the player edited it. The GM rewrites each full sheet with the levels and
  gear they now have, and a short `background` that includes the last tale.
- New optional argument `elapsed_hours` (default 0): time to pass before the new tale opens.
- New optional argument `opening_place`: the name of a place already recorded in the world, where the party starts. If
  absent, the curator resolves the opening text's place as usual.

### 3.4 Beginning the next tale

The history is replaced as now (the carry-over's campaign record). The world seeding differs:

- **Skipped:** the bootstrap (it builds a world from nothing) and the familiarity pass (what the characters know is
  already there; new knowledge arrives as play goes on).
- **Run:** a smaller "continue" pass: put the party at the opening place (create it if it is new, with a parent), move
  the clock on by `elapsed_hours`, and refresh the opening overview for that place. Things that would plausibly change
  with the time (an optional list the curator proposes) are not applied automatically in the first cut.
- **Run:** the sheet step (sheets are rewritten from the new free text), and the plot step, now given the existing
  world, so that chapter 1's "wide open" rule adds to a world that already has places and people. The plotter is
  told to make the goal a **new** one and to reuse existing places and people where that makes sense.
- Heroes keep their levels and XP; `start_level` becomes the party's average level now, and the plot's
  `party_level` begins there.
- The compendium keeps what the player has read.

### 3.5 What the GM knows about the last tale

The briefing gains a short, stable paragraph: one line per archived tale (its goal, ending and epilogue), so the GM can
refer back to what happened. Facts in the world already hold the rest.

## 4. Edge cases

- A player who never uses `/next` keeps today's behaviour exactly.
- A party defeat: `end_story` with `party_defeated` also ends the story. The new tale is offered but the GM, in the
  new Session 0, is told that the party fell, and that the player may revive, replace or retire characters.
- An endless game never finishes, so it never has the offer. (Rolling over an endless game is out of scope.)
- A failed `begin_adventure` in the new Session 0 leaves the carry-over untouched, like today.
- A save made between `/chat/next` and `begin_adventure` is a Session 0 save with a world; format 9 reads it. Older
  saves have no `tales` and read as today.
- Going `/next` twice: each tale appends to `tales`; the note lists them all, newest last.

## 5. API sketch

| Piece | Change |
| --- | --- |
| `GET /chat/history` | `story` gains `can_continue`; the top level gains `tales` (a count) |
| `POST /chat/next` | New. 409 unless the story has ended. Returns what `POST /chat/new` returns, plus `tales` |
| Save format | 9: `tales`; Session 0 saves may carry a world and campaign when `tales` is not empty |
| Tools | `begin_adventure` gains `elapsed_hours` and `opening_place` (optional) |
| Client | The notice on `ended`; `/next`; the status line shows "Session 0" as usual |

## 6. Build order

1. **State and route:** `tales`, the relaxed invariant, `POST /chat/next`, the carry-over note, format 9, tests.
2. **The new Session 0:** the system prompt part, the `begin_adventure` changes, the scripted GM path for `--test`.
3. **Beginning the next tale:** the continue pass, the plot step given an existing world, the clock, tests.
4. **Client:** the notice, `/next`, the confirmation, docs.

## 7. Risks

- The plot step with an existing world is new ground for the plotter. It may reuse too little or invent contradictions.
- The sheets a character has are only as current as the GM kept them. Until `update_character` exists (STATUS.md 3.3),
  the free-text sheet may be stale in HP and gear; the new Session 0 has the GM rewrite it, which helps.
- Long gaps change the world (people age, places change). The first cut only moves the clock.

## 8. Decisions to confirm

1. **Offer by command, not by tool.** The client shows a notice and `/next`, so nothing relies on a pushed event.
   Recommended.
2. **The old transcript is dropped** from the live history (it can still be saved before rolling over); only the
   `tales` summary and the world remain. Recommended.
3. **Heroes keep levels and XP; sheets are rewritten** by the GM in Session 0, then re-structured by the sheet step.
   Recommended.
4. **Time passing only moves the clock** in this cut; no automatic changes to the world. Recommended.
5. **A party defeat also offers the new tale.** Recommended, with the GM handling the dead in Session 0.
