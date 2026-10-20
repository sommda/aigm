This game is a story, so `set_scene` is also where you report its progress, in the optional `story` field. You do not need a location change to use it: call `set_scene` with only `story` when a quest ends.

- `story.quests`: for each quest of your story notes that has just ended, its `id`, a `status` and an `outcome`. Use `done` when the party achieved it, `skipped` when they got around it by other means, and `failed` when it can no longer be done (the person who mattered is dead, the place is destroyed). The `outcome` is one or two sentences on what happened and what the party chose; it is kept to shape the ending.
- `story.goal_revealed`: true once the party has learned what the final goal is, whether from the quest that reveals it or earlier.

Only report what has really happened in the story so far. The result tells you which quests are now active and when a new chapter begins.
