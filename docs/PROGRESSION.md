# Experience and levels

The server keeps the party's advancement, and the GM awards it. Before this the starting level was the only number the
server held; the GM was told to track levels and reward quests in prose, and in practice never did.

## State

`GameState.level` (None until the first award, then the party level) and `GameState.xp`. `party_level` is the
level, falling back to the one chosen in Session 0 (`campaign["level"]`). Both are saved (save format 5; older saves
load with level from Session 0 and 0 XP) and copied with the turn's working state, so an award in a failed turn is lost
with the turn.

## The `award` tool

Offered in the adventure phase, to endless and story games alike. Input: `xp` (the whole party's points), `level`
(the new party level, exactly one above the current one) and a required `reason`. At least one of `xp` and `level`
is needed. The server does not know any ruleset's XP table: the GM decides what is earned and, under its ruleset's
Advancement rule, when a level is reached. Rulesets that level by milestone award `level` only. A level is one step at
a time, so a double level-up is two calls.

The result tells the GM the new totals and, after a level, to update every character sheet. The player is shown an
`award` SSE event (docs/API.md), which the client prints as a line (`+120 XP (total 340) for the wolves`, or
`Level up! The party is now level 3`). The line is also rebuilt from the `award` calls in the stored history.

## What the GM sees

Every request's world notes start with `Party: level 2, 450 XP.` (the XP only once some was awarded), so the GM knows
the level without remembering it. The adventure prompt (`system/adventure/04b_progress.md`) tells it to award after
fights, finished quests, discoveries and clever solutions, to level when the ruleset's table or milestones say so, and
to describe the new sheet details. In a story game, a finished quest whose plan gives something (a level, an ally,
an item) is followed by a reminder in the `set_scene` result to hand the reward out with `award`.

## Not done

The server does not enforce XP tables or the story's per-chapter target levels; those stay with the GM, guided by the
briefing. The curator does not read XP from the narration.
