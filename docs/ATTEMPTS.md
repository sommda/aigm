# AIGM Attempts: Design

Status: **spec, not built**. Second of two prerequisites to the stakes feature ([STAKES.md](STAKES.md)); the first is
the clock ([TIME.md](TIME.md)), which this spec relies on. It decides what a failed action means: a bad try that can be
repeated at a price, or a task the character simply could not do. It also keeps a record of every failed attempt. It
adds **no new tool**: an attempt is declared in the die roll itself.

## 1. Goal

Today a failed roll is just narrated, and the next turn the player may roll the same lock again, as often as they like.
That removes the sting of failure. The rules:

1. **A failure is interpreted by the kind of action.** Picking a lock can be tried again, at a cost. Lying to someone
   cannot: the same story the second time gets "I liked your first story better".
2. **No retry is free.** Even in the earliest chapter a retry costs at least time (TIME.md), and often noise, wear or
   risk as well.
3. **The ruleset and the GM decide.** Which actions are repeatable, and whether a particular failure meant a bad moment
   or a task too hard for this character, is for the ruleset prompts and the GM. The server provides the record and a
   small number of firm rules.
4. **Every failed attempt is recorded as a fact**, whether or not it can be retried.
5. **The rules do not change with the chapter.** The stakes feature builds tension by other means: a costly failure
   takes time against a deadline, or alerts an enemy, or breaks a tool. A retry is no more or less allowed in chapter 3
   than in chapter 1 (section 7).
6. **The roll is the record.** The GM says what is being attempted in the roll it already makes, and the server finds
   out from the roll whether it failed, whether it may be tried at all, and what to write down.

### Non-goals

- Combat. Attack rolls, saves and damage are not attempts: a missed attack is simply a round that went badly.
- Trivial checks. Only a roll the GM marks as an attempt is recorded: a guarded door, a clue, a person's trust.
- Player-visible state of its own. The facts appear in the compendium as they would anyway; there is no new screen.
- Stopping a player from trying something. A closed attempt is made clear in the fiction; the player may still try
  something different.

## 2. Today

