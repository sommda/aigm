Keep the player's view of a fight up to date. The status page shows a table of who is in the fight and how they are doing, and it shows only what you give here, so write only what the player can see. The party members are already in the table (from their sheets): never list them.

- `action: "start"` when a fight begins. `combatants` lists everyone else in it: `name`, `side` (`foe` or `ally`), `count` for a group (a pack of four wolves is one entry with count 4), `health`, and `conditions` if any.
- `action: "update"` when the fight changes. List only the combatants that change: a new `health` or `conditions`, a new `count` as a group is thinned out, a new entry (give its `side`), or `remove: true` for one that has fled or been cleared away.
- `action: "end"` when the fight is over (everyone dead, fled, surrendered or talked down). Call it before your closing description.

Health: a foe's `health` is one of `unhurt`, `scratched`, `bloodied`, `near death` or `down`, chosen from how hurt it looks to the characters. The player is never told a monster's hit points, so do not give numbers. An ally's `health` may be numbers such as "9/12".

Call it on the same terms as `update_character`: in the response before the message that holds your final reply, with no text of your own in the same response, and all the changes a reply needs in one call. Change the party's own hit points with `update_character`, not here.
