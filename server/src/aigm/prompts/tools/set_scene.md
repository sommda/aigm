Tell the world notes where the party is now and who is with them, and how much in-world time has passed. Call it when the party moves to a different recorded place, when people join or leave them, or when time passes (travel, a rest, waiting, a night's sleep).

- `location`: the recorded place the party is now in. **Whenever your narration takes the party somewhere (even a room in the building they are in), pass `location`**: without it the place does not change, however you narrate it, and the player's status page stays where it was. Moving to a new place clears who is present unless you also give `present`.
- `present`: recorded people or groups now with the party; this replaces the previous list. Never list the party members themselves: they are always with the party and are not recorded.
- `elapsed_minutes`: whole minutes passed since your last reply, beyond what your rolls and `pass_time` calls this turn already counted (your best estimate: 10 for a short walk or a search of a room, 60 for an hour, 480 for a night's sleep, 1440 for a day; 0 if none).

Places and people must already be recorded; use `establish` first for new ones. Your next world notes will reflect the change.

Call it before the message that holds your final reply, never in that message and never after it. If you are about to roll, roll first, then call this once you have seen the results. Once the result is back, do not repeat or add to your reply.

Write no text in the same response as this call: not even a remark such as "I'll record that". Anything you write is shown to the player as story.

When the party moves, the player must read the journey and the arrival in the story before anything happens at the new place, so call this before the first roll there and narrate the trip.
- Moving the party takes the time the way takes: the server works it out from the routes, or from the places' sizes when none is recorded, and moves the clock to match if you gave less. Give `elapsed_minutes` as the time you narrate; if it is longer than the way, yours stands, and a long trip between places with no recorded route is kept as a route.
- When the party sets out for a place that is not next door and has more than one way to it, the result lists the ways and does not move them: unless the player's words or your narration already chose one, ask which they take (describe the ways, do not number them), then call `set_scene` again with `via`: a place on the way or words from its description. A party with no knowledge of a way is not offered it.
- The party walks the way. It stops in the first place it has not been to (set them down there, narrate as far as it and no further, and let them explore on), and at a block on the only way (describe what stops them). `guide` names a recorded person with the party who knows the way: with one the party passes through places it has not seen. When it stops short, `present` is cleared; call `set_scene` again at the stop if people are there.
- `pace`: `normal` is on foot. `fast` (a horse, a coach, a boat) halves the time and `instant` takes none, and both need `how`: the means the story has given the party. Travel is never instant unless something in the story, such as a teleportation circle or a spell, makes it so.
