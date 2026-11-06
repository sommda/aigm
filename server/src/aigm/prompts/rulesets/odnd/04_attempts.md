<!-- How a failed attempt is read in OD&D (docs/ATTEMPTS.md 8). Adventure mode only. -->
### Failed attempts: OD&D

For the `attempt` of a roll:

- Checks are rolled **under**: a thief ability is a percentage and a plain ability check is d20 at or below the score. Use `dc_mode: under` and give the number to roll under as the `dc`. A 1-in-6 chance (listening, finding a secret door) is a d6 against a `dc` of 1 or 2, also roll under.
- Map the thief's abilities onto the types: open locks `lock`, find and remove traps `trap`, climb walls `climb`, hear noise `search`, hide and move silently `sneak`. Breaking down a door is `force`; listening and searching are `search`.
- Retries: most things may be tried again at a cost of time (and noise: a door forced or a lock worked at in a corridor wakes what sleeps nearby). Where your tables say a thief may try a given lock or trap once until they gain a level, give `closes: true` and `reopens_if: the thief gains a level, or better tools`.
- A changed approach is a different character, a different tool (a crowbar, a lantern, a ten-foot pole) or a different way in; time passing for a wandering monster check is not.
