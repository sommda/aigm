# Experience and levels

The server keeps each party member's advancement, and the GM awards it. Before this the starting level was the only
number the server held; the GM was told to track levels and reward quests in prose, and in practice never did.

## State

`GameState.heroes` maps a character's name (from the campaign record's party) to a `Hero` with a `level` and `xp`.
A character with no entry is at the party's starting level (`campaign["level"]`) with no XP. `average_level` is the
mean over the party. Everything is saved (save format 5; older saves load at the starting level with no XP) and copied
with the turn's working state, so an award in a failed turn is lost with the turn.

## The `award` tool

Offered in the adventure phase, to endless and story games alike.

- `xp`: points that each recipient earns. The GM works out the share under its ruleset (some divide a total).
- `who`: the recipients' names, case aside. Left out, it is the whole party, the usual case. Name only some when the rest
  were absent or the award is personal.
- `level_up`: characters who have just reached their next level, each rising by one. How much XP a level takes
  depends on the character's class and the ruleset, which the server does not know, so the GM decides.
- `reason`: required, what earned it.

Every XP award ends with a result that lists each touched character's level and XP and tells the GM to compare each
against the ruleset's advancement table for their class, and to call `award` again with `level_up` for anyone who has
earned a level. The tool description and the adventure prompt (`system/adventure/04b_progress.md`) repeat the rule.

The player sees an `award` SSE event (docs/API.md), printed as `+120 XP to the party for the wolves` and, for each
level gained, `Maren Holt reaches level 2!`. The lines are rebuilt from the stored `award` calls when a game is reloaded.

## What the GM sees

Every request's world notes start with `Party: Maren Holt level 2, 450 XP; Ilyr Wren level 1.` In a story game the
story section also gives the party's average level and the level the chapter needs.

## Chapters and the average level

A story chapter has a target level (docs/STORY.md). `Story.party_level` keeps the party's average, updated by every
award. Chapters 1 and 2 end only when their quests are settled (and, in chapter 1, the goal is known) **and** the
average level has reached the target. The GM is told when the quests are done but the level is short, so that it gives
the party more to earn. The award that lifts the average over the target ends the chapter itself.

So that a party that cannot earn the level never stalls the story, the level requirement lapses `LEVEL_GRACE_TURNS`
(40) turns into the chapter. Chapter 3 ends with the story's ending and is not held back by level.

## Not done

The server does not enforce XP tables, and the curator does not read XP from the narration.
