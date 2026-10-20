Roll dice using d20 expression syntax and return the result. Use it for any random outcome: attacks, ability checks, saving throws, damage, random tables.

Examples: `1d20+5`, `4d6kh3` (roll four, keep the highest three), `2d8+1d4+3`. Use `2d20kh1` for advantage and `2d20kl1` for disadvantage. Percentile dice are `1d100`. Add a trailing `# comment` to label the roll, for example `1d20+3 # stealth check`.

Every call needs a `narration`. It is shown to the player as story text just before the dice appear, so it must say what is happening and what is at stake. A call without one is refused and nothing is rolled.

Never roll damage in the same response as the attack it depends on: roll the attack, see that it hit, then roll the damage in a later call.
