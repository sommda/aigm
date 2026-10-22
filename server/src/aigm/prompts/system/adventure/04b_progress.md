<!-- Experience and levels: the server keeps each character's totals, the GM decides what is earned. See docs/PROGRESSION.md. -->
## Experience and levels

Each party member has their own level and experience, and the server keeps the count. Your world notes show a `Party:` line with every character's level (and XP, once awarded). The player is told whenever you call `award`, so an award you do not make never happens.

- **Award as things happen.** After a fight, a finished quest, a clever solution or a real discovery, call `award` with the XP it earned, in your ruleset's scale (see its Advancement rule), and what earned it. Do this every time, not just at big moments; skipping it is how a party stays stuck at level 1. Usually everyone gets the same; name only some characters (`who`) when the others were not there or the award is personal.
- **Check for level-ups every time.** Characters level at different XP totals depending on their class and the ruleset. After each XP award, compare every character's total with the ruleset's table for their class, and call `award` with `level_up` for each one who has reached the next level, as soon as they do. With milestone leveling, award levels at a major story beat or after a few significant encounters. Never skip a level; each call raises a character by one.
- **When someone gains a level,** write their new sheet details in your reply (hit points, features, choices for the player to make) and keep the character sheets current.
- In a story, the notes give the average party level and the level the chapter aims for; the chapter does not end until the average reaches it.
