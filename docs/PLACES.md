# AIGM Place Looks and Pictures: Design

Status: **spec; build steps 1 to 4 (section 12) are done**.
Third step toward graphics, after the Looks ([LOOKS.md](LOOKS.md)) and the portraits ([PORTRAITS.md](PORTRAITS.md)).
It gives every location a detailed written description, shows it in the compendium and uses it to make a landscape
picture in the game's art style. It reuses almost all of the portrait machinery (the image generator, the image
library, the pending-work plumbing, the app's picture component) and adds what is different about places: their
descriptions, what may be shown about them, and the picture's shape.

## 1. Goal

Each location the player has discovered gets (a) a **Look**, a detailed description of how it appears to a visitor,
and (b) a **picture** made from it, wider than it is tall and a little larger than a portrait, in the same art style as
the game's portraits. Both appear on the location's compendium entry. For now every discovered location is pictured.
Later the pictures may be limited to major places, so the design keeps a place's scale in its data and puts the
decision behind one function (section 8.3).

### Non-goals (this step)

- Maps, floor plans or tactical grids ([ART.md](ART.md) 5). A picture is a view, not a diagram.
- Pictures of items, factions, concepts or scenes in play (a fight, a moment of a story).
- People in the pictures. Places are shown empty, so a picture never contradicts a portrait or the narration.
- Showing pictures in the terminal client.
- Revising a place's description as the story changes it (a burned inn). The record keeps what is needed ("rev"), the
  revision pass is a later step (section 11).

## 2. Decisions already taken

| Decision | Source |
|---|---|
| Locations get detailed descriptions, like the Looks of characters | the product owner |
| The descriptions appear on the compendium pages and are used to build the image prompts | the product owner |
| Images are landscape and slightly larger than the portraits, in the same overall style | the product owner |
| Every location is pictured as it enters the compendium; a "major places only" limit may come later | the product owner |
| The prompt is built in the image pipeline; generation is background work that never delays a turn | portraits |
| A place's picture is carried as `portrait` in the API, with a `shape` | the product owner |
| The summary of the party's location goes into every request, so the narration stays within it | the product owner |
| The status tab shows the picture of the party's current location, prominently | the product owner |
| The describer uses **known facts only**; a place the player has only vaguely heard of waits | the product owner |
| The landscape size, 1536 x 1024 | the product owner |

## 3. Terms

- **Place Look**: the written description of a location. It is the same record as a person's Look
  ([LOOKS.md](LOOKS.md) 3) with a tag set suited to places (section 4). "Look" now means how any person or place
  appears.
- **Picture**: a generated image of a place. It is stored as a `Portrait` record, the same data as a person's portrait
  (the record says what image, which style and which Look revision, and nothing about faces). The name stays for now;
  see the open questions.
- **Visible**: the compendium's rule: the player has been told a fact about the place, so it has an entry
  ([COMPENDIUM.md](COMPENDIUM.md)).
- **Describable**: visible, and known well enough to picture (5.1).

## 4. The place Look

### 4.1 Fields and tags

The record is `Look`, with the usual `summary` (up to 25 words), `description`, `tags`, `rev`, `state` and `source`.
The description is **90 to 140 words**, prose, present tense, about what a visitor sees on arriving. Tags depend on the
entity's kind, so the validator chooses the tag set by kind:

| Tag | Kind | Values |
|---|---|---|
| `scale` | controlled | `room`, `building`, `site`, `district`, `settlement`, `region` |
| `setting` | controlled | `urban`, `rural`, `wilderness`, `underground`, `waterside`, `sea`, `interior`, `other` |
| `climate` | controlled | `temperate`, `cold`, `hot`, `arid`, `wet`, `magical`, `unknown` |
| `architecture` | free text, 12 words | what is built there and of what |
| `terrain` | free text, 12 words | the land, water or floor |
| `flora` | free text, 12 words | plants and growth, or none |
| `light` | free text, 12 words | the usual light and colors |
| `mood` | free text, 12 words | the feeling of the place |
| `features` | list, at most 5 | the things a painter would draw |

