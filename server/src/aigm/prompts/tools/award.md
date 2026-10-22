Give party members experience points or levels. The server keeps each character's totals, tells the player, and shows every character's level and XP in your world notes, so call it whenever the party earns something instead of only describing it.

- `xp`: the experience points each of the named characters earns, in your ruleset's own scale, for a combat, a quest, a discovery, treasure or a clever solution. Work out the share yourself under your ruleset's rules (some divide the total among the party; some give each character the full amount).
- `who`: the characters who earn it. Leave it out for the whole party, which is the usual case. Name only some when the rest were absent, out of the fight, or the award is personal (a character's own goal, a class-specific award).
- `level_up`: the characters who have just reached their next level, each going up exactly one. How much XP a level takes depends on each character's class and the ruleset, so look up each one's threshold; do not assume the party levels together.
- `reason`: what earned it, in a few words.

After every award of XP, the result lists each character's total: compare each against the ruleset's advancement table for their class, and if anyone has earned a level, call `award` again with `level_up` naming them, then update their sheets. Do this check every time. Call this in the same response as your other bookkeeping, before your final reply, and write no text beside it. The player sees the award; describe the new abilities in your reply when someone gains a level.
