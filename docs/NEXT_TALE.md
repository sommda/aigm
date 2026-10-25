# AIGM Next Tale: Rolling a Finished Game into a New One

Status: **agreed in outline** (section 8); not built.
Related: [STORY.md](STORY.md) (endings), [OPENING.md](OPENING.md) (what the adventure's start
builds), [PROGRESSION.md](PROGRESSION.md) (levels), [WORLD.md](WORLD.md), [STATUS.md](STATUS.md) (sheets).

## 1. Goal

When a structured story ends, the player is offered, explicitly, a way to carry on: a **new tale** in the same world
with the same characters. It begins with a new Session 0 that starts from what the game has become, and ends, as
always, in chapter 1 of a new story.

In the new Session 0:

- The ruleset stays as it is.
- The characters stay, with their levels, XP and gear as they now are.
- The world stays, with what the party discovered and did. The old tale's events are written into it as lore, so
  nothing the characters did is lost (section 3.5).
- The player picks a new campaign length (or endless play).
- The player may move the starting place, and may let time pass before the new tale opens: a couple of weeks, or
  centuries. The world changes to match (section 3.6).

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
- `world`, `heroes`, `compendium` and `campaign` are **kept** (the campaign is the *previous* record, see 3.3).
- `sheets` are kept for the GM's reference but rewritten when the new tale begins.
- The old tale is **archived**: `tales` is a new list of `{title, length, ending, epilogue, turns}` that grows each
  time. It is shown to the GM in Session 0 and in the briefing afterwards.
- The **chronicle** (section 3.5) runs first and turns the old transcript into lore. Only when it has succeeded is the
  message history replaced by one carry-over note (section 3.3), so a failure leaves the finished game as it was.
- The verbatim transcript is then dropped from the live history. (Saving before `/next` keeps it, and the server's
  history store has its own rules, see [HISTORY.md](HISTORY.md); this adds none.)
- The response is like `POST /chat/new`'s: the new phase and the counts, so the client reloads its transcript. The
  chronicle can take a while, so the route streams `status` events like a turn does, or the client waits on the
  request with the "Preparing" status line (decided when building; same pull rule either way).

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
- **Run, in this order:**
  1. The **passing of time** (3.6), when `elapsed_hours` is more than 0.
  2. A small "continue" step: put the party at the opening place (create it if it is new, with a parent), and refresh
     that place's overview so it describes the place as it is *now*, after the time that passed.
  3. The sheet step (sheets are rewritten from the new free text).
  4. The plot step, now given the existing world, so that chapter 1's "wide open" rule adds to a world that already
     has places and people. The plotter is told to make the goal a **new** one, to reuse existing places and people
     where that makes sense, and to treat the chronicle and the last tale's ending as history it builds on.
- Heroes keep their levels and XP; `start_level` becomes the party's average level now, and the plot's
  `party_level` begins there.
- The compendium keeps what the player has read, and the chronicle's lore arrives in it as unread entries.

### 3.5 The chronicle: the old tale becomes lore

Dropping the transcript must not lose what the characters did. Before the history is replaced, the curator writes the
tale into the world. The pieces already exist (the turn digests, the extract step); this adds one new step.

1. **Catch up.** Every turn not yet digested is digested now (the digest step), and any turn the extract step has not
   yet seen is extracted, exactly as the periodic passes do. After this, the world holds what the live passes would
   have recorded and every turn has a digest.
2. **Chronicle.** A new curator step, `chronicle`, reads the digests in order (in chunks if they are many), the story
   plan's goal, `choices`, quest outcomes and ending, and the epilogue. It writes:
   - A **concept entity for the tale** ("The Tale of the Vault" or whatever the plot calls it) with `known` facts
     naming the party members, in order: what they set out to do, the turning points, what they chose, and how it ended.
     Aspect `history`. These are the only world facts that name the player characters, because here they are
     historical figures; they are written in the third person and in-world ("Toby and Mira closed the sluice gate").
   - Facts on the **places, people and groups** the tale touched, for what the party changed there (a village saved, a
     ruler dead, a faction broken), superseding what is no longer true. This is where "so none of the character's
     actions are lost" is delivered: each deed lands on the thing it affected as well as in the tale's own account.
   - One short fact per **party member** on the tale entity ("Mira lost her left hand to the Vault's warden"), because
     scars and reputation carry into the next tale. (The characters stay out of the world as entities, as before.)
3. **Archive.** The tale's title, ending, epilogue and turn count are appended to `tales`.

The digests themselves stay in the world (they are the finest-grained record), and the briefing can reach the tale
entity and its facts like any others. If the chronicle fails, `/chat/next` fails and nothing has changed.

### 3.6 The passing of time

When the player lets time pass before the new tale, the world changes to match. The gap can be small or enormous, and
a long one (the party slept for centuries) is a chance for real depth, so this is a real step, not just a clock move.

A new curator step, `advance`, is given: the world (places, people, groups, their active facts), the chronicle, the
elapsed time in plain words (and in hours), the ending and epilogue, and what the GM said about the party's own state
in the interval (asleep, travelling, resting, ruling a keep...). It returns ordinary world ops:

- **Superseded and new facts** about existing entities: who has died, aged, risen, fallen; what was built or ruined;
  which faction won; what became of the party's allies and enemies, the places they saved or razed.
- **New entities**: descendants, successors, new rulers, new factions, new settlements, ruins of old ones, legends
  about the party's deeds (these arrive as `concept` entities, with a mix of true and garbled facts).
