# AIGM Stakes: Design

Status: **spec, not built**. Builds on the structured campaign ([STORY.md](STORY.md)), the key items
([KEY_ITEMS.md](KEY_ITEMS.md)) and the next tale ([NEXT_TALE.md](NEXT_TALE.md)). It makes failure matter: the game
today fails forward so well that nothing the player does can go wrong in the end. This feature lets the cost of
failure grow with the three chapters, up to a game that can be lost.

## 1. Goal

A player who succeeds should feel it because they could have failed. The stakes rise with the story:

| Chapter | Stakes | A failed quest | A lost key item | The party is wiped out | The game can be lost by |
|---|---|---|---|---|---|
| 1. Setting the stage | Low | Fail forward, with a small cost | Replaced by a new path | Rescued, with a small cost | Nothing: the GM steers back |
| 2. The road to the goal | Real | Recoverable, with a real cost | A recovery quest | Rescued, with a heavy price | Neglect, or an extremely foolish act |
| 3. The endgame | Final | Bad ending | Gone for good | Bad ending | Any bad choice, or running out of time |

The chapters differ in how likely a loss is. In chapter 2 it is **possible but unlikely**: it takes repeated defeats,
neglect or folly, and a party that plays carefully will not meet it. In chapter 3 it is **likely unless the player
chooses well**: the many ways to fail are there to be dodged.

Three rules hold in every chapter:

- **Danger is hinted, never stated.** The player learns the stakes from the fiction (omens, a frightened ally, a
  burned bridge), not from the GM saying "if you do this, the game ends".
- **Chapter 1 costs never block the story.** A cost may be gold, supplies, a day. It can never make the main path
  impossible. If a loss would, the narrative bends around it.
- **Total failure is for neglect and folly.** An honest attempt that goes badly never ends the game before chapter 3.

### Out of scope

- **Endless games have no stakes.** Failing a quest there only means the quest's reward is not earned. That is
  already how it works and nothing changes.
- **Non-retryable actions** (the lock that cannot be picked again). They need their own design. Section 12 notes what
  this one leaves ready for them.
- **Checkpoints / going back.** A lost game ends the adventure for now.

## 2. How failure is defined

Today a quest fails when the GM decides it can no longer be done. That gives the GM nothing to hold on to, so the
plan now says up front how each quest can fail. Three new optional fields on a milestone:

```jsonc
{
  "id": "m07",
  "fails_if": [
    "Vane burns the ledger before the party has copied it",
    "Sister Orla, the only one who can read it, is killed or turns against the party"
  ],
  "deadline": {
    "day": 6, "hour": 18,
    "cue": "the second sun's slow slide toward the Spire",
    "fixed": true
  },
  "ending": "end_ruin"
}
```

- `fails_if` is a **list** of plain sentences, each naming a different way the quest is lost. They are shown to the GM
  as tripwires. The GM reports `failed` when one happens, as it does now (STORY.md 8.1), and the curator checks for
  them too, the same backstop it already is for completion. A quest may have one, but the plotter is told to write
  several whenever the quest has more than one thing that can go wrong (an object that can be destroyed, a person who
  can be lost, a place that can be sealed, a rival who can get there first). Section 2.2 sets the numbers.
- `deadline` is a moment on the in-world clock (`World.time`, day and hour), and a `cue`: the sign in the world that
  shows how near it is. `fixed` marks a deadline that nothing in the story can move (a conjunction of the suns, a tide,
  a feast day) as against one that people set and can be delayed (a ritual, a caravan); it defaults to false. The server
  compares the clock to the deadline after every turn, so a time limit is a fact the server checks and not something the
  GM must remember. What happens when it passes depends on the chapter (section 3). How a deadline is stated to the
  player is the GM's craft, within the rules of section 8.
- `ending` names the plan's ending that follows if this quest fails in a chapter where failure ends the game
  (section 5). The plotter gives one to every chapter 3 milestone, so every failure there has a named result.

