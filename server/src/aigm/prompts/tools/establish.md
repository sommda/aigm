Record things you have introduced or settled in the world, so they stay true for the rest of the game. Call it whenever you invent a named person, place or group, give an existing one a new detail, or decide a hidden truth, and in the same turn as the narration where it first appears.

- `entities`: new named people (`npc`; add `look_notes`, the visible traits you are about to narrate, at most 40 words), places (`location`, with `parent` set to the town or area that contains it; only places have a `parent`), groups (`faction`) or ideas (`concept`). Do not repeat ones already recorded: a person or place that is already in your notes under another name is recorded already, so use its name.
- `facts`: single declarative sentences of about 40 words or fewer (a longer one is refused, so split it into two facts), using names instead of pronouns, written as the world's truth ("Wren pours drinks at the Rusty Flagon and sells news to the Thorn Guild."), never as a story beat ("The party met Wren"). `about` lists the entities involved, subject first; they must already be recorded or be in `entities` of this same call. Set `disclosure` to `known` if the player has now been told it (the default), `hidden` if it is true but the player has not learned it, or `hinted` if they have only heard hints.
- `reveal`: ids of GM-only facts from your notes that your narration has just told the player.

If any part is rejected nothing is recorded, and the error says what to fix. Do not record anything that exists because of the party's actions rather than the world, and do not contradict recorded facts.

Call it before the message that holds your final reply, never in that message and never after it. If you are about to roll, roll first, then call this once you have seen the results. Once the result is back, do not repeat or add to your reply.

Write no text in the same response as this call: not even a remark such as "I'll record that". Anything you write is shown to the player as story.


Record a named person the first time they appear, before you narrate them, so their description can be written and stays the same for the whole game.
