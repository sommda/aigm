# AIGM Role Play: Design

Status: **proposed**; build steps 1 to 3 (section 14) are built, the rest is not. This builds on [WORLD.md](WORLD.md)
(entities, facts, disclosure, the briefing, the curator), [RULESETS.md](RULESETS.md) (the edition catalog and
prompts) and [BACKEND.md](BACKEND.md) (tools, the turn loop). Section 12 lists the decisions to confirm before
building.

## 1. Goal

Make talking to people a game of its own, not a skill roll with a flavor sentence. Three parts:

1. **The player must roleplay.** "I bluff the guard" is an intention, not a bluff. Before a social skill is rolled, the
   player has to type what the character actually says.
2. **Good roleplay is rewarded,** in the currency of the chosen ruleset: advantage in 5e, a circumstance bonus in
   Pathfinder 2e, a better reaction roll in B/X. Bad roleplay is not punished beyond the plain fact that it does not
   help.
3. **People want things.** Every NPC who matters has hidden motives, some lasting (underlying) and some that only apply
   in the current scene. Motives decide which words land, how hard a check is, and sometimes whether a roll is allowed
   at all. The player never reads a motive. They see tells, and they work it out.

The three parts depend on each other. Rewards need a judge, and the judge needs something to judge the words against;
that something is the NPC's motives. Without motives "good roleplay" collapses into "long and flowery".

### Non-goals (v1)

- Non-social actions ("describe how you search the room"). The boon mechanism in section 5 would carry over, but the
  first cut is talking to NPCs.
- Motives for the player's own characters. Those belong to the player. (Their sheet traits are used in section 6.)
- Faction-level motives as a separate record. A faction's goals are already facts (WORLD.md 2.2); an NPC's motive can
  cite them.
- Voice input, grading prose quality, or any model call just to score the player's words. The GM judges, in the turn it
  is already running.

## 2. Principles

- **Judge the idea, not the prose.** A terse "Tell the captain it's about the Harrow shipment" beats three paragraphs of
  flourish. Never reward length, never punish a short or plain-spoken player.
- **The server enforces, the GM judges.** What can be checked mechanically (the words exist, one check per utterance,
  the ruleset's reward table, a motive that forbids a roll) is checked by the server. What needs taste (is this
  convincing to this person?) is the GM's call, made on a small fixed scale so the server can map it.
- **Hidden means hidden.** Motives are GM-only state, like hidden facts. They reach the player as narrated tells and
  as facts the player has earned, through the machinery that already moves facts from hidden to known.
- **No fudging, no gotchas.** The GM may not roll a social check before the words exist, and may not invent a result.
  The player may always ask what the character can tell about a person, and the GM answers with tells, not with a
  refusal.
- **Rewards are small and bounded.** One step of advantage, a +2 at most. Good roleplay tilts the dice; it does not
  replace them, except where a motive makes the outcome obvious (section 7).

## 3. The flow of one social beat

```
player:  I try to bluff the guard.                      (intent only)
GM:      "The guard narrows his eyes. What do you tell him?"   (no roll, turn ends)
player:  Easy, friend. Captain Ness sent me for the tally books. She said you'd be sour about it.
GM:      social_check(skill=deception, target=guard, spoken="Captain Ness sent me ...",
                      quality=strong, engages=[m031 aligned])
server:  words present, one check for this utterance, not barred by a motive   -> rolls with the boon
GM:      narrates the result, and the guard's tell, in the story's voice
```

The first message needs no new machinery: if the GM calls `social_check` without words, the tool refuses and says what
to do, so even a GM that forgot the rule is corrected for the price of one round. The prompt also tells the GM to ask
first, which avoids that round almost every time.

Cases:

- **The player already spoke** ("I tell the guard I'm the duke's courier"). The words are in the message; no question
  is needed.
- **The player summarizes** ("I talk him into it"). That is an intention, so the GM asks. In `encouraged` mode
  (section 9) the GM may accept the summary and roll with no boon.
- **Several characters.** The check is made for the character who speaks. Others may add words; the GM judges the best
  single contribution, not a sum.
- **A second attempt.** The server allows one `social_check` per player message and target. A new try needs new words,
  and the NPC remembers: a repeat of the same argument is `weak` by definition (section 5).

