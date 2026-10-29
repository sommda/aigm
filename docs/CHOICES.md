# AIGM Choices: A Choose-Your-Own-Adventure Interaction

Status: **brainstorm, no code**. Part of the graphical app design; start with [APP.md](APP.md). This document changes
how the player acts: instead of typing every turn, they tap one of a few choices, sometimes a sub-choice, and may
still type their own words within limits. It must keep the feel of free roleplay and stay compatible with the roleplay
design in [ROLEPLAY.md](ROLEPLAY.md). Cost and speed effects are in [TURN_COST.md](TURN_COST.md).

## 1. Goals and principles

1. **Tapping is the main way to play; typing is the escape hatch.** A turn should take seconds on a phone.
2. **Choices are the character's options, not a menu of game actions.** They are written in the story's voice, shaped
   by the situation, the character's personality and what they know.
3. **Choices must not leak.** They never mention hidden facts, never rank themselves, and never reveal which option
   "works". The player learns what works the way the player does now: by reading tells and hints.
4. **Good play is rewarded; guessing is not enough.** Dialogue choices differ in what they appeal to. Reading the NPC
   (their tells, what the hints said) is how you pick the one that lands.
5. **The model remains the game master.** Choices are proposals the GM makes; the GM then narrates whatever is chosen,
   including a typed action that was not offered.
6. **Everything still works as text.** The same flow runs in the terminal client, in test mode and in the web client.

## 2. Anatomy of a turn

A turn now has up to five parts:

1. **Narration**: short and streamed (see section 9). Often one to three paragraphs, not a page.
2. **Mechanics inline**: a dice roll animation when a check happens (the existing `dice_roll` event).
3. **Art and state**: plates, portraits, status changes arrive alongside.
4. **Choices**: two to five cards.
5. **The always-there bar**: Look around, Journal, Map, Character, Rest. These are not choices (section 8).

When the choices arrive the player taps one. If it has sub-choices, a second sheet opens. If it is a dialogue choice,
the sub-choices are the actual lines the character might say.

## 3. The choice model

Each offered choice has a visible part, sent to the client, and a hidden part, kept on the server.

```json
{
  "turn": 41,
  "choices": [
    {
      "id": "c1",
      "label": "Bluff your way past the guards",
      "kind": "talk",
      "target": "Captain Fenn",
      "note": "Risky",
      "children": [
        {"id": "c1a", "text": "\"Lord Vance sent me. Check the seal on the letter.\""},
        {"id": "c1b", "text": "\"Do you know who you're keeping out? Open the door.\""},
        {"id": "c1c", "text": "\"I only need a minute. There's silver in it for you.\""}
      ]
    },
    {"id": "c2", "label": "Slip along the wall to the east door", "kind": "act", "note": "Stealth"},
    {"id": "c3", "label": "Ask Tobin what he knows about the guards", "kind": "talk", "target": "Tobin"},
    {"id": "c4", "label": "Back away and watch the gate for a while", "kind": "wait"}
  ],
  "freeform": {"modes": ["say", "do"], "max_chars": 200}
}
```

Hidden on the server, never sent:

```json
{
  "c1a": {"engages": ["m12"], "quality": "strong", "check": {"skill": "Deception", "dc": 14}},
  "c1b": {"engages": ["m12"], "quality": "weak",   "check": {"skill": "Intimidation", "dc": 14}},
  "c1c": {"engages": ["m13"], "quality": "ordinary", "check": {"skill": "Persuasion", "dc": 12}},
  "c2":  {"check": {"skill": "Stealth", "dc": 13}}
}
```

Fields:

- `label`: at most about 8 words, an imperative or a verb phrase, starting with the verb. Sentence-case, no trailing
  punctuation.