The plotter writes these. In chapter 1 they are rare. In chapter 2 about half the required quests carry some. In
chapter 3 every decisive step does. A lost key item that a quest `needs` (KEY_ITEMS.md 6) is also a failure of that
quest, with no `fails_if` needed.

### 2.2 How many ways to fail

| Chapter | `fails_if` per required quest | Dooms | Idea |
|---|---|---|---|
| 1 | 0 or 1 | none | A quest may go wrong, but rarely in a way that matters |
| 2 | 1 or 2 | 1 to 3 | A few pitfalls a careful party sees coming |
| 3 | 3 or more, 5 or more on the last quest | 3 to 6 | A gauntlet: many things to dodge, each one telling |

The last chapter is meant to feel dangerous. The final approach has many separate ways to lose, and the player gets
through by noticing and avoiding them, not by luck. The plotter is asked for conditions that are **different in kind**:
a person, an object, a place, a rival, a clock, a choice. Five versions of "the party dies" do not count. A condition
the player can see coming and act on is better than one that springs from nowhere, so each should have a hint the GM
can plant earlier (section 8).

### 2.1 Story-wide ways to lose

Some losses are not any one quest: leaving the area, doing nothing while the enemy's plan finishes, walking into the
boss's lair unprepared. The plan therefore gets a short list of **dooms**:

```jsonc
"dooms": [
  { "id": "d1", "chapters": [2, 3], "when": "The party abandons the vale for good", "ending": "end_ruin" },
  { "id": "d2", "chapters": [2, 3], "when": "Vane's ritual completes", "deadline": { "day": 20, "hour": 0 },
    "ending": "end_ruin" },
  { "id": "d3", "chapters": [3], "when": "The party breaks into the Vault without the warded key",
    "ending": "end_fall" }
]
```

- Chapter 2 has one to three dooms and each must be avoidable by any reasonably careful party. Ending the game in
  chapter 2 takes real work or real stupidity, and the plotter is told so: intentional neglect, abandoning the
  quest, rushing in unprepared against what the party knows. Failing a quest is not one of them.
- Chapter 3 has several (section 2.2), and its quests' own failures count as well.
- A doom is never listed in chapter 1. Fleeing the area there is handled by steering (section 4).
- The briefing shows the GM only the dooms of the current chapter, and only to the GM.

## 3. What the server does when something fails

One function, `story.failure_response(story, chapter, ...)`, returns what happens. Pure logic, no model, held as data
beside `LENGTHS`:

| Chapter | On a failed required quest | On a passed deadline | On a doom |
|---|---|---|---|
| 1 | Repair (STORY.md 8.2), plus a small `cost` | Never fails: the deadline moves, a time cost is recorded | Not used |
| 2 | Repair that must add a backup quest and a real `cost`; never ends the game | Fails the quest and repairs, unless it is a doom's deadline (then the game ends) | The game ends |
| 3 | The game ends | The game ends | The game ends |

"The game ends" means the server tells the GM, in the next briefing, to play out the quest's `ending` (or the doom's)
and call `end_story`. The GM gets the scene it is in to finish, but the server will not accept any further milestone as
`done` and, as with a stalled quest today, forces the ending after `AIGM_STORY_STALL_TURNS` player turns if the GM never
calls it. The GM may not choose a different ending to soften the result; it may name `end_custom` only for a failure
the plan did not foresee.

## 4. Chapter 1: low stakes, still some cost

- A failed required quest still triggers repair, now with a `cost` (section 6). The repair adds what keeps the story
  going, as today, including a new path when the party is wiped out or a key item is destroyed.
- A passed deadline moves instead of failing. The server records the lost time as a setback and the briefing tells the
  GM the world was delayed too, so the quest is still possible. Example: the party lost a day, so the caravan they were
  to catch is also late, because of the storm that held them.