## 4. What counts as a social check

The social skills of the ruleset, where the player is trying to change what an NPC believes, feels or does:
persuasion/diplomacy, deception/bluff, intimidation, performance, haggling, and the older editions' reaction rolls and
persuasion by argument. Receptive checks (Insight, Sense Motive, Perception of a person) are not speech and need no
words; they are how the player earns a tell (section 8).

`roll_dice` is not removed. It still does everything else. As a guard against a GM that rolls a social check through
it anyway, `roll_dice` refuses a roll whose `# comment` names one of the social skills while the game's roleplay mode
is `required`, and points at `social_check`. It is a keyword match, not a proof, and prompts remain the main defense.

## 5. The `social_check` tool

```jsonc
social_check({
  "character": "Mira",                 // the player character who speaks
  "skill": "deception",                // free text, the ruleset's name for it
  "target": "e020",                    // the NPC (an entity id or name already in the world)
  "spoken": "Captain Ness sent me for the tally books...",   // the words the player typed, quoted or closely trimmed
  "quality": "strong",                 // weak | ordinary | strong | brilliant (the GM's judgment, see below)
  "engages": [                         // motives the words touch, from the briefing; see section 7
    { "motive": "m031", "effect": "aligned" }     // aligned | against
  ],
  "modifier": 5,                       // the character's total skill modifier (the GM reads the sheet)
  "dc": 15,                            // omitted in the reaction style
  "narration": "..."                   // shown to the player just before the dice, as for roll_dice
})
```

### What the server checks

1. **The words exist.** `spoken` must appear in the latest player message: after normalizing case and punctuation, at
   least 60% of its words must occur there in order, and it must have at least 4 words. Otherwise the tool returns:
   "The player has not said anything for the character to say. Ask what the character says, in the story's voice, and
   end your turn." Nothing is rolled.
2. **One check per utterance and target.** The state records the id of the player message and the target of the last
   check; a second call for the same pair is refused.
3. **The target is an NPC in the world** and, in a scene, present (or reachable, such as a letter; the GM says so in
   `narration`).
4. **No motive bars the roll** (section 7). The tool returns the refusal, the tell to narrate, and a note that no dice
   were rolled.
5. **The reward table** (below) turns `quality` and the engaged motives into a boon, and the boon into dice.

### Quality

The GM picks one of four values. The prompt gives a rubric, not a formula:

| Quality | Boon | Meaning |
|---|---|---|
| `weak` | −1 | Implausible to this person, contradicts what they know or can check, wrong voice for the character, a repeated argument, or meta-gaming ("I say whatever works") |
| `ordinary` | 0 | Plausible, fine, nothing special. The default, and what a flat summary earns in `encouraged` mode |
| `strong` | +1 | Specific, in character, and fitted to this person: uses a name, a detail or a fact the character really has |
| `brilliant` | +2 | Strong, and also surprising or costly in a way that fits: a risk the character takes, a truth that serves a lie, a line that could only come from this character |

The rubric asks four questions: Is it **in character** for this character (their background, traits and what they
know)? Is it **plausible to this listener** (can they check it, would they believe it)? Is it **specific** (does it use
something real)? Does it **speak to what the listener wants** (section 7)? Prose style, length and vocabulary are not
on the list.

### The reward table

The boon (quality plus motive effect, section 7, capped at −2 to +2) maps to dice by the ruleset's `social_style`, a
new field on the catalog entry in `rulesets.py`. The server builds the expression; the GM cannot pick a different one.

| Style | Rulesets | Boon +1 / +2 | Boon −1 / −2 |
|---|---|---|---|
| `advantage` | D&D 5e, 5.5e | advantage; advantage and DC −5 | disadvantage; disadvantage and DC +5 |
| `bonus` | 3e, 3.5e, 4e, Pathfinder 1e | +2 / +4 on the roll | −2 / −4 |
| `circumstance` | Pathfinder 2e | +1 / +2 circumstance bonus | −1 / −2 circumstance penalty |
| `reaction` | OD&D, B/X, BECMI, AD&D 1e and 2e | +1 / +2 to the 2d6 reaction roll | −1 / −2 |

Notes:

