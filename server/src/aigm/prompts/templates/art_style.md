<!-- Offered in Session 0 only when portraits are on. {{default}} and {{styles}} are filled from aigm/art.py. -->
## Portraits

Characters in this game get portraits, all in a single art style that is the same for the whole game. For this ruleset the default style is **{{default}}**. The player can pick another:

{{styles}}

Mention this once, in a single short line, when you settle the ruleset (for example: "Portraits will use this era's default style, {{default}}; say if you would rather have something else, such as anime, or none at all."). Do not list every style unless the player asks. If the player picks a style, or asks for no portraits, call `set_art_style`. If they say nothing about it, leave it alone: the default is used. The style is final once the adventure begins.
