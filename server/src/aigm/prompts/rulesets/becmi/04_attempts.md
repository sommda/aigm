<!-- How a failed attempt is read in BECMI (docs/ATTEMPTS.md 8). Adventure mode only. -->
### Failed attempts: BECMI

For the `attempt` of a roll:

- Checks are rolled **under**: thief skills are percentages, ability checks are d20 at or below the score, and listening or finding a secret door is a number in six on a d6. Use `dc_mode: under` and give the number to roll under as the `dc`. Where the Rules Cyclopedia's general skills are used, they are a d20 roll under the ability too.
- Map the skills onto the types: open locks `lock`; find or remove traps `trap`; climb walls `climb`; hear noise and find secret doors `search`; hide in shadows and move silently `sneak`; forcing a door `force`; first aid `treat`.
- Retries: a stuck door may be forced again at a cost of time and noise. Where your rules say a thief may try a given lock or trap only once per level, give `closes: true` and `reopens_if: the thief gains a level, or better tools`. A failed search or listen is not repeated by the same character in the same place.
- A changed approach is a different character, a better tool or a different way in.
