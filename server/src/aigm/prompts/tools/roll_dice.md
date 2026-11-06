Roll dice using d20 expression syntax and return the result. Use it for any random outcome: attacks, ability checks, saving throws, damage, random tables.

Examples: `1d20+5`, `4d6kh3` (roll four, keep the highest three), `2d8+1d4+3`. Use `2d20kh1` for advantage and `2d20kl1` for disadvantage. Percentile dice are `1d100`. Add a trailing `# comment` to label the roll, for example `1d20+3 # stealth check`.

Every call needs a `narration`. It is shown to the player as story text just before the dice appear, so it must say what is happening and what is at stake. A call without one is refused and nothing is rolled.

`minutes` is how long the action being tested takes, when it is more than a moment: a lock 10, a search of a room 30, a hard climb 60. Give it on the roll that decides the action, and leave it out of a damage roll or any roll that only follows another. Time is counted once: do not repeat it in `set_scene`.

`dc` is the difficulty, when the roll has one: the number the total must meet or beat, which you decide before you roll and never tell the player. With it the result says whether the roll succeeded or failed and by how much, so you do not have to work it out. Give `dc_mode: under` for a roll that succeeds at or below the number (the old editions' ability checks). Leave `dc` out of rolls with no difficulty: damage, hit points, initiative, an ability's value, a random table.
`attempt` says what the roll is for when it tests a task that can fail: `who`, `kind`, `task` (two to twelve words), `failure` (up to 25 words completing "...and failed; ___", the stakes you name before the dice, in the third person with names, never "you"), and optionally `about` (what it concerns; default the place), `closes`, `reopens_if`, `after_minutes`, `scope`, `changed` and `opens` (a blocked way a success opens). It needs a `dc`, and it takes the kind's usual time if you give no `minutes`. The server decides from the total whether the attempt failed, may refuse the roll if this exact attempt was already closed, and writes the record; the result tells you what to narrate. A roll with a `dc` whose label names a task (a lock, a search, a climb, a trap, a recall, a first aid) and no `attempt` is refused, and nothing is rolled. Leave `attempt` out of rolls that are not tasks: damage, initiative, hit points, an ability's value, a random table, an attack.

Never roll damage in the same response as the attack it depends on: roll the attack, see that it hit, then roll the damage in a later call.

Write no text beside a roll that is not story: no rulings, no reasoning about the rules, no remarks on what you are about to do. Put rules details in the `# comment`.

Do not use it for social checks (persuading, deceiving, intimidating, haggling): those go through `social_check`, which needs the words the player has typed for the character.