- **Drift.** If the party tries to leave the area, the GM bends the narrative back: a storm closes the pass, a
  stranger's plea arrives, the road loops to the same fork. The briefing says so in chapter 1 whenever the active quest
  is tied to a place the party is leaving. The GM never says the party cannot go; the world just does not let them get
  far. (The Eldoria game where the player tried to flee is the model for this.)
- A total party defeat is not an ending: the party is found, taken in or released, minus something (section 7).

## 5. Chapter 2: failure costs, but is recoverable

- A required quest that fails gets a repair pass with two extra rules for the plotter: it must add a **backup quest**
  inside the existing world (STORY.md 6.4 still applies: no new regions or factions) and it must name the **cost**.
  The ledger burned? Then there is a copy somewhere, a mage who can restore it from ash, or another source for the
  same facts. Each is a quest, and the cost is real: the enemy is a step ahead, an ally is lost, the party is poorer.
- A backup quest is `required` and takes the failed quest's place in the chapter's count. It can itself fail; a second
  failure of the same line costs more and the plotter is told to make it harder.
- A passed quest deadline fails the quest and goes the same way. Only a doom's deadline ends the game.
- **Failing a quest in chapter 2 never ends the game.** There is always a backup path, even when it is a hard one.
  The game can be lost in chapter 2 only through a doom (2.1). The briefing lists the chapter's dooms to the GM and
  tells it to hint at them as the party draws near, and to end the game when one occurs. Running into the boss's lair
  unprepared after learning what is there is a doom the plotter would write.
- Leaving the area: if that is a doom, it ends the game. The player gets the epilogue and the shame of what followed.

## 6. Costs

A **cost** is one line the server records so it is not forgotten:

```jsonc
{ "turn": 52, "chapter": 2, "milestone": "m07", "kind": "resource",
  "text": "The party paid Sister Orla's debt: 80 gold and the healing draughts" }
```

- `kind` is `time`, `resource`, `ally`, `knowledge` or `position` (the enemy gains ground).
- The GM supplies the cost when it reports a failure: the `story.quests` entry in `set_scene` gains `cost` (one
  sentence). It is required for `failed` in chapters 1 and 2 and the call is refused without it. The plotter's repair
  also names one, which wins if the GM's is missing.
- Chapter 1 costs are limited to `time` and `resource`, and small. Chapter 2 may use any kind.
- Recent costs go in the briefing so the GM keeps the consequences alive in later scenes.
- A time cost moves the world clock (`elapsed_hours`) at the GM's next `set_scene`; the server tells the GM how much.

## 7. Death and defeat

### 7.1 What exists today

Death is not modelled. The party members are the player's characters (`party_names`); each has a sheet with optional
hit points and free-text conditions (`update_character`), and nothing says "dead". A character at 0 HP stays on the
status page and in the party, and the ruleset prompts ("0 HP means unconscious", death saves) are advice to the GM. The
player's characters are never world entities, so the compendium has no death state for them either. A party wipe has no
meaning to the server: the GM narrates it, and the next turn goes on as if nothing happened. This section adds a small
state for the dead and one tool for the defeat of the whole party. What a hit point or a death save *means* stays in the
ruleset, as now; the server records the result.

### 7.2 A character's fate

A sheet gains a **fate**:

| Fate | Meaning |
|---|---|
| none | Alive and with the party (the default; down, dying and unconscious stay conditions the GM sets) |
| dead | The GM has decided the character is dead; `died_turn` and the in-world time are kept |

A dead character also has **remains**: `carried` (the body travels with the party), `left` (left where it fell),
`buried` (laid to rest), or `lost` (nothing is left to recover: burned, disintegrated, swallowed). Until the GM sets
remains the death is **unresolved**.

`update_character` gains `fate` (`dead` or `revived`) and `remains`. Rules the server enforces:

- Marking a character dead needs a sheet that is not already dead, and records when.
- **The last living character cannot be marked dead in chapters 1 and 2.** The refusal says to use `defeat` (7.5). In
  chapter 3 it is accepted and ends the game (7.6).
- `revived` needs a dead character whose remains are not `lost`, and a `cost` (7.4).
- A dead character is out of the party's actions: the briefing lists them under "Fallen" and tells the GM not to use
  them. They stay on the status page, marked dead and sorted last, with their sheet and portrait. A character whose
  remains are `left`, `buried` or `lost` is no longer counted as travelling.
- The server writes a line in the story's `choices` log (STORY.md) for every death and revival, so the epilogue can
  mention who fell and what the party did.

### 7.3 When one character dies

It is not a failure of any quest. It is a **decision for the party**. The briefing, as long as the death is
unresolved, tells the GM:

- put the choice to the player in the fiction, within the next scene or two (not in the middle of the fight): leave
  the body, carry it, bury it, or try to bring the character back;
- say what each costs: a carried body slows the party and draws trouble, a body left behind may be gone or defiled when
  they return, a revival costs what 7.4 says;
- keep the in-world time since the death, which the server supplies (`died 3 days ago`), because many rulesets limit how
  long a body can be raised.

The remains are the player's choice, not the GM's. If the player ignores the question, the GM raises it again at the
next natural pause. After two scenes with no answer, the server treats a living party that has moved on as having
left the body.

### 7.4 Bringing someone back