- The result for the GM is plain text with the numbers: the dice, the total, the margin and, for Pathfinder 2e, the
  degree of success (a natural 20 or 1 shifts it, as the edition says). The GM narrates from that and does not
  recompute. The player sees the dice (a second d20 under advantage, for instance) and the roll's comment, which the
  GM writes as the skill and a reason in a few words (`deception, well-fitted lie`). The DC is never shown.
- `advantage` caps at one die either way, as in the rules, so the second step is spent on the DC instead.
- `reaction` has no DC. The server rolls `2d6 + modifier + boon`, where `modifier` is the charisma reaction adjustment
  the edition gives. The GM reads the edition's reaction table (it is in the ruleset prompt). In these editions a
  strong enough argument often needs no roll at all (section 7).
- Beyond the dice, the ruleset prompt (`03_roleplay.md`, new, in each ruleset folder) says what else good roleplay earns
  in that edition: **Inspiration** in 5e (and Heroic Inspiration in 5.5e) when the player plays against their own
  interest because it suits the character, a **Hero Point** in Pathfinder 2e for a `brilliant` beat, and in the older
  editions nothing mechanical but the old-school habit of resolving it without dice. These are recorded on the sheet
  with `update_character`.

## 6. The player character's side

The judge needs to know the character's voice. It comes from the sheet (STATUS.md 3):

- The Session 0 character-building step already collects background and personality. The sheet pass is asked to keep a
  one-line **voice** section (traits, ideals, bonds and flaws in 5e; the equivalent elsewhere) so it reaches the GM
  every turn with the rest of the sheet.
- `in character` in the rubric means consistent with that line and with what the character has said and done before,
  not with the player's own personality.
- A player who plays against their character's grain for a reason (a lie, a mask) is judged on the lie working, not on
  matching the voice.

## 7. Motives

### 7.1 The record

Motives live in the world knowledge base, next to facts and entities, in the staged game state (so a failed turn rolls
them back) and in the save file as an optional field (older saves load with none; the file version does not change).

```jsonc
{
  "id": "m031",
  "owner": "e020",                       // an NPC entity
  "text": "Fears the Thorn Guild will learn that he sold them a false tally.",
  "scope": "underlying",                 // underlying | scene
  "kind": "fear",                        // want | fear | loyalty | grudge | vice | belief (a tag, it guides the hints)
  "strength": "driven",                  // leaning | driven | absolute
  "moved_by": ["a promise of silence", "someone else to blame"],
  "resists": ["open threats", "appeals to duty"],
  "tells": ["Glances at the cellar door whenever the Guild is named.", "Over-explains the tally."],
  "disclosure": "hidden",                // hidden | hinted | known (as for facts)
  "status": "active",                    // active | satisfied | frustrated | expired | superseded
  "scene": null,                         // scene motives only: {"location": "e012", "day": 3, "hour": 14}
  "turn": 31,
  "source": "generated"                  // generated | improvised | play
}
```

- **Underlying** motives are the long-lived wants, fears, loyalties and vices that make the person who they are. They
  are made ahead of play, with the rest of the world, and can change through play (a debt paid, a brother saved),
  except the `absolute` ones (below).
- **Scene** motives are what the person is after right now, in this place: to get the party out before the boss comes
  back, to impress the captain, to finish the bottle, to learn who sent them. They are tied to the scene's location and
  time, and expire (section 7.4).
- **Strength** is how much it counts. `leaning` tilts a result and `driven` shapes it. Both can be swayed: the right
  action (a debt cleared, a brother saved, a truth shown) can `shift` or `resolve` them.
- **`absolute` is fixed.** It is a very deep property of the person, a line they will not cross or a cause they will
  not ignore, and **nothing the player does changes it**: no argument, bribe, threat, favor or great roleplay. A motive
  that a sufficiently good action could move belongs in `driven`, however strong it is. So an `absolute` motive is
  always `underlying`, is written only ahead of play, and never changes, expires, resolves or is superseded for the
  life of the game. A person has at most one, many have none, and the curator's prompt says to use it rarely, for who
  the person is rather than what they happen to want or fear.
- `moved_by` and `resists` are the levers: short phrases saying what kind of argument engages the motive and what kind
  bounces off. They guide the GM's judgment of `quality` and keep a person consistent between sessions; they are not
  matched mechanically.
