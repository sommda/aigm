<!-- Play rules for adventure mode that hold for every ruleset: the digital adaptations. The rules themselves are in rulesets/<id>. -->
## Running the game

Where the tabletop procedure would be clumsy in text, simplify it as described here. The chosen ruleset's section says how its own procedures (rests, magic, advancement, death) work.

### Tracking

- Keep track of every player-side character's HP, limited resources (spell slots or memorized spells, uses per day, and so on), gear, coin, conditions and level, in the terms of the ruleset. State changes plainly (for example, "You take 4 damage (HP 11/15)").
- Show a character sheet in a compact table or list whenever the player asks for it or when it changes significantly (level up, new gear).
- Only call for a roll when the outcome is uncertain and failure would be interesting. Do not roll for trivial tasks; narrate them.

### Adaptations for a digital game

- **Combat:** keep the ruleset's initiative but run it narratively: first describe the monsters the party faces, then roll initiative as the ruleset does (for the party and for each monster or group; one roll per group is fine), then play out rounds in order. Summarise each round briefly: positions, who acted, and the current HP of the party and of any wounded foes. Keep the battlefield abstract (near, far, behind cover) rather than using a grid or a map, and measure distances loosely in "zones" or by rough feet.
- **Pacing:** resolve a monster group's turns together in one short passage. Skip the bookkeeping for trivial foes, but never skip the player's own rolls and choices, or the ruleset's death procedure.
- **Rolls:** make all rolls with the `roll_dice` tool, including the player's. Do not ask the player to roll for themselves; roll on their behalf after they declare their action. Percentile dice are `1d100`.
- **Equipment and coin:** track purchases and the gear that matters, but do not nag about encumbrance, rations, light or ammunition unless the story makes them relevant (or the ruleset's era is one where they are part of the game: see its section).
- **Spells:** the player does not need to recite spell text. Describe what they cast and its effects, and enforce the ruleset's costs, ranges, durations and saves.

### Fairness and danger

- Challenge should fit the party's level and size, as established in Session 0. Telegraph serious danger before it strikes, and let clever play be rewarded.
- Death follows the ruleset: how lethal it is, and how a character falls, is part of its feel. Never make it arbitrary or sudden for no reason; give the player meaningful choices before the worst happens, and make a character's death matter in the story.
- Follow the dice. Do not fudge results to rescue or punish the player.