`scale` is also what a later "major places only" limit reads (section 8.3). A person's Look keeps its own tags;
nothing about people changes.

### 4.2 Writing rules

The rules of [LOOKS.md](LOOKS.md) 3.1 carry over: only what is visible, no game terms, no product names, never "you" or
"the party", the place's name used in the description, no real people or franchises. Specific to places:

- **What is shown.** The view from where a visitor first stands: the outside of a building, the approach to a
  settlement, the whole of a room. A place made of smaller places (a town of streets, an inn of rooms) is described as
  a whole, from outside, and its parts are described on their own.
- **No people, no text.** No figures in the description beyond "empty" or at most distant, unnamed crowds; no signs or
  writing a painter would have to draw.
- **No time of day or weather,** unless the place is always so (a perpetual storm, a lit cavern). Pictures are
  made once and shown whenever the player looks, so they show the place's usual light.
- **No secrets.** Nothing the narration has not told, except as section 5 allows.
- **Distinct from its neighbours.** Two places the game has already described must not read as the same picture (the
  same check as for people: the same controlled tags and a very similar summary are rejected and rewritten).

### 4.3 Search text

A place's canonical `search_text` (version 1, for the later similarity library) is, on one line:

```
<scale> <setting> <climate> | <summary> | <architecture>; <terrain>; <flora>; <light>; <mood> | <features, comma-joined>
```

## 5. What the describer may see

This is the main difference from people. A person's appearance is never a secret, so the describer was allowed to use
hidden facts about how they look. A place's hidden facts are its secrets (a vault under the mine, a smugglers' cellar),
and a picture would give them away. So the describer is given **known facts only**:

1. **Every known fact about the place** and about the places that contain it (its context: the region and the town).
2. **The narration** that mentions the place, so the description fits what the player has just read.
3. **The campaign setting** (its tone and period) and the ruleset's era, so a harbor looks like this game's harbor.
4. **The summaries of the places the game has already described**, only to keep new descriptions distinct.

It is **never** given hidden or hinted facts of any aspect, motives, or the plot, not even an `overview` the party has
not yet been told. The prompt says to invent ordinary visible detail where the facts are thin, and to avoid anything
that would suggest what the player has not been told (a hidden door, a cracked foundation that matters to the plot).
Invented detail becomes canon: see 7.

### 5.1 Enough to picture

A known fact is not always something a painter can use. "Some say the old mine is haunted" is a rumor, and a place
the player knows only by rumor is not described, or pictured, until later. A place is **describable** once the player
knows at least one fact of a *visual* aspect about it: `overview`, `items`, `approach`, `entry`, `interior` or
`layout`. Arriving in a place reveals its `overview` and `items` facts ([WORLD.md](WORLD.md), `ARRIVAL_ASPECTS`), so
a place the party has been to is nearly always describable. Facts of the other aspects (`history`, `inhabitants`,
`tensions`, `economy`, `leaders`, `connections`, `hazards`, `discovery` and so on) still go to the describer once a
visual fact makes the place describable, but do not make it so on their own. The rule is **strict** (decided): a fact
with no aspect never counts, however plainly it describes the place. The list is a constant (`VISUAL_ASPECTS`) so
it can be tuned. A place that is not yet describable keeps its compendium entry, with its facts
and no View.

## 6. When a place is described

A place is described when it **first becomes describable** (5.1), not when it is created. This differs from people, who
are described as soon as they are mentioned, for two reasons: the compendium rule says what the player may see, and
most places the world creates ahead of play are never reached, so describing them all would be wasted calls.

- The sweep runs after a turn, in the same place as the Looks sweep, and takes at most **6 places per call, 4 calls at
  a time, 12 places per sweep**, in this order: the party's current location, places named in the last narration,
  places just made describable, then the rest (a save that predates this feature catches up over a few turns).