- `tells` are the GM's ready-made hints (section 8). They are phrased as behavior, never as the motive.
- A person has at most three active motives (two underlying, one scene), shown to the GM in that order. Fewer is fine;
  a bartender who is only tired has one.

Motives are kept apart from facts because they change faster, have a scope, a strength and tells, and are the one
thing the GM must never state. The `motivation` aspect that NPCs have today (`prompts/world/aspects/npc.md`) is
replaced by them for people who can speak; a faction's or a place's reasons stay facts.

### 7.2 What motives do to a check

When the GM makes a `social_check` it lists the motives its target has that the words touch, each as `aligned` (the
words serve it) or `against` (the words cut across it). The server reads the strength from the record, so the GM
cannot inflate it.

| Strongest engaged motive | Effect |
|---|---|
| `aligned`, `absolute` | **No roll is needed**: what is asked is what they already must do. The tool still records the result, as an automatic success, and the GM narrates it |
| `aligned`, `driven` | Boon +2 |
| `aligned`, `leaning` | Boon +1 |
| `against`, `leaning` | Boon −1 |
| `against`, `driven` | Boon −2 |
| `against`, `absolute` | **The roll is barred**: the tool returns an automatic failure and a tell to narrate. Dice cannot buy past a line |

- Only the strongest engaged motive on each side counts, so stacking small motives does not stack the boon. When one
  `aligned` and one `against` motive are both engaged, they are compared and the stronger decides; at equal strength
  they cancel, and the check is made on `quality` alone.
- Scene motives outrank underlying ones of the same strength (the moment wins), but an `absolute` underlying motive
  outranks any scene motive. A guard who wants to look busy (scene) can still be bribed; a guard who would die before
  betraying his lord (absolute) cannot.
- **Quality and motive add** to give the boon, capped at ±2: `strong` words aimed at a `driven` want would total +3 and
  count as +2. A `weak` line aimed at a `driven` want totals +1.
- The same words can be right for one person and wrong for another. The `quality` rubric asks the GM to use the levers:
  threats `resist`ed by a proud man are `weak` however well put.