- `roll_dice` takes an expression and a narration. It has no difficulty, so it cannot tell success from failure; the GM
  reads the total and narrates. `social_check` does have a `dc` (except for the old editions' reaction rolls), and
  works out "success by 3" or "failure by 5" itself (`tools/social.py`).
- `social_check` also already refuses to roll in two cases and tells the GM to narrate the result with no dice: a motive
  held absolutely can **bar** the roll or make the words **succeed**. A closed attempt is the same shape of result.
- `social_check` allows one check per player message and person; a second try needs new words. Nothing else limits
  repeats, and nothing remembers a failure.
- Nothing is written down when a roll fails. The GM's prompt says to let the player "fail forward" and the ruleset files
  describe each edition's checks, but none say when a failure ends an approach.
- The clock does not move by an action's duration (TIME.md 2); with that spec it does, and that is what makes a retry
  cost something.

## 3. The two kinds of retry

Every kind of action has a **retry policy**:

| Policy | What a failure means | What a retry is |
|---|---|---|
| `costly` | A bad try. The task can be done. | Allowed, and it costs something each time |
| `once` | The task was beyond this character, or the story was heard | Not available, unless something changes |

There is no free policy. Both start with the time the try took, and `costly` adds to it.

### 3.1 Costly

A failed `costly` attempt always costs the time of the try (TIME.md 6). The GM adds whatever suits the fiction, and says
what it is **before the roll**, in the `failure` clause (section 6), so the stakes are plain when the dice fall:

- **Noise or alert**: the guards stir, the next patrol comes sooner. The GM records it the usual ways (a fact, a motive)
  in the same turn.
- **Wear or breakage**: a pick snaps, a lock jams, a rope frays. The means may be lost; the GM then closes the attempt
  until the party has new means.
- **Risk**: a fall, a trap, a wound.
- **Position**: a rival gains ground, an NPC is further irritated.

An attempt that has failed `costly` stays **open**: the next try is a retry, linked to the first. The GM may **close**
it at any failure when the fiction says the task is out of reach ("the mechanism is finer than anything Kit has
handled"). How many failures is too many is for the GM.

### 3.2 Once

A failed `once` attempt is **closed** for the same character on the same target. The player may try again only when
something changes: a new approach, a different character, new information, an ally's help, or time passing.

- The GM says in the narration that it is closed, in the fiction: "the steward's eyes cool; he has heard that tale".
- The attempt records what would reopen it: `reopens_if`, for the GM only (so a surprise is not spoiled). It has a
  default for each type, so a closed attempt always has a way back.
- A closed attempt can also be given a clock, `after_minutes`; the server reopens it when that much time has passed
  ("the guard's suspicion fades in a day").
- A closure applies by default to the one character (`scope: character`). The GM may close it to everyone
  (`scope: anyone`) when the failure came from the situation, not the character: the vault's mechanism is jammed.

The difference between "too hard" and "unlucky" must be clear from the story.

### 3.3 Which kind an action is

A table of **action types** sets the policy unless the GM says otherwise. The types are data in `aigm/attempts.py`,
tuned after play tests. `minutes` is the time of a try when the roll does not give one (TIME.md 6).

| Type | Policy | Minutes | Examples |
|---|---|---|---|
| `lock` | costly | 10 | Picking a lock, opening a puzzle box |
| `trap` | costly | 10 | Finding or disarming a trap, defusing a ward |
| `force` | costly | 5 | Breaking a door, lifting a portcullis, smashing a window |
| `climb` | costly | 15 | Climbing, swimming, crossing a ledge, a hard jump |
| `repair` | costly | 60 | Mending, building, forging, cooking something delicate |
| `treat` | costly | 10 | First aid, a poultice, tending a poisoned companion |
| `search` | once | 30 | Searching a room or an area by a given method |
| `lore` | once | 5 | Recalling what the character knows; identifying a thing |
| `appraise` | once | 10 | Valuing, authenticating, reading a forgery |
| `sneak` | once | 10 | Passing unseen, shadowing, hiding |
| `social` | once | 10 | Persuading, deceiving, intimidating, bargaining |
| `inquire` | once | 60 | Asking around, working a source, researching in a library |
| `other` | once | 10 | Anything else the GM records |

`other` is `once` because a failure of an unknown thing should not be assumed repeatable. A search is `once` because
looking in the same way finds nothing new, but a new method (the pry bar, a lantern, a second pair of eyes) is a new
approach. A `sneak` failure is `once` because the guard has already looked.

The ruleset prompts adjust the table (section 8): an edition that lets a skill be retried freely when nothing is at
stake says so, and the GM treats the type as `costly`. The GM may also override the policy of one attempt with `closes`.

## 4. The record

### 4.1 The attempt

A failed attempt is stored on the world (`World.attempts`) as:

```jsonc
{
  "id": "a004",
  "who": "Kit",
  "kind": "lock",
  "task": "pick the vault lock",
  "about": "e017",
  "status": "closed",
  "tries": 2,
  "chain": "a003",
  "scope": "character",
  "failure": "a pick snapped and the clatter woke the guard",
  "reopens_if": "Better picks, a locksmith's help, or the key",
  "reopens_at": { "day": 4, "hour": 9, "minute": 0 },
  "fact": "f0183",
  "turn": 41,
  "at": { "day": 3, "hour": 21, "minute": 10 }
}
```

- `status` is `open`, `closed` or `resolved` (the task was done in the end).
- `about` is the entity the attempt concerns: a place, a person, an item, a faction. It defaults to the place the party
  is in. The server resolves it as `establish` and `key_item` resolve names.
- `chain` joins the tries of one task: the first failure starts a chain and each retry adds to it (`tries`).
- `failure`, `reopens_if` and `reopens_at` are as in section 3. Only the GM sees `reopens_if` and `reopens_at`.

### 4.2 The fact

Whether the attempt is open or closed, the server records a fact about the target, `known`, `source: play`, aspect
`attempts` (a new aspect on every kind). The server writes it from the attempt, so the GM need not:

> Kit tried to pick the vault lock and failed; a pick snapped and the clatter woke the guard.

- It follows the usual fact rules (WORLD.md 2.1): one claim, names not pronouns, in-world, about 40 words at most. The
  `failure` clause is held to that length.
- It is the part of the record the player may read in the compendium, in the entry of the thing it is about.
- When the chain ends in success (`resolved`), the server supersedes its failure facts with one summary fact: "Kit
  opened the vault lock on the third try."
- Facts of a closed attempt stay; the story keeps them. The briefing shows a cut of them (section 5); `recall` shows
  all.

## 5. What the GM sees

The briefing gains an **Attempts** block, for the place the party is in, the people with them, and the things they hold
or are working on:

```
Attempts here:
- CLOSED: Kit's lockpicking of the vault lock (2 tries). Reopens if: better picks, a locksmith, or the key.
- OPEN: Mira's climb of the cliff (1 try; the rope frayed). A retry costs time and may break the rope.
- Closed, now open again: the guard's suspicion of Kit (a day has passed).
```

- A closed attempt is listed for the GM only, with its `reopens_if`. The briefing says: **do not roll a closed attempt
  again unless something has changed; narrate why it fails in a line, and let the player choose something new.**
- An open one is listed with its tries and its failure cost, so the GM prices a retry.
- The block is cut to what matters: the current place, the people present, items in hand, and the active quests' places,
  newest first, at most a handful of lines.
- Attempts whose `reopens_at` has passed are shown as open again, and the server marks them so.

## 6. Folding it into the roll

There is no `attempt` tool. `roll_dice` and `social_check` take an optional `attempt` that says what the roll is for.

```jsonc
{
  "expression": "1d20+7 # lockpicking",
  "narration": "Kit kneels at the vault lock, picks between her teeth, the guard's boots somewhere above.",
  "dc": 18,
  "minutes": 10,
  "attempt": {
    "who": "Kit",
    "kind": "lock",
    "task": "pick the vault lock",
    "about": "the vault door",
    "failure": "a pick snaps and the clatter wakes the guard"
  }
}
```

### 6.1 The fields

- `dc` (new on `roll_dice`): the number the roll must meet or beat. The GM commits to it before rolling, and it is never
  shown to the player. For the editions that roll under an ability, `dc_mode: "under"` makes the roll succeed when it is
  at or below `dc`. `social_check` already has `dc`.
- `attempt.who`: the party member (for `social_check`, the `character`).
- `attempt.kind`: one of the types of 3.3. For `social_check` it is `social`, and `attempt` can be left out entirely.
- `attempt.task`: three to twelve words, in the form "pick the vault lock".
- `attempt.about`: the entity the attempt concerns; the current place if left out. For `social_check` it is the
  `target`.
- `attempt.failure`: the clause that completes "...and failed; ___" for the fact, naming what failing costs or shows.
  Up to 25 words, in-world. It is the GM's promise of the stakes before the dice are thrown.
- Optional: `closes` (true or false) to override the type's policy; `reopens_if`; `after_minutes` for a closure with a
  clock; `scope` (`character` or `anyone`); and `changed`, the new approach or circumstance that reopens a closed
  attempt (6.2).
- `minutes`: as in TIME.md 4. If it is left out, an attempt takes its type's `minutes`, so a roll marked as an attempt
  never takes no time at all. A GM-given figure is used as given, but never less than one minute.

An `attempt` without a `dc` is refused: without one the server cannot tell what happened, and the GM is told to roll the
opposition first and use its total, or the passive figure for the task, as the `dc`. The GM gives the `dc` **before**
rolling. **Rolls that have no difficulty are not attempts and carry no `attempt`:** rolling a character's attribute
values, a random table, damage, hit points, initiative. They are unchanged. A reaction roll is the one attempt without a
`dc`, and its ruleset gives the failing total (6.3).

### 6.2 What the server does

1. **Before the dice: look up the record.** It finds an earlier unresolved attempt by the same character (or any, for
   `scope: anyone`), of the same type, on the same target.
   - **Closed and not reopened, and no `changed`:** nothing is rolled and no time passes. The result says, as the
     barred-motive result does: "No roll. This is closed: *reason*. Narrate the refusal in a line; the player may try
     something different." The narration the GM wrote is still shown, since it has already streamed.
   - **Closed, with `changed`:** the attempt is reopened, with the `changed` text kept as the reason, and the roll goes
     ahead as a retry. The briefing tells the GM to use `changed` only for a real difference.
   - **Open:** the roll goes ahead as a retry; `tries` will go up.
   - **None:** a first try.
2. **The roll and the time.** The dice are rolled as for any roll, and the clock moves by the attempt's minutes.
3. **The verdict.** The total is compared with `dc`: success, or failure by *n*.
   - **Failure:** the attempt is created or extended, set to the type's policy (or the GM's `closes`), the fact is
     written (4.2), and a `once` closure gets a default `reopens_if` for its type if the GM gave none. The result tells
     the GM what was recorded and what to do: if closed, narrate that it is closed and why; if open, narrate the failure
     with its cost and tell the player what a retry would risk.
   - **Success:** an open chain is `resolved`, and its facts are folded into one. With no chain, nothing is recorded;
     only a failure leaves a mark.
4. **Time and the player.** A closed result narrates in the fiction. The roll appears to the player as any roll does.

The chain is found by the server, so the GM never passes an id. A roll that carries no `attempt` is not recorded.

### 6.3 Social checks

`social_check` already knows the speaker, the target and the `dc`, so its attempt is implied: the type is `social`, the
target is the person, and only a `failure` clause is added. It already allows one check per message and person; the
attempt record is what makes "the same lie, later" a closed attempt (the person has heard it). Whether the new words are
a different approach is the GM's judgement (`changed`), and the quality rules of ROLEPLAY.md already say a repeated
argument is `weak`.

A **reaction roll** (the old editions, with no `dc`) is read on a table, so the ruleset data says which totals count as
a failed attempt: each reaction ruleset has a `reaction_fail`, the highest total that is a failure (on the usual 2d6
table a hostile or unfavourable reaction). The server compares the reaction total with it, as it compares other rolls
with `dc`, and records the failure, the fact and the closure the same way. A total above it is not recorded, and a later
success on the same chain resolves it. The GM still reads the table to narrate the person's actual reaction.

### 6.4 What it avoids

- A second round after the roll for a recording call. The roll result already contains the verdict and the record.
- A voided roll: the lookup happens before the dice, as `social_check`'s barred-motive case does.
- A forgotten recording after a failure: the server does it from the roll.

What it asks of the GM is a `dc` and a `failure` clause before it rolls. That is the GM stating the stakes up front,
which the narration was meant to do already.

## 7. Tension without chapter rules

Attempts behave the same in every chapter and in endless play. Nothing here reads the chapter. Stakes (STAKES.md)
gets its tension from the *consequences* the GM attaches to a failure:

- **Time.** Every try costs minutes (TIME.md), and a retry costs them again. Under a deadline that is the price. The
  briefing shows the clock and the deadline beside the Attempts block.
- **Alerts and rivals.** The GM names them in the `failure` clause ("the clatter wakes the guard") and makes the
  matching record in the same turn.
- **Wear.** A tool breaks, and the attempt closes until the party has another.
- **Position.** A rival gains ground, a person's patience wears thin.

A closed attempt always has a way back, because every type has a default `reopens_if` (a new approach, another
character, new information, help, or time). The plotter's quests therefore cannot be blocked by one failed roll;
STAKES.md decides when a quest's `fails_if` conditions end it, and attempts are one of the things that can feed those
conditions.

## 8. The rulesets

Whether a failure means "too hard" or "unlucky" is the ruleset's. Each ruleset gets a short file in its prompts (after
the rules, era and role play files) that does four things:

