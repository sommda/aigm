<!-- How a failed attempt is read in AD&D 2e (docs/ATTEMPTS.md 8). Adventure mode only. -->
### Failed attempts: AD&D 2e

For the `attempt` of a roll:

- Thief skills are percentages rolled **under**; ability checks are d20 at or below the score, and proficiency checks are d20 at or below the ability adjusted by the proficiency's modifier. Use `dc_mode: under` and give the number to roll under as the `dc`.
- Map the skills onto the types: open locks `lock`; find or remove traps `trap`; climb walls `climb`; detect noise and find secret doors `search`; hide in shadows and move silently `sneak`; open doors and bend bars `force`; healing and herbalism `treat`; the crafts and survival proficiencies `repair`.
- Retries: a failed proficiency or thief skill check may be repeated when the check was not an all-or-nothing one, each try costing time (a turn) and risking noise. Where the rules say a thief may not retry the same lock or trap until they gain a level, give `closes: true` and `reopens_if: the thief gains a level, or better tools`.
- A changed approach is a different character, better tools, a different proficiency or a different method.