- `kind`: `act`, `talk`, `move`, `look`, `use` (an item or spell), `wait`, `fight`. The client picks an icon from it.
- `note`: an optional short cue the player may fairly know ("Risky", "Stealth", "Costs a spell slot", "Takes an
  hour"). Never a success estimate. Whether a skill name is shown is a setting: on for newcomers, off for a purer
  feel.
- `children`: sub-choices, at most one level deep. For `talk` choices these are lines of dialogue (section 4). For
  other kinds they are variants of the approach ("Pick the lock", "Force the door", "Look for another way").
- Hidden: `engages` (motive ids touched, as in `social_check`), `quality`, and an optional `check` the server can roll
  without asking the model (section 7).

Count rules: two to five choices; at least one that is not a fight or a flight; at least one that fits a quiet or
curious character; when a conversation is under way, one choice is always to say something else (the typed option).
Two to five sub-choices, never fewer than three for dialogue so that there is a real decision.

## 4. Dialogue choices and the roleplay design

[ROLEPLAY.md](ROLEPLAY.md) requires the player to type the words before a social skill is rolled, and rewards good
words through motives and a quality grade. The choice flow keeps both ideas:

- **The words are chosen instead of typed.** The sub-choice text is the player's spoken line. When the player taps it,
  the server writes it into the player message ("I bluff the guard: \"Lord Vance sent me...\""), so the `social_check`
  words gate (at least four words, mostly present in the player's message) passes naturally, and the transcript reads
  as it always has.
- **Quality comes from the option, not from the model's judgment after the fact.** The choice writer (section 6)
  already knows the NPC's motives and tells. It writes each line to appeal to something different and records the
  grade. The server applies that grade as the `quality` of the check, so the reward is decided before the player sees
  the options and cannot drift with the narrator's mood.
- **Reading the NPC is the skill.** One line flatters, one threatens, one offers money, one is plain honesty, one
  pulls on a stated loyalty. Which works depends on the hidden motive and its strength. Absolute motives still bar or
  auto-pass as designed; if a line crosses an absolute motive the server applies the bar, and the narrator plays the
  tell.
- **Typed words still count.** The free-text option goes through the original path: the model grades the words and
  names the motives they engage. A player who writes their own line can beat the written ones. Typed play is also the
  only route to something the options did not anticipate.

### 4.1 Writing options that teach rather than give away

Rules for the choice writer, to put in its prompt and to test:

1. **Do not make the best line the longest, the most polite, or the last.** Randomize the order, keep the lengths
   within about 20 percent of one another, and vary the register.
2. **Every line must be plausible.** No obvious fools. A weak line is weak because it pushes the wrong lever, not
   because it is silly.
3. **At most one line should be strong, and sometimes none is.** If every NPC always has a winning line, the game is a
   quiz. Sometimes the right move is to not talk yet (ask Tobin first), to leave, or to gather what moves them.
4. **Lines may be good for the wrong reason.** A strong line can raise another problem (the guard remembers you).
5. **Lines carry the character's voice.** Use the personality fields on the sheet so a blunt character's options are
   blunt.
6. **No hints in the text.** The option does not repeat a tell ("since he's afraid of the harbor..."). The narration
   shows the tell; the options only offer ways to act on it.
7. **Respect hints and the compendium.** Options may use what the player knows, never what they do not.

### 4.2 Motives and absolute cases

Where a motive is `absolute` against the character's likely approach, the options should show it by *offering fewer
doors*, not by labeling: perhaps every line is weak, and the strong move is to find another way. The tell in the
narration is what makes that fair.

## 5. The free-text option

Free text keeps the sense of roleplay. It needs limits so that it stays cheap and safe on mobile.

- **Two modes**: **Say** (the character speaks; goes through the words gate and quality grading) and **Do** (a
  described action). A toggle on the field; the client prefixes nothing, the server records the mode.
- **Length**: at most 200 characters on phones (the field is a small sheet), more on PC. The cap is enforced on the
  server too.
- **Rate**: a per-day count by tier (for example generous on the top tier, a handful on free). Show the count; do not
  surprise the player. Typed turns are the most expensive because the narrator must adjudicate unaided
  ([TURN_COST.md](TURN_COST.md)).
- **Moderation**: input is checked before it reaches the model, and the narrator prompt treats the text as the
  character's words, not as instructions (the usual prompt-injection guard). Out-of-character text is handled by a
  fixed reply, not narrated.
- **Mapping**: after the narrator reads a typed action, it may resolve it directly. If the action implies a check, it
  calls the check tool as today.
- **Suggestions**: the field shows a placeholder drawn from the choices ("or say something else, like..."). Never
  auto-fill it.

## 6. Who writes the choices

| Approach | How | Latency | Cost | Quality |
|---|---|---|---|---|
| A. The narrator, in the same call | the narrator ends its turn with an `offer_choices` tool call or structured block | adds a few seconds before the turn is "done" | cheapest per call, but longer outputs | best fit to the narrator's intent; the narrator also does everything else |
| **B. A separate choice writer (recommended)** | a second, small call after the narration finishes, with a compact context | runs while the player reads; invisible if narration takes longer to read than the call takes | one extra small call (a few thousand input tokens, a few hundred output) | focused prompt, easy to test and tune, and a clean fallback |
| C. Rules engine only | choices from templates (every scene has Look, Talk, Leave) | none | none | too samey; dialogue lines impossible |

### 6.1 Recommended: the choice writer

After the narrator's final reply, the server runs the choice writer on the cheap model. Its context:

- the final narration and the last few turns;
- the briefing (including `GM only` motives, since it writes the grades);
- the compact party sheet (class, skills, personality, resources);
- the open leads and the story's current beat ([STORY.md](STORY.md));
- a `next_beat` note the narrator leaves at the end of its reply (one line: "the guards are suspicious; the east door
  is unwatched"), so the writer knows where the scene is going without the narrator's hidden reasoning;
- the rules of section 3 and section 4.1.

Its output is the structured object in section 3 (visible and hidden parts). The server validates it (counts, lengths,
that every `engages` id exists and belongs to a person present, that targets are in the scene, no hidden fact text
appears in visible fields), repairs trivial problems, and retries once. If it still fails, fall back to generic
choices plus the free-text option, and log it.

The client shows the narration immediately and the choice cards as soon as the `choices` event arrives, usually before
the player has finished reading. Reading a few paragraphs takes ten seconds or more, which hides the call.

### 6.2 Why not let the narrator do it

Approach A has one advantage (the narrator's intent) and three costs: it lengthens the critical path before the turn
can end, it makes the narrator prompt and tool list larger, and a narrator that skips the call leaves the player with
nothing to tap. The `next_beat` note recovers most of A's advantage.

## 7. Protocol changes

### 7.1 Server to client

A new SSE event after the narration, and optionally one for the typed-input state:

```
event: choices
data: {"turn": 41, "choices": [...], "freeform": {"modes": ["say", "do"], "max_chars": 200}}
```

Hidden fields stay in the game state: `GameState.pending_choices` holds the full object, stored with the save so a
reload shows the same options. A client that reconnects after a dropped connection gets the `choices` event again as
part of the re-attached turn (see [APP.md](APP.md) section 6).

### 7.2 Client to server

`POST /chat` gains a structured action beside `message`:

```json
{"session_id": "default", "action": {"turn": 41, "choice": "c1", "sub": "c1a"}}
{"session_id": "default", "action": {"turn": 41, "say": "Fine, I'll tell you the truth."}}
{"session_id": "default", "action": {"turn": 41, "do": "I climb onto the cart and hide under the tarp."}}
```

Rules:

- The server checks `turn` against the current turn and `choice` and `sub` against `pending_choices`. A stale or
  forged choice is refused.
- The server turns the action into the player message stored in history (for a dialogue choice, the quoted line with a
  short lead-in), exactly as if it had been typed. History therefore needs no new message types, and the terminal
  client and test mode keep working with plain `message`.
- The hidden part is attached to the turn as a note for the narrator: "the player chose: Bluff, line 1; check
  Deception DC 14, quality strong, engages m12".
- Plain `message` still works for compatibility and for the terminal client.

### 7.3 Terminal client and test mode

The terminal client gets a simple rendering of the same event (numbered list, answer with a number) so the flow can be
exercised without the web client. The scripted GM learns to offer fixed choices. This lets the existing end-to-end
tests cover the new protocol.

## 8. The always-there bar

Some actions are not choices and should not take one of the five slots:

- **Look around** and **Examine**: a free query answered from the briefing, with no turn spent, or a cheap narrator
  reply. Prefer cheap: the choice writer can attach "things you can examine" to the scene so the bar can list them.
- **Journal**, **Map**, **Character**, **Inventory**: client-only screens fed by existing routes.
- **Rest/wait**: appears as a choice only when sensible.
- **Back**: inside a sub-choice sheet.

## 9. Narration style for mobile

The choice flow only works if turns are short.

- **Length**: 80 to 200 words per turn by default; longer for chapter openings and big reveals. Enforce in the prompt
  and with a soft token cap; do not rely on the model's instinct.
- **No closing question.** The current prompts end with "What does X do?"; the choices replace it.
- **Beats**: one idea per turn, ending on a situation that invites a choice.
- **Pacing control**: a "Continue" tap for pure-narration beats (an arrival, a cutscene) where there is nothing to
  decide, so the player is not forced to pick filler.
- **Reading time as a resource**: the server can start the choice writer, the scribe ([TURN_COST.md](TURN_COST.md))
  and art jobs while the player reads.

## 10. Failure modes

| Failure | Guard |
|---|---|
| Choices all look alike | the writer prompt requires distinct `kind`s; a validator rejects a set with one kind and no `talk` or `look` |
| The right option is always the same position or length | shuffle server-side; a test measures the quality-position correlation across replays |
| Hidden information leaks into labels | a validator compares visible text against `hidden` fact text and motive text; the first release also blocks proper nouns the player has not met |
| Choices ignore the current scene | the writer gets only the final narration and scene state; the validator checks targets are present |
| A tapped option does not match the narration that follows | the narrator receives the exact line and hidden notes; a replay test checks the line appears or is paraphrased |
| The player feels railroaded | always show the free-text option; keep its limits visible; sometimes offer a wildcard choice |
| Typed turns become the main cost | tiers cap typed turns; choices carry pre-built checks (cheaper) |
| Dialogue choices become a quiz | rule 3 of section 4.1: some turns have no winning line |

## 11. Interaction with other systems

- **Roleplay modes** ([ROLEPLAY.md](ROLEPLAY.md) step 5): the Session 0 `set_roleplay` setting maps to the mix of
  typed and chosen words: `required` means every social check needs the typed or chosen words; in choice play the
  chosen lines satisfy it. `off` skips the words entirely.
- **Story and quests** ([STORY.md](STORY.md)): the writer receives the open leads; at least one choice per turn may
  serve a lead when one is relevant, never forced.
- **Compendium and hints**: choosing "Ask Tobin about the guards" is a normal turn and produces facts the compendium
  records; the compendium can also offer "ask about this" shortcuts that become choices.
- **Combat**: a round's choices are the actions (attack, cast, defend, move, use item), with a target sub-choice.
  Later a tactical grid replaces the target sheet with a tap on the map.
- **Campaign packs** ([CAMPAIGNS.md](CAMPAIGNS.md)): authored set pieces may carry their own choice cards, passed to
  the choice writer as required or suggested options; the writer adapts their wording to the moment and adds the
  hidden grades.
- **Art**: choices have no art in the first release; a plate may follow a major choice.
- **Saves**: `pending_choices` is part of the save so that loading shows the same options and the same hidden grades.

## 12. Open questions

1. Show skill names on choices by default, or only as a setting?
2. Should the narration for a tapped dialogue line quote the line back verbatim, or paraphrase it? Quoting is clearer
   and keeps the words gate honest; it is also a little repetitive.
3. How many typed turns per day on each tier, and should unused ones carry over?
4. Do the hidden `check` objects come from the choice writer or from a small rules module (skill and DC from the kind
   and the situation)? A module is more predictable; the writer is more flexible. A hybrid (writer picks the skill,
   the module sets the DC from a table by difficulty word) is probably right.
5. Should a choice screen offer an "undo" in the first minute after a tap? It is cheap to support (re-run the turn)
   but it doubles cost if abused.
6. For veteran players who prefer typing only, is there a "typed mode" that hides the cards and keeps the same rules?