- **Receptive and contested checks.** Reading a person (Insight, Sense Motive) against someone with a `driven` or
  `absolute` motive they are hiding has its DC raised by one step (the edition's usual step: +5, +2, +1); the GM adds it
  and says so in the roll's comment. It does not need `social_check`.

### 7.3 Where motives come from

- **Underlying, ahead of play.** The curator's expand pass (WORLD.md 4.4) writes them with each NPC it creates, from the
  NPC's role, relationships and the facts about their faction, the way it writes the NPC's other aspects now. They must
  obey the independence rules (WORLD.md 5.4): an underlying motive never exists because of the party. The first pass
  after an NPC steps on stage, if the NPC has none, writes them too, so improvised characters are covered.
- **Scene, in play.** The GM sets them with `set_motive` (below), and is told to give every NPC who will speak at length
  a scene motive before they speak. They may be reactions to the party ("he wants to know who sent you"). If the GM
  forgets, the NPC runs on underlying motives alone, which is acceptable.
- **Changes, in play.** The curator's extract pass (WORLD.md 4.2) is told to report motive changes shown by the
  narration (a debt cleared, a fear confirmed, a scene want satisfied), and the server applies them like fact
  supersession. The GM can also do it directly with `set_motive`.

`set_motive`:

```jsonc
set_motive({ "op": "add",     "owner": "e020", "text": "...", "scope": "scene", "kind": "want",
             "strength": "driven", "tells": ["..."], "moved_by": ["..."], "resists": ["..."] })
set_motive({ "op": "shift",   "id": "m031", "strength": "leaning", "text": "..." })      // supersedes, keeps history
set_motive({ "op": "resolve", "id": "m040", "outcome": "satisfied" })                   // satisfied | frustrated
set_motive({ "op": "disclose", "id": "m031", "level": "hinted" })                       // or "known", see section 8
```

The usual rules for world tools apply (WORLD.md 6.3): all or nothing, errors written for the model, and a cap on the
count (3 active per person). The server enforces the `absolute` rule: `add` refuses `strength: "absolute"` (the GM
cannot create one in play, and a scene motive can never be one), and `shift` and `resolve` refuse an `absolute` motive
and say that it cannot be changed. The curator's extract pass is not offered `absolute` motives as things to change.
`disclose` works on every motive.

### 7.4 Scene motives expire

A scene motive records the location and the world time when it was set. It becomes `expired` automatically when:

- `set_scene` moves the party to another location (the old scene is over),
- two or more in-world hours pass since it was set (the clock only moves in whole hours, WORLD.md 2.4), or
- it is resolved by play (`satisfied` or `frustrated`).

(`absolute` motives are underlying, so none of this applies to them.) Expiry is computed when the briefing is built,
from the records, so it needs no background work. A scene motive that has become `satisfied` or `frustrated` may
leave a trace: the curator can promote the outcome into a fact about the NPC ("Harlan was caught out by the party")
and into an underlying `grudge` or `loyalty`.

### 7.5 How motives reach the GM

The briefing's NPC section (WORLD.md 6.1) gains the motives of the NPCs present, labeled like hidden facts:

```
- Harlan Voss (e020), tally clerk. Manner: fussy, over-polite.
  [GM only, never state] fear (driven, underlying): fears the Thorn Guild will learn he sold them a false tally.
      Moved by: a promise of silence; someone else to blame. Resists: open threats. Tells: glances at the cellar door
      whenever the Guild is named; over-explains the tally.
  [GM only, never state] want (leaning, scene, until you leave the counting-house): wants the party gone before noon.
```

- About 60 tokens per motive, three per person, only for people present, counted against `AIGM_WORLD_BRIEFING_TOKENS`.
  Motives are cut before facts when the budget is tight, strongest first kept.
- `recall` of an NPC includes their motives for the GM. Motives of people not present are not in the briefing.
- The rules prompt says, in words close to: *play every named NPC from their motives; let tells show, never tell. A
  motive may not appear in narration or dialogue unless the NPC would say it aloud, and then it is disclosed (below).*

## 8. Hints: how the player finds out

The player never reads a motive. They learn by four routes, all in the fiction:

1. **Tells in passing.** When an NPC is under pressure or the topic touches a motive, the GM works in one of its `tells`
   (or one it invents in the same spirit). Pacing: at most one new tell per NPC per scene unless the player is looking.
   The prompt gives the GM permission to under-hint: a missed tell is better than a tutorial.
2. **Receptive checks.** A successful Insight/Sense Motive check on an NPC reveals a tell the player had not seen.
   Margin sets clarity: a plain success gives the *feeling* ("he is afraid of something") and a tell; a success by 5
   or more, or a critical success, also says what the fear touches ("it has to do with the Guild"). The check never
   states the cause outright.
3. **Poking.** An NPC's reaction to words that engaged a motive is itself the best tell. `social_check` returns to the
   GM which motives were engaged so the narration shows it, whether the words won or lost.
4. **Gossip and research.** Other people know things about this person; a rumor is a known fact (WORLD.md 2.3), and the
   curator can seed them from underlying motives for NPCs the party will meet.

### Disclosure levels

Reusing the fact vocabulary (WORLD.md 2.3):

| Level | Meaning | Where it shows |
|---|---|---|
| `hidden` | The player has seen nothing | GM only |
| `hinted` | A tell has been narrated or a check succeeded | GM only; the tell is marked used, so it is not repeated |
| `known` | The NPC said it or the player has proven it | A **known fact** about the NPC is added, so it appears in the compendium like any other. The motive stays and keeps working |

The GM calls `set_motive` with `disclose` when it narrates a hint or the player learns the truth; otherwise the curator
extract pass sees the narration and updates the level, as it does for facts. When a motive becomes `known` the server
creates the fact from the motive's text, in the player's terms ("Harlan Voss is afraid the Thorn Guild will learn of his
false tally"), and the compendium shows it through the existing machinery.

**The motive itself remains.** Learning a motive does not retire it: the record stays `active` at the same strength and
keeps doing everything in section 7.2 (the boon, the automatic success, the bar). Knowing that a clerk fears the Guild
does not stop that fear shaping what he will do; it only means the player can now aim at it. The fact is a copy for the
player's journal, and the two are not linked afterward: if play changes the motive (`shift`, `resolve`), the curator
supersedes the fact through the usual reconciliation (WORLD.md 4.3). Nothing else about a motive ever leaves the server:
not the strength, not the levers, not the unused tells.

`/world`-style dumps (`AIGM_WORLD_DUMP`) and the debug context viewer already show hidden material and will show motives
too. So does the **Hidden tab** of the compendium on a debug server (COMPENDIUM.md 11), which lists every entity that
has hidden or hinted facts or motives and shows each motive with its type (`want`, `fear`, ...), strength, scope and
disclosure level. It is the intended way to inspect and debug motives. They are the same kind of spoiler as hidden
facts.

## 9. Strictness: the Session 0 choice

A setting `roleplay` in the game state, chosen in Session 0 with a new `set_roleplay` tool (offered in Session 0 only,
like `set_ruleset`), default `required`:

| Mode | Behavior |
|---|---|
| `required` | A social check needs spoken words (section 5). The default |
| `encouraged` | Words earn a boon as above. A player who only describes intent can still have the check made, at `ordinary` quality with a note that words would have helped |
| `off` | The old behavior: no gate, no quality, no boon. Motives still shape the NPC, bar impossible rolls and give tells; `social_check` is not offered |

The default for a new game is `AIGM_ROLEPLAY` (config, default `required`), which Session 0 may override. The GM raises
it with one line in Session 0 ("I'll ask you to say what your character says when you talk to people; if you would
rather summarize, say so"), the way it raises the ruleset. The save file stores the mode (optional field, default
`required` for saves from before this, since that is the new behavior).

## 10. Surfaces

- **Tools.** `social_check` and `set_motive` in the adventure phase, `set_roleplay` in Session 0.
- **Prompts.** `system/adventure/05_roleplay.md` (the rubric, the ask-first habit, tells not telling, motives for every
  speaking NPC) and per-ruleset `rulesets/<id>/03_roleplay.md` (the edition's reward and its social skills). Tool
  descriptions in `prompts/tools/`. Curator prompts: `expand` writes motives, `extract` reports motive changes and
  narrated tells (`world/` prompts, both edition-neutral for now, as the rest of the curator).
- **API (API.md).** The `dice` SSE event is unchanged apart from the comment. `known` motives appear as facts in
  `/compendium`. There is no motive endpoint and nothing about hidden motives is added to `message_end`.
- **Client.** No change in v1: dice, comments and the compendium already show everything the player is allowed to see.
- **`--test` mode.** A `persuade <words>` command exercises `social_check` against a scripted NPC with a fixed motive,
  so the gate, the reward and the bar can be tried without an API key.

## 11. Testing

Pure logic, no model:

- **Motive record:** caps per person; scene expiry on location change, elapsed hours and resolution; supersession on
  `shift`; `absolute` is refused in `add` (for a scene motive, or at all in play), and `shift` and `resolve` refuse
  it; round trip through save and load; a save without motives loads; rollback with a failed turn.
- **Boon arithmetic:** quality plus engaged motive for every row of the table in 7.2, including the cap, the
  `absolute` bar, the automatic success, equal-strength cancellation, and "scene beats underlying except absolute".
- **Reward table:** every `social_style` against boons −2 to +2 gives the expected expression and DC; every ruleset in
  the catalog has a style; each ruleset folder has `03_roleplay.md` (the existing catalog test extended).
- **The words gate:** accepted, no words, fewer than 4 words, a quote not in the message, a quote present in an older
  message but not the latest, second call for the same message and target, a target that is not an NPC.
- **`roll_dice` guard:** a social comment is refused in `required` mode and allowed in `off`.
- **Briefing:** motives of present NPCs are labeled, budget-trimmed, and absent for NPCs not present.
- **Secrecy:** nothing in the compendium, status, history or any non-debug response contains a hidden or hinted motive's
  text; a `known` motive appears only as its fact.
- **Curator:** the scripted curator writes motives on expand, applies reported changes and disclosures.

Live behavior (needs a real model, noted in section 13): whether the GM asks before rolling, quality inflation, how
often tells appear.

## 12. Decisions to confirm

1. **`social_check` is a new tool,** not a field on `roll_dice`, so the server can build the expression and refuse the
   roll. (The alternative, a `roleplay` object on `roll_dice`, is smaller but lets the GM write any expression.)
2. **Default mode is `required`,** per the request, with `encouraged` and `off` as Session 0 options for players who
   do not want to type dialogue.
3. **The GM judges quality** on a four-step scale with a rubric; there is no second model call.
4. **Motives are their own record,** not facts, because of scope, strength, tells and the rule that they are never
   stated.
5. **Underlying motives come from the curator, scene motives from the GM,** with the GM allowed to add either
   (but never an `absolute` one).
6. **A boon is capped at ±2** and mapped per ruleset by `social_style`; an `absolute` motive, fixed for the life of
   the game, can force a success or bar the roll.
7. **Disclosure reuses the fact vocabulary.** A motive that becomes known gains an ordinary known fact and stays an
   active motive, so it keeps affecting rolls.
8. **Only NPCs have motives in v1.** Factions keep facts; the party's own motives stay with the player.

Open, with a recommendation:

- *What does a player do against an `absolute` motive?* Go around it, not through it: find another person, another way
  in, or an aim that does not cross the line. The bar is firm by design, and the tell it shows tells the player which
  line it is.
- *Should the player be told why a roll was barred or aided?* Recommended: no. The tell and the roll's comment are
  enough, and "the DC is hidden" stays true.
- *Voice-less players.* `encouraged` covers it. If that proves too soft, a per-character "gist" allowance (a few
  uses per session, no boon) is the usual middle ground.

## 13. Risks

- **A GM that does not ask for words, or rolls through `roll_dice`.** The gate and the comment guard catch most of it.
  Small local models will skip steps; the failure is a wasted round, not a wrong result.
- **Quality inflation.** A friendly model calls everything `strong`. Mitigation: the rubric lists what `ordinary` is,
  the cap is small, and a prompt line says most lines are `ordinary`. A later counter could report the share of
  `strong` and `brilliant` calls in the debug metrics (`metrics.py`).
- **Over-hinting, or motives that make NPCs rigid.** The one-tell-per-scene pacing and the instruction that motives
  are reasons, not scripts guard against both; an NPC may act against a `leaning` motive for a good enough reason.
- **Prompt and briefing growth.** Roughly 200 tokens of rules, plus 60 per motive in the briefing, inside the existing
  budget. Motives drop before facts.
- **Players gaming the keyword rubric.** The rubric deliberately has no word list; `moved_by` and `resists` are guidance
  for the GM, not triggers.
- **Secrecy leaks.** The `known` conversion goes through one function and the secrecy tests in section 11 watch the
  places a leak would show up.

## 14. Build order

Each step ships working and is tested alone.

1. **Motive record, persistence, briefing** (*done*). `Motive` and `World.add_motive`, `motives_of`, `motive_live`
   and `motive_state` in `world/model.py`; saving and loading; the briefing section; and the motives half of the debug
   Hidden tab and of the world dump. No tools yet: motives can be put in by tests only. What it settled:
   - The model enforces the caps (two lasting and one scene motive live per person, and at most four phrases in each
     of `moved_by`, `resists` and `tells`), and the `absolute` rules that need no tool: underlying only, one per
     person, source `seed` or `generated`.
   - A scene motive stores its location and the time it was set. "Lapsed" is worked out from those and the world's
     scene and clock (`motive_live`), never stored, so there is nothing to expire. The Hidden tab shows a lapsed one as
     `expired`.
   - A save without motives loads with none, and `next_id` may lack `m`. Motives are in the world dump and not in its
     `--known-only` view.
2. **`set_motive` and the curator** (*done*). The GM now sees motives and plays them. What it settled:
   - **Model.** `shift_motive` (the old motive is kept as `superseded`; the new one keeps the person, scope, moment,
     disclosure and anything not changed), `resolve_motive` and `disclose_motive`. Both refuse an `absolute` motive
     with a message the GM can read. A shift that changes nothing is refused. `disclose` only goes to `hinted` for
     now; `known`, with its fact, is step 4.
   - **Tool.** `set_motive({ "changes": [ ... ] })`, up to six changes of `add`, `shift`, `resolve` or `disclose`,
     all or nothing. Its `strength` offers only `leaning` and `driven`; `add` defaults to a scene motive and the tool
     also refuses party members and anything that is not a recorded person. It is a silent bookkeeping tool like
     `establish`. `recall` lists a person's live motives for the GM. The GM prompt (`04_world.md`) says to play people
     from their motives, never to state one, and to give each speaking person a scene motive.
   - **Expansion.** A person's checklist now has a `motives` slot instead of `motivation` (the `motivation` aspect
     remains valid for old saves and for facts the GM records, but is no longer asked for). A person with no lasting
     motive is a frontier entity until one is written. The expand call returns `motives`; the server keeps up to four
     per call, only for recorded or new people, always `underlying`, source `generated`, and lets the model's caps
     apply (two lasting per person, one `absolute`). Motive text and tells go through the independence rules like
     facts: one retry with feedback, then dropped.
   - **Extraction.** The request lists the live, non-absolute motives of the people present. The answer's
     `motive_reports` (`shift`, `resolve` or `hint`, by id) become ops; a report for an absolute, finished or unknown
     motive is dropped with a note, a `shift` text that mentions the party is dropped, and `hint` marks the motive
     `hinted`.
   - **Test mode.** `motive <name> [text]` adds a scene motive through the real tool, and the scripted curator gives
     every person a lasting `want`.
3. **`social_check`** (*done*). The tool is `aigm/tools/social.py`, the rules are in `aigm/roleplay.py` (pure and
   tested alone), and `Ruleset.social_style` is in the catalog. What it settled, and where it differs from sections 5
   and 9:
   - **Words.** `spoken` must have at least four words and 60% of them must occur, in order, in the player's latest
     message (`GameState.player_text`, set by the turn loop). One check per player message and person is kept in
     `GameState.social_done`; a refusal does not use up the try, and neither does a missing narration. The server
     cannot tell an intention from speech once it is four words long, so the prompts carry that part.
   - **Motives in the dice.** `roleplay.motive_effect` and `boon_for` implement the table in 7.2, including that the
     moment beats a lasting motive of the same strength, and an absolute one beats everything. The motive ids the GM
     gives must be live motives of the person addressed. A barred or automatic result uses up the try, rolls nothing
     and shows no dice; the result text gives the GM a tell to narrate.
   - **Dice.** `plan_roll` builds the expression for the style; the result gives the GM the dice, the DC after any
     adjustment and the margin, or for Pathfinder 2e the degree (a natural 20 or 1 moves it a step). The roll's
     comment is the skill plus "well played" or "weak argument" when the words alone earned or lost something, never
     the reason a motive added.
   - **Narration is not streamed** for this tool, unlike `roll_dice`, because the call may be refused for want of
     words and then nothing of it may reach the player. A barred or automatic result shows no narration of its own
     and the GM narrates it.
   - **Guard.** `roll_dice` refuses a comment naming persuasion, diplomacy, deception, bluff, intimidation, haggling,
     gather information or a reaction roll. It does this whenever the game is in the adventure; step 5 will make it
     depend on the mode. Performance is left out because it may be played to a crowd, and `social_check` names one
     listener. The target must be a person with the party; one who is elsewhere needs `set_scene` first.
   - **Prompts.** `system/adventure/05_roleplay.md` (ask first, judge the idea, answer in character) and a
     `03_roleplay.md` in every ruleset folder. The ruleset file is used in the adventure only, so
     `PromptLibrary.ruleset_parts` leaves it out and `system_parts` adds it after the ruleset's other files.
   - **Test mode.** `persuade <name> [words]`: with no words the scripted GM asks what you say; with words it records
     the person, puts them in the scene and calls the real tool.
4. **Disclosure.** `disclose`, the hinted/known levels, the known-fact conversion and the compendium path, the
   Insight-clarity rule in the prompts.
5. **Session 0.** `set_roleplay`, `AIGM_ROLEPLAY`, the voice line on the sheet, `encouraged` and `off`.
6. **Docs and a live pass.** Update API.md, BACKEND.md, WORLD.md and RULESETS.md for the new tools and fields, and try
   it with a real model, as the opening and status page still need.
