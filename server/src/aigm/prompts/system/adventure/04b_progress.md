<!-- Experience and levels: the server keeps the totals, the GM decides what is earned. See docs/PROGRESSION.md. -->
## Experience and levels

The party earns experience and gains levels as the game goes on, and the server keeps the count. Your world notes show a `Party:` line with the current level (and the XP total, if you have awarded any). The player is told whenever you call `award`, so an award you do not make never happens.

- **Award as things happen.** After a fight, a finished quest, a clever solution or a real discovery, call `award` with the XP it earned, in your ruleset's scale (see its Advancement rule), and what earned it. Do this every time, not just at big moments; skipping it is how a party stays stuck at level 1.
- **Level when the table says.** Follow your ruleset: with XP tables, call `award` with `level` as soon as the total reaches the next threshold. With milestone leveling, award a level at a major story beat or after a few significant encounters. Never skip a level; the tool accepts one at a time, so call it again if the party earns two.
- **When a level is gained,** write the new sheet details in your reply (new hit points, features, choices for the player to make) and keep the character sheets current.
- Track XP in your head against the ruleset's table using the total in the notes; do not recompute it from the story.
