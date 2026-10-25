Record a change to a party member's character sheet. The sheet is what the player sees on the status page, so call this whenever your story changes something on it: damage or healing, a condition gained or ended, a spell slot or charge spent, a potion drunk, an item found, lost or used, coin gained or spent, a new ability.

- `name`: the party member.
- `hp` (the new total) or `hp_delta` (a gain, or a loss as a negative number): hit points. Do the arithmetic by the rules and tell the player the result in your story ("you take 4 damage"); the server keeps the number. `max_hp` if the maximum changed.
- `conditions_add` / `conditions_remove`: short names such as "poisoned" or "prone".
- `section`: a title and the complete new list of lines, which replaces that section of the sheet or adds it if there is none. Your world notes show the current sheet. Rewrite the whole section, so a spent spell slot or a potion drunk is the same section with that line changed. An empty list removes the section.

One call per character. Make all the changes a reply needs in one response, before the message that holds your final reply, and write no text in the same response as a call. Tool calls are invisible to the player. Experience and levels are not recorded here: use `award`.