- It never raises and never blocks a turn. Failures back off for 2 turns, as for people.
- Results are applied between turns through the world's op list, with `SetLook` extended to places (and `ReviseLook`
  for later).
- **The campaign opening** is known from the start, so the first location is described after the first turn.

## 7. Staying consistent

- **The GM sees the summary** of the place the party is in in **every request** (a line in the world briefing, with the
  same instruction as for people: stay within it, add detail freely, contradict nothing). The description is written
  *after* the narration that made the place describable, so it is built from that narration, and from then on the
  narration is built from it.
- **Detail invented by the describer is canon,** as for people, and becomes known to the GM through the briefing line.
- **Later narration that contradicts it** (the inn "had stone walls" and the story says timber) is the reviser's job,
  built as for people (a word gate, then a model check, then a new `rev`). That is a later step; until then the
  description may drift from later narration, and the picture with it.

## 8. The picture

### 8.1 Shape and size

Landscape, **1536 x 1024** (3:2): about one and a half times the pixels of a 1024 x 1024 portrait. The size is a
setting, `AIGM_PLACE_IMAGE_SIZE`, because the configured model's accepted sizes are learned in step 1 (section 12).
The size is part of the image id, so portraits and views never collide.

### 8.2 The prompt

Built in `art.py` by `build_place_prompt(look, style, names)`, in the same parts as a portrait's:

1. **The style direction**, the same text for the whole game. Directions written for faces (the anime one speaks of
   "character art", the sketch one of "a portrait") get a `place` variant, so each style has the text to use for
   views. The rest are used as they are.
2. **Framing for a view**: a wide establishing view of one place, seen from where a visitor first stands, nothing
   cropped awkwardly, the horizon level, the subject centered and clear, **no people, no figures, no creatures in the
   foreground, no text, signs or writing, no border, no watermark**.
3. **The place**: the Look's summary, its controlled tags (scale, setting, climate), then the description with the
   place's name replaced by "the place" (the same scrub as for people, so a name cannot pull a famous setting into
   the picture).
4. **The closing reminder** to keep to the style.

### 8.3 Which places

`place_wanted(entity)` decides whether a visible place is pictured. It returns **true for every location** for now.
Its inputs are what a later limit needs: the Look's `scale`, whether the place is a story location, how often the party
has been there. A setting `AIGM_PLACE_IMAGES` (`all`, `major`, `none`) is added when the limit is, and not before.

### 8.4 Pipeline

The portrait pipeline ([PORTRAITS.md](PORTRAITS.md) 8) with these changes: jobs for places join the same sweep, in this
order: the party, **the place the party is in** (the status tab shows it prominently, so it does not wait behind the
people), the people in the scene, the other people, then the other places, newest first. The same two-at-a-time limit
and the same sweep size apply. The record is the same `Portrait`, kept on `Entity.portrait`, now allowed for
locations; a prompt of the place kind and the place size are used; failures, staleness and the 20-turn limit on
replacements are unchanged, except that a refused view is not retried with a softer prompt (there is none), only
recorded. Pictures are made after the Look, so a place needs its description first, and so only describable places
(5.1) are pictured.

## 9. The API

- `GET /compendium/entities/{id}` for a location gains `look` (`summary` and `description`, as for people) and
  `portrait` in the form [PORTRAITS.md](PORTRAITS.md) 9 gives, with one more field, `"shape": "landscape"` (people's
  are `"square"`), so a client sizes the frame without knowing the entity kind.
- `GET /portraits/{file}` serves a place's picture once the place is visible, as it does for people.
- `GET /status` carries the same `portrait` and the `look` on its `location`, so the status tab's place page can show
  where the party is (section 10).
- Compendium list rows are unchanged.

## 10. Clients

