# Playtest mode

Setting up a situation to test a feature (a locked door at midnight, a level 7 party, a rival already hostile) takes
many turns of play. Playtest mode lets a developer tell the GM what the game should look like and have it done.

It exists only on a debug server (`aigm --debug`); without `--debug` the endpoint does not exist.

## 1. Entering and leaving

- `/playtest` in the terminal client calls `POST /debug/playtest` for the session. It needs a game in progress (not
  Session 0) and no turn running, otherwise the server answers 409. `{"enabled": false}` switches the mode off from
  outside, for when the GM will not.
- From then on every message goes to the GM as an instruction. The GM leaves the mode only when told to (for example
  "exit playtest mode"), by calling its `end_playtest` tool.
- The flag is part of the saved game (`playtest`, written only while it is on), so a restart or a reload keeps it.

## 2. What changes

- `prompts/system/playtest.md` goes first in the system prompt and says it overrides the rest: the GM is the
  developer's setup assistant, does what is asked (large changes, finishing scenes, jumping chapters) without rolling
  or refusing, replies in a line or two out of character, and may show hidden facts. The prompt files that make the GM
  stay in character and steer the story are left out in this mode (`PLAYTEST_DROPPED` in `game.py`); the tool
  guidance stays.
- The world notes, the sheets and every adventure tool stay, so the GM sees and changes the real state. Three tools
  are added, offered and accepted only in this mode (`Tool.playtest_only`):
  - `end_playtest` leaves the mode and asks for a curator pass (section 3).
  - `playtest_time` sets the clock to any moment, earlier ones too (`World.reset_time`).
  - `playtest_hero` sets a party member's level, XP and class levels directly.
  - `playtest_story` (story games) jumps to a chapter, sets any quest to any status and sets whether the goal is known.
- Everything else is done with the usual tools: `establish`, `key_item`, `set_scene`, `update_character`,
  `set_combat`, `set_motive`, `award`, `pass_time`.

## 3. Leaving: the curator pass

Ending the mode sets `pass_now` on the game state (not saved). The next background run treats a pass as due however
little narration has built up, as long as something is unprocessed: it extracts from the playtest exchange, reconciles
and fixes the world, as Session 0's end builds the world. The Looks, place and item sweeps run on their usual cue.

## 4. Limits

- The playtest exchange stays in the conversation, so the curator may digest it as story. The prompt tells the GM it is
  out of the story, which is usually enough for the narration; a clean test is a save made after leaving the mode.
- There are no tools yet to delete a person or fact, add or remove a party member, or change the ruleset or the story's
  chapter. Add them when a test needs them.
