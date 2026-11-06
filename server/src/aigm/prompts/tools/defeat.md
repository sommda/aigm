Record that the whole party has been beaten: every character is dead, down, captured or otherwise out of the fight. A party that is merely losing, or that has retreated, is not defeated. Use this instead of marking the last living character dead.

- `how`: `taken` (captured, bound, held), `left` (left for dead, then found and tended) or `routed` (driven off and scattered, to regroup later).
- `aftermath`: where the party is now and in what state. It must be a position they can act from (waking in a cell, stripped of weapons; tended in a stranger's wagon), never "you all die".
- `cost` and `cost_kind`: one sentence on what the defeat cost them (gear taken, an ally lost, ground given to the enemy) and its kind: `time`, `resource`, `ally`, `knowledge` or `position`. In chapter 1 it is small and only `time` or `resource`.
- `elapsed_hours`: the hours that pass before the party can act. In the middle of a story a first defeat takes at least a day, a second at least three, and each later one more; the result tells you if your figure is too low.

Afterwards narrate the aftermath, move the party with `set_scene` if they are somewhere new, and update every sheet with `update_character` (hit points, conditions, what was taken). If they were `taken`, the way out is its own quest: the result says when it is written; until then narrate the captivity and let the party act, but do not free them. In the endgame a defeat is the end of the story: the result tells you to play out the failure ending.

The player is never told in advance that a fight could end the game, and the characters who fell are not lost: they wake, are found or are freed. Do not use this to punish; use it when the dice and the fiction have truly left the party with nothing.
