Let in-world time pass whenever the story spends it and no roll, `set_scene` travel or fight records it: a conversation that needs no roll, a watch kept, a wait, the party studying a map or tending the wounded. Also use it for the time a roll's result forces, such as a failed climb that cost an hour of searching for another way. Call it after you have seen the roll.

- `minutes`: whole minutes, 1 to 1440 (a day). Longer stretches, and any travel, are `elapsed_minutes` on `set_scene`.
- `reason`: one line on what the time was spent on.

Ask yourself at the end of every turn: did what I narrated take more than a few minutes, and did a tool already count it? If not, call this. Typical amounts: a talk over a meal or a negotiation 15 to 30, questioning a prisoner 20, reading a book or a map 30 to 60, bandaging and resting briefly 10 to 30, a night's watch 480, waiting for someone 30 to 120, crafting or cooking an hour or more.

Each stretch of time is declared once, in the tool that fits it: a roll's own `minutes` for the action it tests, this tool for time with no roll, `set_scene` for travel, rests and waiting. Do not count the same time twice. A moment, a line of dialogue, a quick look: no time worth counting, so do not call this for it.

The time of the last turn is shown in your notes. Let the player feel time passing in the story when it is half an hour or more: the light, weariness, a candle burned down. Write no text in the same response as this call.