- **Compendium, location entry**: the picture across the top of the entry, up to **360 px** wide (240 px high) on a
  desktop and the width of the column on a phone, with the **View** text (the description) below it, above the facts.
  While pending, a quiet frame with the place's name and "Painting a view..."; with none coming, nothing.
- **Status, the place page**: the picture of the party's current location, **prominently**: the full width of the page
  (up to 720 px, 480 px high) above the place's name, with the View text below it, or the pending frame while it is
  made. This is the first thing on the tab. The picture changes when the party moves.
- The component is the one that shows portraits, told the shape. A picture that fails to load falls back to the frame.
- The terminal client shows the **View** text in the compendium entry and nothing else.

## 11. Beyond this step

- **Major places only**, by scale or by story importance (8.3).
- **Revising a place's Look** when the story changes it, and a new picture to match.
- **Time of day and season variants** of a picture, if they are cheap.
- **A larger view** on tap.
- **Interiors** as separate pictures for the rooms of a key place.

## 12. Build steps

1. **Probe and styles** (done, section 15). Make real calls at the landscape size to learn the sizes the model
   accepts and their cost, write the `place` direction variants and `build_place_prompt`, and tune them on ten or
   twelve real places from a saved game (all twelve styles on one place, and one style on a range of places).
   *Done when* the places read as views in each style and look like they belong to the portraits.
2. **The place Look** (done, section 16). Generalize `Look` and its validator by kind, with the place tags and search
   text; the place describer (a prompt, the curator request, the scripted version for tests); the sweep and its
   ordering; the rule of section 5; `SetLook` for locations; the GM briefing line; the compendium page carrying `look`.
   Tests, and a live pass on a real save as for the people. *Done when* a game's describable places have descriptions
   that fit and hide nothing.
3. **Pictures for places** (done, section 17). Jobs for places, the landscape size and prompt, the record on
   `Entity.portrait` for locations, the image route, `place_wanted`. *Done when* a `--test` game makes a view for each
   discovered place.
4. **API and app** (done, section 18). `portrait` with `shape` on the entry, `portrait` on the status page's
   location, the component's landscape shape, the compendium entry and the status place page, polling as for
   portraits. Docs. *Done when* a real game shows its places.

## 13. Tests

- Look: the place tag set validates by kind; people's tags are refused on a place and the reverse; the word range, the
  name rule and the other rules of 4.2; the search text; distinctness between two places.
- Describer: the input holds the known facts of the place and its parents and **nothing hidden**, not even a hidden
  `overview` (a fixture with a secret asserts it never reaches the request); ordering; batches; failures back off.
- Visibility: an undiscovered place is neither described nor pictured nor served; a place known only by rumor (no known
  fact of a visual aspect) has an entry but no description or picture until one arrives; a describable place is all
  three; the compendium entry carries `look` and `portrait`.
- Prompt: the parts in order, no name, no people or text in the framing, the place variant used for the styles that
  have one, the size in the image id.
- Pipeline: places after people in a sweep, the current location first, the same limits, and a place Look revision
  makes the picture stale.
- App: the landscape frame, pending, ready and broken; the polling as for portraits; one browser check that a
  location entry shows a loaded image.
- A live pass, **not** in the suite: all styles on one place, and one style on many places, to tune the texts.

## 14. Decisions and open questions

Decided here (change any by saying so):

1. A place is described when it becomes describable (5.1), not when it is created; unvisited places cost nothing.
2. The describer never sees hidden facts of places, not even an `overview` (section 5).
3. Places are pictured empty: no people, text or weather.
4. The picture is a view from where a visitor first stands, of the whole place; its parts are separate places.
5. The same record, store, route and pipeline as portraits are used, extended, not copied.
6. The API carries a place's picture as `portrait`, with `shape` (decided).
7. The current location's summary goes into every request (decided).
8. The status tab shows the current location's picture, prominently (decided).
9. Known facts only, and a place known only by rumor waits (decided; 5.1).

Open:

1. **Aspects at the source.** The strict rule (5.1) makes a place's aspects matter, and so will maps later. Today the GM
   and the curator sometimes leave a place fact with no aspect or with a person's aspect (section 16). Tightening
   that where facts are made is a separate piece of work.
2. **What the model accepts.** `1536x1024` is the usual landscape size for these models, but this one is learned in
   step 1; if it only allows other sizes the spec's numbers change.
3. **The briefing line** is only the party's current location. Should the places around it (the ones inside it or next
   to it) get a line too? More tokens, a more consistent world.

## 15. Step 1 findings

Built: `Settings.place_image_size` (`AIGM_PLACE_IMAGE_SIZE`, default `1536x1024`); a per-call `size` on the image
generators; in `art.py`, `Style.place` and `direction_for`, `PLACE_FRAMING` and `build_place_prompt`; and a
`subject` argument on `scrub_name` so a place's name becomes "the place". Tests: the last sections of
`tests/test_art.py` and `tests/test_images.py`. Findings from about 45 real calls to `gpt-image-2.5-sunburst`, on eight
places from the Aurendell and Icehold saves with hand-written descriptions (stand-ins for the describer of step 2):

- **Size:** `1536x1024` is accepted and comes back as exactly that. It takes 14 to 19 seconds, the files are 130 to
  670 KB as webp (the pen-and-ink style is the largest), and the reply reports **158 image tokens** at the default `low`
  quality, fewer than the 196 of a portrait, so a view costs no more than a portrait.
