<!-- How a failed attempt is read in AD&D 1e (docs/ATTEMPTS.md 8). Adventure mode only. -->
### Failed attempts: AD&D 1e

For the `attempt` of a roll:

- Checks are rolled **under**: thief abilities are percentages, ability checks are d20 at or below the score, and listening or finding secret doors is a number in six. Use `dc_mode: under` and give the number to roll under as the `dc`.
- Map the abilities onto the types: pick locks `lock`; find and remove traps `trap`; climb walls `climb`; hear noise and find secret doors `search`; hide in shadows and move silently `sneak`; open stuck doors and bend bars `force`; binding wounds `treat`.
- Retries: a door or a bend bars attempt may be repeated, each try costing a turn and a risk of noise. Where the rules and your judgment say a thief has had their one chance at a particular lock or trap, give `closes: true` and `reopens_if: the thief gains a level, or better tools`. Searching the same place the same way finds nothing new.
- A changed approach is a different character, better tools or a different method.
