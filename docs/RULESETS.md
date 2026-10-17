# AIGM Rulesets

Status: **implemented**. This builds on [BACKEND.md](BACKEND.md) (prompts, tools, saves) and [API.md](API.md).

## 1. What it does

In Session 0 the player chooses the rules the game is played under. **D&D 5.5e (the 2024 rules) is the default**, but
any earlier edition of Dungeons & Dragons or either edition of Pathfinder can be picked instead. The choice does two
things:

1. **The mechanics.** The GM runs the game by that edition's rules: how characters are built, how attacks, saves and
   death work, what the armor class number means, how advancement and magic work, and how lethal it is.
2. **The period feel.** Each older ruleset also brings the *feel of its era* into the GM's descriptions, as style rather
   than as year numbers: the GM never says "this is 1979", but an AD&D 1st Edition game reads like a late-1970s dungeon
   crawl, a B/X game like an early-1980s module, a 3rd Edition game like the d20 boom of 2000. The rules and the voice
   are chosen together, so picking an old edition gets you its nostalgia too.

## 2. The catalog

The catalog is `aigm/rulesets.py`. Each ruleset has an id (also its prompt folder), a name, a short name for status
lines, a family, and the year it first appeared.

| Id | Ruleset | Year | Feel of the period |
|---|---|---|---|
| `odnd` | Original D&D ("white box") | 1974 | wargame roots, megadungeon, pulp fantasy, Law versus Chaos |
| `basic` | D&D Basic/Expert, "B/X" | 1981 | the classic module, keyed rooms, plain bright voice |
| `becmi` | D&D BECMI and Rules Cyclopedia | 1983 | red box, cartoon-bright heroics, a world of gazetteers, rising to rulership |
| `adnd1e` | Advanced D&D, 1st Edition | 1977 | Gygaxian diction, sword-and-sorcery, deadly dungeons, "backward AC" |
| `adnd2e` | Advanced D&D, 2nd Edition | 1989 | epic novelistic fantasy, campaign settings, kits, gothic moral weight |
| `dnd3e` | D&D 3rd Edition | 2000 | the d20 System, kitchen-sink spectacle, feats and builds |
| `dnd35e` | D&D 3.5 Edition | 2003 | crunchy tactics, splatbooks, magic-item economy |
| `dnd4e` | D&D 4th Edition | 2008 | powers and roles, "points of light", bold video-game-like fights |
| `dnd5e` | D&D 5th Edition | 2014 | warm, character-driven, "actual play" voice |
| `dnd55e` | D&D 5.5 Edition (2024), **default** | 2024 | modern, cinematic, inclusive |
| `pf1e` | Pathfinder, 1st Edition | 2009 | adventure paths, archetypes, gloriously weird Golarion |
| `pf2e` | Pathfinder, 2nd Edition (Remaster) | 2019 | three-action cinematic tactics, degrees of success |

Armor class follows the edition: the old editions (OD&D, Basic, BECMI, AD&D 1e and 2e) use **descending AC** ("lower
is better", "backward AC") with THAC0 or an attack matrix, and every character sheet and combat summary is written
that way. Later editions use ascending AC.

## 3. How it works

### Prompts

Each ruleset has two files in `prompts/rulesets/<id>/`:

- `01_rules.md` (heading `## Ruleset: <name>`): the mechanics: character creation (ability score methods, races,
  classes, hit points, AC convention), the core resolution system, combat, saves, death, magic, advancement, and the
  edition's own danger level. It is written for the GM as a reminder and a set of choices, not as a rulebook.
- `02_era.md` (heading `### Period feel: ...`): the style: diction, tropes, fiction touchstones, the look of the era's
  illustration, and the tone, all as things to hint at while staying in the fiction.

The system prompt is built from, in order: the common files (`system/common`), the chosen ruleset's two files, then the
files of the current mode (`system/session_zero` or `system/adventure`). Everything edition-specific was moved out of
the
common and mode prompts into the ruleset files, so those hold only what is true of every ruleset (digital adaptations,
tone, tracking, fairness). `01a_ruleset.md` in Session 0 tells the GM how to offer the choice.

The files follow the usual prompt conventions: `AIGM_PROMPT_DIR` can override or add rulesets' files, and the context
viewer ([CONTEXT.md](CONTEXT.md)) shows the ruleset's parts like any others.

### State and tool

- `GameState.ruleset` holds the id (default `dnd55e`) and is saved with the game (`ruleset` in the save file; saves from
  before rulesets existed load as `dnd55e`; an unknown id makes the save corrupt). The file format version is unchanged
  because the field is optional.
- `set_ruleset(ruleset)` is offered in Session 0 only. It changes `state.ruleset`; because the loop builds the system
  prompt for every request, the next request already carries the new rules and period feel. Calling it again with a
  different id re-chooses (the result reminds the GM to rebuild any characters made under the old ruleset). Once the
  adventure begins, the choice is fixed: the tool is no longer offered.
- The campaign record shown to the GM at the start of the adventure has a `### Ruleset` section naming it.
- The server reports the ruleset in `message_start` and `message_end` (`ruleset` and the short `ruleset_name`), in
  `GET /chat/history`, `POST /chat/new` and the restore response. The client shows it in the status line (for example
  `mode: Session 0 · AD&D 1e`).
- In `--test` mode, `ruleset <id>` calls the real tool, so the whole flow can be tried without an API key.

### In the conversation

The GM raises the ruleset in its opening message, with the first setting question, recommending 5.5e and saying that
older editions are available and give the game their period's look and feel. A curious player gets a few lines on how
an edition plays. When the player decides (or says "you decide", which means the default), the GM calls `set_ruleset`
and confirms, then builds characters the way that edition does. In Session 0 the GM speaks plainly and out of
character, but suggests settings and hooks that suit the era.

## 4. Limits and notes

- The rules files are condensed reminders written from the model's knowledge of each edition; they do not reproduce
  rulebook text. Where the model remembers a rule differently, the files win, and they are easy to correct.
- The adventure's world knowledge base and the curator do not know the ruleset yet. The world's content is chosen by the
  GM and the campaign record, so a 1e game's world already reads as 1e, but the curator's own prompts are
  edition-neutral.
- Pathfinder's default setting is Golarion, and Basic/BECMI's is the Known World, but a custom setting is always fine.
- To add a ruleset: add a `Ruleset` to `aigm/rulesets.py`, add `prompts/rulesets/<id>/01_rules.md` and `02_era.md`, and
  list it in `prompts/system/session_zero/01a_ruleset.md`. Tests check that every catalog entry has both files and is
  named in the Session 0 text.

## 5. Possible later work

- Per-ruleset random tables and procedures as tools (reaction and morale rolls, the old exploration clock, wandering
  monsters), and automated THAC0 and saving-throw lookups, so the GM does less arithmetic.
- Letting the world curator and the bootstrap prompts see the ruleset, so the generated world's monsters, scale and
  tone match the edition even more closely.
- More editions or variants (Holmes Basic, Pathfinder Playtest, "retro-clones"), and mixed-edition house rules.