- **The party's own changes**: the GM, in Session 0, decides what the interval does to the characters (they age, or
  they do not, as the story says) and writes it into the sheets and backgrounds. The `advance` step does not touch the
  party; it only receives the GM's account.
- The **clock** moves on by the elapsed hours.

Scale decides the shape of the work:

| Gap | Pass |
| --- | --- |
| Under about a month | One light pass: rumors, small changes, one or two consequences of the tale |
| Months to a few years | One full pass over the entities the tale touched and their neighbours |
| Decades to centuries | Stepped: one pass per era (a decade, then a century...), each seeing the last one's result |

Stepping keeps a long gap coherent (the third century builds on the second) and bounds each model call. The stepped
passes report progress as `status` events. Each step's new and changed facts are `hidden` unless the carry-over note
says the characters know them (a legend that is common knowledge is `known`; the fate of a distant kingdom is not).
The GM's briefing for Session 0 and for the first scene sees the result like any other world content.

A long gap also changes **what the characters know**: the new tale's opening overview and the first scene must make
the changes plain (the party wakes in a land that is not the one they left), and the GM's Session 0 prompt tells it
to show the player a short account of what changed before asking for the opening. No cap on the gap is built in;
the cost of the stepped passes is the limit, and Session 0 warns the player about long ones.

### 3.7 What the GM knows about the last tale

The briefing gains a short, stable paragraph: one line per archived tale (its goal, ending and epilogue), so the GM can
refer back to what happened. The tale entity and the facts it holds carry the rest, found like any other lore.

## 4. Edge cases

- A player who never uses `/next` keeps today's behaviour exactly.
- **A party defeat** also offers the new tale. The carry-over note says how the tale ended. In Session 0 the GM must
  decide, with the player, how the characters come back, and it is told to make the explanation fit the ending: a
  rescue, a resurrection with a price, a long recovery, a different set of survivors, a descendant or an apprentice
  taking up the name. It then rewrites the sheets (new HP, lost gear, a cost) like any change of circumstance. Time
  passing (3.6) is the usual tool here.
- An endless game never finishes, so it never has the offer. (Rolling over an endless game is out of scope.)
- A failed `begin_adventure` in the new Session 0 leaves the carry-over untouched, like today. A failure in the
  time-passing or plot steps rolls the beginning back, so the game stays in Session 0 and the player can retry.
- A save made between `/chat/next` and `begin_adventure` is a Session 0 save with a world; format 9 reads it. Older
  saves have no `tales` and read as today.
- Going `/next` twice: each tale appends to `tales`; the note lists them all, newest last.
- The chronicle for a very long tale must not exceed the model's input: it works in chunks and carries a running
  account, like the digest step's batching.

## 5. API sketch

| Piece | Change |
| --- | --- |
| `GET /chat/history` | `story` gains `can_continue`; the top level gains `tales` (a count) |
| `POST /chat/next` | New. 409 unless the story has ended. Runs the chronicle; returns what `POST /chat/new` returns, plus `tales` |
| Save format | 9: `tales`; Session 0 saves may carry a world and campaign when `tales` is not empty |
| Tools | `begin_adventure` gains `elapsed_hours` and `opening_place` (optional), and `elapsed` (the gap in words) |
| Curator | New steps `chronicle` and `advance`; both optional like `plot` and `digest` (a world with no curator cannot roll over) |
| Client | The notice on `ended`; `/next`; a wait with status text during the chronicle and the passing of time |

## 6. Build order

1. **State and route:** `tales`, the relaxed invariant, `POST /chat/next`, the carry-over note (without lore), format 9,
   tests. The old transcript is dropped only once step 2 exists, so this step keeps it.
2. **The chronicle:** catch-up, the `chronicle` step, the tale entity and the facts, the archive, tests. The route now
   replaces the history.
3. **The new Session 0:** the system prompt part, the `begin_adventure` changes, the scripted GM path for `--test`.
4. **Beginning the next tale:** the continue step, the plot step given an existing world, tests.
5. **The passing of time:** the `advance` step, stepping, the clock, tests.
6. **Client:** the notice, `/next`, the confirmation, the waits, docs.

## 7. Risks

- The plot step with an existing world is new ground for the plotter. It may reuse too little or invent contradictions.
- The chronicle is only as good as the digests. A digest that dropped a deed drops it from the lore. The catch-up
  step helps by digesting what was not yet digested, but the digest prompt's rules are what decide the detail.
- `advance` over centuries can invent a world that no longer feels like the one the player knew. Stepping and the
  "keep what the tale changed" input are the guard; the player sees the account in Session 0 and can say no.
- Sheets are only as current as the GM kept them. Until `update_character` exists (STATUS.md 3.3), HP and gear may be
  stale; the new Session 0 has the GM rewrite them, which helps.
- Cost: a long tale plus a long gap makes many model calls.
  The Session 0 warning and the status text are the mitigation.

## 8. Decisions

Settled by the review:

1. **Offer by command, not by tool.** The client shows a notice and `/next`; nothing is pushed.
2. **The old transcript is dropped, but only after it is processed into lore** (3.5), so the characters' actions
   stay part of the world.
3. **Heroes keep levels and XP; sheets are rewritten** by the GM in Session 0, then re-structured by the sheet step.
4. **Time passing changes the world** (3.6), from a couple of weeks to centuries, and the GM can use the gap to
   explain a magical sleep, a long recovery and the like.
5. **A party defeat also offers the new tale**, with the GM explaining how the characters come back (section 4).