Revival is possible but never free after chapter 1. The ruleset says *how* (a spell, a cleric's rite, a miracle); the
server decides *what it costs*, and requires the GM to say:

| Chapter | Revival |
|---|---|
| 1 | Easy to find (a temple, a travelling healer, a debt), with a small time or resource cost |
| 2 | Possible, with a real cost (7.4.1) and often a short quest of its own: a rare reagent, a distant priest, a favour |
| 3 | Possible, at a heavy cost, but it never undoes a failure that has already happened (7.6) |

#### 7.4.1 A chapter 2 revival

The cost is recorded as a section 6 cost, of a kind other than `time` alone. The GM may make it a side quest
(`required: false`) by saying so in the quest report, so the player can see it in the log and take the time to do it,
or decline. The compendium shows the character as dead with their remains. A character who is not revived in
chapter 2 is gone for the rest of the game, and the epilogue can say so.

### 7.5 When the whole party is defeated

A **defeat** is the moment no character can still act: everyone is dead, down, captured or otherwise out. The GM calls
a new tool, `defeat`. A party that is merely losing, or has retreated, is not defeated.

```jsonc
{
  "how": "taken",
  "aftermath": "The slavers take them to the Ashmoor pens. The party wakes in the dark, stripped of weapons.",
  "cost": { "kind": "resource", "text": "Weapons and the healing draughts are taken" },
  "elapsed_hours": 36
}
```

- `how` is `taken` (captured, bound, held), `left` (left for dead, found and tended), or `routed` (driven off and
  scattered; reunited later). The aftermath must be a position the party can act from, not "you all die".
- **Escape quest.** When `how` is `taken`, the party must earn its way out. The server asks the plotter for a short
  required quest in the same style as a repair (STORY.md 8.2), the **escape quest**: its brief says where the party is
  held, who holds them and what they have lost, and it completes when they are free. The GM narrates the captivity
  while the plan catches up, as it does for a chapter change. The escape quest is real: it can carry its own
  `fails_if` (a prisoner left behind) and its own `cost`. For `left` and `routed` no quest is added; waking up or
  regrouping is the scene.
- In chapter 1 the plotter also has **freedom to alter the world** for the escape: it may add a new place (the
  slavers' pens), a new person (a sympathetic guard) or a new faction, because chapter 1 has no "no major additions"
  limit (STORY.md 6.4). In chapter 2 the escape must use what the world already has: the holder is an existing
  faction or person, the prison an existing place or a detail inside one, and the way out something the party has met.
- **Chapter 1.** Always accepted. The cost is small and the hours are a few. Nothing stops the story, and the repair
  pass (STORY.md 8.2) makes sure the quest can still be done.
- **Chapter 2.** Always accepted, but `defeat` counts: `story.wipes` rises by one, and each wipe costs more than the
  last (section 7.5.1). The server sets a **minimum** for `elapsed_hours` from the wipe count and refuses a lesser
  figure, so the GM cannot soften the price. The clock moves by that many hours, and a doom's deadline may then be
  reached, except when the party is `taken` (7.5.2). The character whose fall triggered the defeat always lives,
  whatever the earlier dead.
- **Chapter 3.** A defeat is a bad ending. The server accepts `defeat` and tells the GM to play out the nearest
  failure ending with `end_story`, as in section 3.
- A party can never be all dead in chapter 1 or 2: the server refuses the last death (7.2) and the GM uses `defeat`
  instead, which spares the character who fell last. Only chapter 3 allows a party of the dead, and that is an ending.

#### 7.5.1 The price of the second wipe, and the third

| Chapter 2 wipe | Typical price | Minimum hours |
|---|---|---|
| First | Gear taken, or a day or two lost | 24 |
| Second | A companion lost or captured, a key item put out of reach | 72 |
| Third and later | A major ally or item gone for good, the enemy well ahead | 120 and 24 more each time |

The figures are data beside `LENGTHS`, tuned after a play test. Chapter 1 wipes are not counted and have no minimum.

#### 7.5.2 Capture never fails the game

Being captured must not itself cost the party the game, or capture would be an instant failure. When `how` is `taken`
the server protects every active deadline, quest and doom, hard or soft:

- **A deadline that people set** (`fixed` false) is **pushed back by the hours of captivity**. The briefing tells the GM
  why in the fiction: the enemy's plan was held up too (a missing component, the same storm, a rival's move), so the
  cue has not moved while the party was held. The extension is recorded as a cost of kind `time`, so the player sees it
  was a mercy and not a given.
- **A fixed deadline** cannot move, so the **captivity is shortened** instead. The server caps the hours of a capture so
  that at least a **reserve** remains before the deadline: enough for the escape quest and the way back. If the time
  left was already below the reserve, the escape is a scene and not a quest.
- The reserve is a share of the time that remained when the party was taken (a third, and never under 12 hours), and is
  data beside `LENGTHS`. It overrides the minimum hours of 7.5.1, which is a minimum for the price and not a promise.
- The escape quest is sized `small` and is built to be finished inside the reserve: the plotter is told the time it has.
- This protection applies to a capture only. Other defeats (`left`, `routed`) still cost their hours and, in
  chapter 2, may push the party into a doom as in 7.5.1. That is intended (see the next paragraph).
- It is a fairness rule, not a general softening. The game is meant to be hard but not cruel; a harsher setting where
  capture costs the deadline is for a later mode (section 12).

### 7.6 Chapter 3: death can be undone, failure cannot

Revival is possible in chapter 3, but it is the hardest to get and it never undoes a failure:

- A character who dies in chapter 3 may be brought back, at a heavy cost (section 6), and the quest goes on. The GM
  still puts the choice of what to do with the body to the player (7.3).
- **A failure that has happened stays.** If the death tripped a `fails_if`, ended a quest or made the last living
  character fall, the quest is `failed` and the ending is played out. Reviving the character afterwards does not
  reopen the quest, move the ending or give a second chance. The server enforces this: a milestone reported `failed`
  or a game that has reached its ending is never reopened by a revival.
- If the last living character is marked dead, the server accepts it and the briefing tells the GM to play the failure
  ending (section 3). The dead are not revived inside the ending; they are revived after it (7.8).
- Every death and revival in chapter 3 is written into the `choices` log, so a costly victory or a bitter one can follow
  from who survived.

### 7.7 Companions

**There are no replacement player characters.** Non-player allies are world entities, not party members, and are not
changed by this design except that a dead one shows as dead in the compendium (an existing `status`). A player whose
character is gone for good still has the rest of the party. If a single survivor remains, the GM may let a companion
from the story travel with them, but the party never gains a new playable character. A party with no living member is
the chapter 3 case above, or the refusal of the last death in chapters 1 and 2.

### 7.8 After a failure: the aftermath and the next tale

A failure is not the end of the party, even a chapter 3 failure. It is the end of the tale. The "debrief" is not the GM
stepping out of the fiction to explain; it is **time in the world**, with the people in it, after the quest has failed.

1. **The ending.** In chapter 3 the GM plays the failure ending and calls `end_story`, as in section 3, with an
   epilogue of what followed. The existing offer to keep playing in the same world (STORY.md 9) follows.
2. **The aftermath.** The party can walk the world and talk. The NPCs know what happened and react: the ally who is
   grieving or angry, the rival who gloats, the survivor who thanks them anyway, the elder who says what the omens had
   been. This is how the player works out what went wrong, and no one has to tell them. The briefing for these scenes
   carries the failure record (the quest or doom that failed, what the outcome lines say, the costs paid and the
   deaths) as things the world's people may know, so the GM voices them consistently. It reads from the story record
   (the `choices` log and the quest outcomes) and needs no new storage.
3. **The next tale.** The existing offer (NEXT_TALE.md 3.1) follows, with the same party. Every dead character comes
   back at the start of the new tale: the new Session 0 rewrites their sheets, so their `fate` is cleared and they carry
   what they had. The old tale's events, deaths included, are written into the world as lore (NEXT_TALE.md 3.5), so
   the characters can remember what happened.

The same applies, in smaller form, to a quest that fails in chapter 1 or 2: the people involved react to it in the
scenes that follow, and the cost is part of how they speak to the party. The story record already holds what they need.
A good ending gets the same aftermath. It is the chance to see what the party's choices made.

## 8. Hinting, and the hard deadlines

**Consequences are hinted, never stated.** The GM never tells the player "this will end the game" or "you would fail".
Foreshadow with the world: a rumour, a changed guard, a smell of smoke, a companion who will not go on. Dooms and
`fails_if` conditions are for the GM's judgement only and are never read out. No countdown appears in the app or the
terminal client.

**A hard deadline is the exception, and it is made clear again and again.** A *hard* deadline is one whose passing
ends the game: any chapter 3 deadline and any doom's deadline in chapter 2 or 3. How the limit is first stated is
up to the GM. After
that the briefing requires the GM to **work the clock into the narration of every scene** through the deadline's
`cue`, so the player never loses track of it. The model is a quest like The Dark Crystal, which must be finished
before a conjunction of the suns. The GM shows where the suns are and how close they have come, in every scene: the
shadow they throw, the colour of the light, an NPC glancing up. The player may not know what happens when they meet,
but they will never be in doubt that time is running out.

- The server puts a line in the briefing every turn for each hard deadline: the cue, the fraction of time used
  (`~60% of the time is gone`) and the instruction to include a mention in this turn's narration. The GM does not have
  to compute anything from the clock.
- The mention grows with the fraction used: a passing detail early, a comment from a companion in the middle, an urgent
  line when little time is left. In the last tenth the GM says plainly how short the time is.
- **Chapter 2 is included.** A doom with a deadline (the ritual completes on day 20) is a hard deadline from the start
  of chapter 2, and the cue rule applies at once. That is only fair: the player must be able to see the time running
  out. So the plotter must plan such a doom to be learned early, and chapter 1's revelation quest is where the party
  finds out. The GM states the limit in the first scenes of chapter 2 at the latest, and the cue appears every scene
  from then on.
- Soft deadlines (chapters 1 and 2 quest deadlines, which repair when missed) get the lighter treatment: one hint in a
  scene at about half the time, a plain one at about three-quarters.
- A rescue or any other time cost that moves the clock is narrated, so the player sees why the cue has moved.

## 9. Data

- `Milestone`: `fails_if: list[str]`, `ending: str | None` and `deadline: Deadline | None` (a `WorldTime`, a `cue` and
  `fixed`).
- `Story`: `dooms: list[Doom]`, `costs: list[Cost]`, `wipes: int`.
- `Sheet`: `fate: str | None`, `remains: str | None`, `died_turn: int | None`, `died_at: WorldTime | None`.
- A milestone's `outcome` already records what happened. `failed` milestones also store `cost` (kept in `costs`).
- Save format bumps (old saves load with no `fails_if`, no dooms and no costs, so they behave as before).
- API: the `story` section of `/status` gains nothing the player may see. The hidden-state debug view lists dooms,
  deadlines, costs and the wipe count. The compendium shows nothing new.

## 10. The tools and prompts

- **The plotter** (`prompts/world/plot.md`) writes `fails_if`, `deadline`, `ending`, and the dooms, by chapter as in
  sections 2 and 3. The repair prompt gets the cost and backup-quest rules for chapter 2.
- **`set_scene`** `story.quests` gains `cost`. A failed report in chapter 3 is accepted as it is and the result tells
  the GM to play out the ending.
- **`update_character`** gains `fate` (`dead`, `revived`), `remains` and `cost`, with the checks of section 7.2.
- **`defeat`** (new): `how`, `aftermath`, `cost`, `elapsed_hours`, as in section 7.5. It records the wipe, moves the
  clock and in chapter 3 tells the GM to end the game.
- **`end_story`**: in chapter 2 a failure ending is accepted only when it names a doom the briefing lists; in chapter 3
  any failure ending is accepted.
- **The turn loop**: after each turn the server checks every active deadline and doom against the clock. A hit becomes a
  forced report and a briefing line. This is `story.due_failures(story, world)`: pure, and tested without a model.
- **The briefing** gains a "Fallen" block (who is dead, when, where the remains are, what the choices cost) and a
  "Stakes" block: the chapter's stakes in a sentence, active `fails_if`s, deadlines with the
  fraction used, recent costs, the doom list for the GM only, and the hinting rules (section 8).
- **Prompts** `03_style.md` ("let them fail forward") is made chapter-aware: it keeps that rule for chapter 1 and
  in endless play, and points to the Stakes block otherwise.

## 11. Build steps

1. Data: the fields, `failure_response`, `due_failures`, save format, tests. No behaviour change yet.
2. Costs: the `cost` field on quest reports, the briefing line, the clock move.
3. Chapter 1 and 2 failure: repair rules, backup quests, drift, rescue prices.
4. Chapter 3: ending on failure, forced `end_story`, the dooms.
5. Death: the `fate` and `remains` fields, the status page, the briefing block, revival costs (section 7.2 to 7.4).
6. Defeat: the `defeat` tool, the wipe count and the price table (section 7.5), the escape quest, chapter 3 handling.
   The next-tale link (sections 7.6 and 7.8) lands with the next-tale build (NEXT_TALE.md 6), not before it.
7. Plotter and prompts: `fails_if` lists, `deadline` and `cue`, `ending`, dooms; the hinting rules.
8. Live check with the real plotter and GM (a short game), then playtests.

## 12. Left for later

- **Non-retryable actions.** This design gives a place to record "the lock is jammed" (a world fact plus a cost) but
  does not decide how the GM stops a retry. That is its own discussion.
- **A cruel mode.** A harsher setting for players who want it: capture costs the deadline, revival is rarer, and
  failures are less forgiving than this design.
- **Checkpoints.** A saved point to return to after a lost game. Saves already exist; the rest is UI and rules.
- **Costs the player can spend or avoid**, such as insurance or a safer route chosen up front.

## 13. Open questions

None at the moment.
