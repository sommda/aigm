<!-- How a failed attempt is read in B/X (docs/ATTEMPTS.md 8). Adventure mode only. -->
### Failed attempts: B/X

For the `attempt` of a roll:

- Checks are rolled **under**: the thief's skills are percentages, ability checks are d20 at or below the score, and listening or finding a secret door is a number in six on a d6. Use `dc_mode: under` and give the number to roll under as the `dc`.
- Map the skills onto the types: open locks `lock`; find or remove traps `trap`; climb sheer surfaces `climb`; hear noise and find secret doors `search`; hide in shadows and move silently `sneak`; forcing a stuck door `force`; healing by hand `treat`.
- Retries: a stuck door may be tried again (each try is a turn, and the noise is a risk). Where your rules say a thief gets one attempt at a lock or trap until they gain a level, give `closes: true` and `reopens_if: the thief gains a level, or better tools`. Listening and searching are tried once per person per place unless the circumstances change.
- A changed approach is a different character, a different tool (a crowbar, a lantern, a ten-foot pole) or a different way in.