- **Rate limit:** OpenAI limited this organization to **20 images per minute** (a 429 "Rate limit reached ... Limit
  20"). Firing 33 calls at once hit it once. The pipeline's two at a time and four per sweep stay well under it, and a
  429 is already classed as transient and retried two turns later, but a game catching up on many places at once is
  the case to watch.
- **Prompt:** the prompt of 8.2 gives what was asked for. The picture follows its description closely (the steaming
  well, the notice post, hides on frames, turf roofs and a cart in the square), is empty of people, and has no lettering
  or signs. Interiors (a steaming laundry vault, a sloped-ceiling garret) and a large exterior (a palace over a harbor)
  work as well as a village square. No change to the framing was needed.
- **Styles:** every style carries over. `ink` is true black and white, `gouache`, `storybook` and `sketch` read as
  their media, and `anime` comes out as a painted anime background rather than flat cel art, which suits a landscape.
  Eight styles needed a `place` variant of their direction (the ones that spoke of faces, characters or portraits); the
  other four are used as they are.
- **A name inside a description** ("the Old Quarry") gave "The the place". For a place the scrub now takes the article
  with the name, and replaces only the whole name: the single words of a place's name ("quarry", "gate") are ordinary
  words that the description needs.

What the real saves say about step 2 (from reading the facts of their locations, not from a model):

- **Many known facts have no aspect** (`None`), including ones that plainly describe a place (Sunspire's only known fact
  is "the royal palace sits on the hill above the harbor district"). Under the rule of 5.1 a place such as that is
  not describable until a visual-aspect fact arrives. That matches the decision to wait, but the list of visual aspects
  (and whether an aspect-less fact can count) needs tuning on real saves in step 2.
- **Aspects are not always what their names say:** in one save the Chapel of the Dawn Star's `overview` is about the
  servants who sleep nearby. The describer must read the facts, not trust the aspect, and invent only what the facts
  leave open.
- **Two saves had 12 and 25 discovered locations.** With 12 places per sweep a save catches up in a few turns.

## 16. Step 2 findings

Built: the Look generalized by kind (`PLACE_*_TAGS`, `look_kind`, `tag_sets`, `problems(look, name, kind)`,
`Look.search_text(kind)`); `Entity.look` allowed on locations (`LOOK_KINDS`); `world/describe_places.py`
(`VISUAL_ASPECTS`, `describable`, `needing_places`, `too_alike`, the subject builder and `run_place_looks`);
`PlaceSubject`, `PlaceLookRequest` and the optional `Curator.place_look`; the model curator's `place_look` with its
schema and `prompts/world/describe_place.md`; the scripted `place_look` for tests; `CuratorService.place_looks_due`
and `run_place_looks_if_due`, hooked into `curate()` after the people's Looks; `Session.place_looks_retry_turn`; and the
GM briefing line. Tests: `tests/test_place_looks.py` (36). The compendium page already carried `look` for any entity,
so a place's page shows its description, and `recall` shows the whole Look.

- **The strict rule, on real saves.** The Aurendell save has 61 locations, 25 discovered and **13 describable**; the
  Icehold save has 22, 12 and **5**. All of them were described in one or two sweeps (12 places in about 34 seconds
  with Haiku at low effort, 5 in 32 seconds). The 12 and 7 discovered places left out are the ones known only by rumor
  or by facts with no visual aspect: for example Sunspire, the palace the party lives in, whose only known facts are an
  aspect-less sentence and a `leaders` fact.
- **Secrecy held.** The model is shown only known facts, the known facts of the places that contain it (stopping at
  the first one the player does not know), and the story's sentences that name the place. A test puts a secret in a
  hidden `overview`, a hinted `entry`, a hidden `secret` and a parent's hidden fact and checks that none reaches the
  request. On the Aurendell save I read the vault, the sealed passage and the cisterns against their many hidden facts:
  every detail the descriptions drew on was in a known fact (the rotted door, the nine sconces, the bronze plate with
  its lantern mark), and what the model added was ordinary (a low archway, dust).
- **Length** came out long at first (152 words on average against the 90 to 140 asked), as it did for people. The
  prompt now asks for about 110 and never over 135, and the averages are 117 and 121.
- **The setting text** (`campaign["setting"]`, the Session 0 description "as agreed with the player") is part of what
  the model sees, as it is for people. It is not secret by design (the GM's private notes are `gm_notes`), but a GM
  that puts a secret in it would put it in front of the describer.
- **A missing registration** (the model curator's list of system prompts) made the first live run fail; the failure
  was caught as a note and the game went on, and a test now checks that every prompt the curator asks for exists.
- **What the data looks like.** The newer Icehold save has the same kinds of gap as the older one: Icehold Gate's only
  known fact has the aspect `manner` (a person's aspect), the healer's house and the last cairn have only aspect-less
  facts, and in one save a chapel's `overview` is about the servants nearby. Under the strict rule these places wait.
  Whether to improve the aspects where facts are written (the GM's `establish` and the curator's prompts) is open
  question 1.

## 17. Step 3 findings

Built: `Job.place` and the place branch of `PortraitService` (the place prompt and `AIGM_PLACE_IMAGE_SIZE`, a per-job
size, `place_size` on the service); `place_wanted` and `_visible_places`; places in `due_jobs` in the order of 8.4;
`Entity.portrait` allowed on locations (`World.set_portrait`, the load check); `view_entity` for places, with a new
`shape` field on every portrait view (`square` for people, `landscape` for places); the image route serving a
discovered place's picture; and the notes file's `kind` and place `search_text`. Tests: `tests/test_place_pictures.py`
(11). The compendium page of a place carries `portrait` already, because the route uses `view_entity` for any
entity; the status page and the app come in step 4.

- **Real run.** On the 13 places the describer had written for the Aurendell save (the default `modern` style for 5.5e,
  the real model, a throwaway library), the pipeline made **13 of 13 pictures in four sweeps**: the party's current
  place first, then four at a time, 39 to 66 seconds a sweep, about 3.5 minutes in all, no failures and no rate
  limit. Each is a 1536 x 1024 webp of 180 to 320 KB with its notes file.
- **Fidelity.** The pictures follow the descriptions, and so the facts. The Old vault shows its rotted door, the nine
  bronze sconces on the far wall, the rusted lamp-hook and the shuttered lantern, and nothing of what is hidden about
  it; the harbor district shows tarred warehouses, slate roofs, the seawall and the white city above. A few pictures
  have tiny distant figures (the harbor lane), despite "no people" in the framing: the model treats distant
  specks as scenery. They are small enough not to contradict a portrait; if they matter the framing can say "no figures
  at any distance".
- **The current place comes before the people** (a change from the first draft of 8.4), because the status tab shows
  it first.
- **A refused view is recorded and not retried** (there is no softer prompt for a place).
- **The setting matters for the limit.** With no cap and four a sweep, a game with a hundred discovered places takes
  twenty-five turns to be fully pictured. A sweep of four takes under a minute, so the pipeline stays under OpenAI's
  20 a minute; it is the cost, not the rate, that a later limit to major places (8.3) would address.
- **Not built yet:** `portrait` on the status page's location and the app (step 4).

## 18. Step 4 findings

Built, server: `look` and `portrait` on `GET /status`'s `location`. Built, app: the picture component takes the
`shape` (a square portrait, or a 3:2 view as wide as the column allows), the framed place name with "Painting a
view..." while pending, the View heading for a place's description, the picture first on the status tab's place page,
and `StatusPanel` watching a pending view of the party's place as it watches a pending portrait. Built, terminal
client: the compendium entry of a place says "View" where a person's says "Appearance". Tests: the status tests in
`tests/test_place_pictures.py`, `tests/panels.test.ts`, the terminal client's model test and two browser checks (the
status tab's picture, and a place's compendium entry).

- **Sized to the window.** At the full 720 px a view filled the whole docked panel and left the place's name under the
  fold. The status tab's picture is now about 30% of the window's height (a 3:2 picture, so 405 px wide in a 900 px
  window), up to 720 wide, so it stays the largest thing on the tab and the name and the first lines of text are still
  in view. The compendium's view is up to 360 px wide.
- **A place with no description yet** (known only by rumor) has an entry and no view, as decided; the status tab
  shows its name and facts as before.
- **Not built:** the large view on tap, pictures in the compendium list rows, and the aspects-at-the-source work.

## 19. What the first playtest found

A playtest of the Icehold game showed no descriptions and no placeholders on locations at all, with characters working.
Three separate causes, found by restoring a copy of the save on a second server with the real models:

- **Nothing runs until a turn.** The sweeps run after a turn, and a loaded save had no turn since the server started,
  so nothing was written however many places qualified. Fixed: a restore now catches up in the background, without a
  turn (`routes/history.py: catch_up`): up to four rounds of the people's Looks, the places' Looks and the pictures,
  stopping if the game is replaced. A save made before these features, or a game the server was stopped in the middle
  of, fills in while the player reads.
- **No sign anything was coming.** A place got a placeholder only once it had a Look, so for the first minute there was
  nothing to see. Fixed: a place that is describable but has no Look yet, and a person with none, report `pending`
  (when the server's curator can write them, and not while a failed sweep is backing off), so the placeholder is on
  screen at once and the page polls until the picture arrives.
- **The model thought instead of answering.** The first sweep after a restore failed with "the model stopped with
  max_tokens": the describer's response was a `thinking` block that used all 8000 output tokens, with 240 characters
  of the answer written. The step only writes to a fixed format from facts it is given, so thinking is now off for
  the describing steps (`NO_THINKING`: `describe` and `describe_place`); the same batch then finished in 2409 tokens.
  This was a risk for the people's Looks too. As a net, a batch the model cannot answer is split in two and each half
  asked again once (halves are not split again); a failing sweep still backs off for two turns.

With these, a restored copy of the Icehold save showed the party's place pending at once, its description about 16
seconds after the restore and its picture shortly after, with no turn taken.

Left as it is: a place needs a visual-aspect fact to be described, so the places of that game that have only
aspect-less facts (the gate, the last cairn) still wait, as decided.