- maps its own skills and checks onto the types of 3.3 and names exceptions;
- states its retry rules where it has them (editions that allow a retry after a failed check when nothing is lost, or
  allow taking a safe result by spending time, or forbid a retry unless conditions change);
- says what it counts as a changed approach (a new tool, a new skill, a helper);
- says whether its checks are roll-over or roll-under, for `dc_mode`.

The base prompt carries the common reasoning in a few lines, the three questions the GM asks when it decides:

1. Did the failure show that the task is beyond this character, or was it a bad moment?
2. Does a retry cost something, such as noise, wear, a guard's patience?
3. How much does the clock matter now? The tighter the deadline, the more a retry costs.

## 9. Data

- `World.attempts: list[Attempt]` (the fields of 4.1), staged with the turn. Attempt ids are `a001` and up.
- `ASPECTS`: `attempts` on every kind. The compendium shows it as "Attempts" in the entity's entry.
- `Ruleset.reaction_fail`: for the five reaction rulesets (OD&D, Basic, BECMI, AD&D 1e and 2e), the highest total that
  counts as a failed reaction roll (6.3). A figure to be tuned in `aigm/rulesets.py`, with the other ruleset data.
- `roll_dice`: `dc`, `dc_mode`, `minutes` (TIME.md) and `attempt`. `social_check`: `failure`, `minutes`, `attempt`.
- A save format bump. Old saves have no attempts.
- The hidden-state debug view lists all attempts, including `reopens_if`, which no other view shows.
- No change to the HTTP API or to the dice event the clients receive; the facts reach the clients through the
  compendium.

## 10. Build steps

Needs the clock first (TIME.md 10, step 2: `minutes` on rolls and `pass_time`).

1. The model: `Attempt`, the ops, save and load, the `attempts` aspect, the type table in `aigm/attempts.py`.
2. `dc` and `dc_mode` on `roll_dice`, the verdict in the result, and the roll's minutes. Useful on its own.
3. The `attempt` object: validation, the lookup, the chain, the fact, the closed result, the time default.
4. `social_check`: the implied attempt and its `failure` clause.
5. The briefing block and the reopening clock.
6. Prompts: the roll tools' descriptions, the base reasoning, and the ruleset files (section 8).
7. A live check with the real GM: a lock, a lie, a search, a retry, a changed approach.

A **curator safety net** for a GM that forgot to mark a roll as an attempt is deferred until the playtests, as for key
items.

## 11. Left for later

- The curator noticing a failed attempt in the narration and recording it.
- Failures that change an NPC's motives automatically (a rebuffed person). Today the GM does it with `set_motive`.
- A per-character memory of what they have tried and failed at.
- Showing the player their closed attempts as a list. For now they read the facts in the compendium.

## 12. Open questions

None at the moment.
