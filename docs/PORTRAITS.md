# AIGM Character Portraits: Design

Status: **spec, no code yet**. Second step toward graphics, after the Looks ([LOOKS.md](LOOKS.md)). It turns a
character's written Look into a generated headshot, in one art style for the whole game, and shows it on the
character's page. It builds on [LOOKS.md](LOOKS.md) (the descriptions), [RULESETS.md](RULESETS.md) (the default style
follows the ruleset), [OPENING.md](OPENING.md) (Session 0) and [ART.md](ART.md) (the wider art plan, which this step
partly supersedes: ART.md assumed pre-made art, and this is generated art for custom games, its "later" column).

## 1. Goal

Every character who has a Look gets one headshot, made by an OpenAI image model, in a style the player chose in
Session 0 (by default the look of the chosen ruleset's era). A player character's headshot appears on the character's
tab under Status. An NPC's appears on the NPC's compendium entry. The first release builds the player characters; the
data and code are written so that NPCs follow without a redesign.

### Non-goals (this step)

- Full-body art, scenes, places, items, maps or expressions ([ART.md](ART.md) covers those later).
- Showing images in the terminal client.
- The similarity library of [LOOKS.md](LOOKS.md) 6. This step keeps what that library needs (an id, the search text,
  the style, the prompt) but does not search.
- Editing or uploading portraits, or choosing a custom style by free text.

## 2. Decisions already taken

| Decision | Source |
|---|---|
| A headshot for each character that has a description, player characters first | the product owner |
| The model is the one named by `IMAGE_MODEL`; the key is `OPENAI_API_KEY` (both already in `server/.env`) | the product owner |
| One consistent style per game, chosen in Session 0; the default follows the ruleset | the product owner |
| A portrait appears on the character's own page once it exists | the product owner |
| The image prompt is assembled in the image pipeline, not by the GM ([LOOKS.md](LOOKS.md) 14) | earlier decision |
| Generation runs in the background; nothing waits for it | earlier decision |

## 3. Terms

- **Style**: a named, written art direction (medium, line, palette, framing) from a fixed catalog (section 5).
- **Portrait**: the record that says "this character has an image": which file, in which style, from which Look
  revision, made by which model. It is data about the image, not the image.
- **Image file**: the bytes, stored once, named by a hash of what produced them (section 6).
- **The pipeline**: the server code that decides who needs a portrait, builds the prompt, calls the model and stores
  the result. It is the portrait counterpart of the describer in [LOOKS.md](LOOKS.md) 5.

## 4. Configuration

Read from the environment or `server/.env`, like the other settings:

| Variable | Meaning | Default |
|---|---|---|
| `OPENAI_API_KEY` | key for the image API | none: portraits are off |
| `IMAGE_MODEL` | the image model id (the current value is `gpt-image-2.5-sunburst`) | none: portraits are off |
| `AIGM_IMAGES` | set `false` to switch portraits off although a key exists | `true` |
| `AIGM_IMAGE_SIZE` | the requested size | `1024x1024` |
| `AIGM_IMAGE_QUALITY` | the requested quality, if the model has the option | the model's default |

Portraits are **on** only when the key and the model are both set, the setting is not `false` and the server is not in
a mode with no network (`--test` uses a fake, section 12). When they are off nothing else changes: the character pages
carry `"portrait": null`, `GET /health` reports `"images": false`, and Session 0 does not offer a style.

**No new dependency.** The server already has `httpx`; the pipeline calls `POST /v1/images/generations` directly with
`model`, `prompt`, `size` and `n: 1`, so it does not depend on an SDK version that may not know this model. The reply
may hold `b64_json` or a `url`; both are handled. Optional parameters (`quality`, `output_format`) are sent only if
step 1 shows the model accepts them. The key is read once and never logged, saved, or put in an error message.

## 5. Art styles

### 5.1 The catalog

Every style can be chosen under any ruleset. The last four (`storybook`, `sketch`, `anime`, `illustration`) are
ruleset-independent: no ruleset defaults to them, so they are only used when the player picks them.

A style is a few lines of written direction, in `server/src/aigm/art.py` (a code table like the rulesets), with an id,
a display name, and a `direction` text that goes into every prompt of the game verbatim. The direction describes the
look and **never names a living artist, a product, a studio or a setting** ([ART.md](ART.md) 7); it says what the
picture is made of.

| Id | Name | Direction (abridged) | Default for |
|---|---|---|---|
| `ink` | Pen and ink | black and white line art, cross-hatching, no color, like a 1970s rulebook plate | odnd, adnd1e |
| `gouache` | Classic fantasy painting | saturated gouache and oil, strong outlines, heroic, like a 1980s boxed-set cover | basic, becmi |
| `moody` | Moody painting | dark painterly realism, textured brush, muted earth colors, like a 1990s campaign book | adnd2e |
| `comic` | Inked and colored | bold ink lines, flat bright color, dynamic, like a 2000s core rulebook | dnd3e, dnd35e |
| `vivid` | Vivid digital | high contrast, glowing color, crisp edges, like a 2008 digital illustration | dnd4e |
| `modern` | Modern painting | soft realistic digital painting, warm natural light, like a 2010s sourcebook | dnd5e, dnd55e |
| `detailed` | Detailed fantasy | dense detail, ornate gear, rich texture, like a Pathfinder-era hardback | pf1e |
| `clean` | Clean stylized | clear shapes, smooth shading, bright palette, like a 2020s stylized illustration | pf2e |
| `storybook` | Storybook watercolor | loose watercolor and ink wash on paper, gentle colors | none |
| `sketch` | Pencil sketch | graphite portrait sketch on cream paper, soft shading | none |
| `anime` | Anime | clean anime character art, large expressive eyes, cel shading, soft gradients, vivid color | none |
| `illustration` | Fantasy novel illustration | refined painterly book-plate portrait, as in a fantasy novel's cover or frontispiece, natural proportions, rich but restrained color | none |

The abridged directions above are the idea; the written ones are longer (about 40 words) and are tuned in step 1 by
looking at real results. `RULESET_STYLE` maps each ruleset id to its default; a test checks that every ruleset has
one. The catalog is data, so a style is added without touching the pipeline.

### 5.2 Choosing in Session 0

- `GameState.art_style: str | None`. `None` means "the default for the chosen ruleset", resolved when an image is made,
  so choosing a ruleset after the style still gives a matching default. The value `"none"` means no portraits for this
  game. Anything else is a catalog id.
- A new Session 0 tool **`set_art_style`** (`style`: an id or `"none"`), like `set_ruleset`. It is Session 0 only and
  answers an error afterwards: the style is fixed once the adventure begins, because a mixed set of styles is the
  failure this design exists to avoid. It is offered only when portraits are on.
- The Session 0 prompt ([OPENING.md](OPENING.md)) gains one short step after the ruleset: say what the default style
  is, name two or three alternatives in a line, and ask only if the player seems to care. The tool is called only when
  the player picks something other than the default (or "no pictures"). The catalog's ids and names go in the tool
  description, so the GM can list them.
- Session 0 shows nothing else. The chosen style is part of the game state and appears in `GET /status` for the
  clients that want to say it.

## 6. The Portrait record and storage

### 6.1 The record

```json
{ "image": "p_3fa9c1d2e8b7a640", "style": "modern", "look_rev": 1, "model": "gpt-image-2.5-sunburst",
  "state": "ready", "attempts": 1, "made_turn": 3 }
```

- `image` is the id of the file, or absent when none exists yet. `state` is `ready` or `failed`; **pending is never
  saved** (it lives in the running session, like the other pending work in `Session`).
- `look_rev` is the Look revision the picture was made from ([LOOKS.md](LOOKS.md) 7). A Look that moves on makes the
  picture stale (section 8.4).
- A `failed` record also carries `reason` (`moderation`, `quota`, `unavailable`, `bad_reply`) and `attempts`.

### 6.2 Where it lives

Beside the Look it comes from, and separate from facts, sheets and the compendium:

- Party members: `GameState.portraits`, keyed by name, like `GameState.looks`.
- NPCs (step 4): `Entity.portrait`, beside `Entity.look`; only `npc` entities have one.
- Save format **11**; older saves load with no portraits, and the pipeline then fills them in.

### 6.3 The image files

The bytes are not in the save (a save is JSON and stays small). They go in a shared library folder
`{save_dir}/images/`:

- The file name is the **image id**, `p_` plus the first 16 hex digits of a SHA-256 over (model, size, style, prompt).
  The same inputs give the same id, so a regenerated or restored game finds its picture instead of paying again, and
  two games never overwrite each other.
- Next to each image goes `<id>.json`: the full prompt, the model, the style, the Look's `search_text` and summary,
  the time. This is the index for the library and similarity search of [LOOKS.md](LOOKS.md) 6; nothing reads it yet.
- The extension is `.png` unless step 1 shows the model returns something smaller; the server serves what it stored.
- Writes are atomic (a temporary file, then a rename), and the record is set only after the file exists. A record
  whose file is missing (a save copied without its images) is treated as no portrait and rebuilt.
- Deleting a save does not delete images; they are the library.

## 7. Building the prompt

The prompt is built in `aigm/art.py` from three parts, in this order, by one function that tests can call:

1. **Style direction**: the chosen style's text, the same for every character of the game.
2. **Framing**: fixed text for every portrait: a head-and-shoulders portrait, facing the viewer at a slight angle, the
   character centered with the head fully in frame, a plain simple background that suits the style, no text, no
   caption, no border, no watermark, no other people.
3. **The character**: the Look's `description` (the summary first, as a one-line anchor), followed by the controlled
   tags that help a model most (ancestry, age, gender, build), because tags survive where prose is skimmed.

Rules:

- **Only the Look.** No facts, no sheet, no secret and no GM note enter the prompt, so a portrait can show nothing the
  Look does not say. The Look is already written to contain only what anyone could see ([LOOKS.md](LOOKS.md) 3.1).
- **Name stays out.** The prompt uses "the character", never the name, so a famous name cannot pull the face toward a
  real person or a franchise.
- **Clothing and gear** are used as the Look gives them; the framing keeps only what is above the chest in view.
- The prompt is stored with the image (6.3), so a surprising picture can be explained.
- Length is kept under the model's limit by dropping the tags first, then trimming the description's tail.

Same style text, same framing, same size and the same model are what make a game's portraits look like a set. The
models do not promise the same face across calls and this design does not try; it only controls the style.

## 8. The pipeline

### 8.1 Who needs a portrait

A character needs one when **all** hold:

- portraits are on and the game's style is not `"none"`;
- they have a Look, and it is not `provisional` for a party member (party Looks are written from Session 0 text, so
  they are `fixed`); an NPC is considered once it is visible to the player (the compendium rule, so a portrait is never
  paid for before the player could see the character; this is the cost control for NPCs);
- they have no `ready` portrait made from the current Look revision, or a `failed` one that is due for a retry.

Order: party members in party order, then NPCs present in the scene, then other visible NPCs, newest first.

### 8.2 When it runs

In the same place as the Look sweep (`curate()` after a turn in `routes/chat.py`), as a background step:

- `portraits_due(session)` is cheap and synchronous: it only looks at records. Nothing is called unless someone is
  due.
- `run_portraits(...)` generates up to **2 images at a time** and at most **4 per sweep**, so a six-person party
  finishes in two sweeps without a burst of calls. It never raises and never blocks a turn.
- When a game starts, the party's Looks arrive first (the Looks bootstrap stage), and the first sweep after that
  generates the portraits. The bootstrap does **not** wait for pictures: a headshot takes tens of seconds.
- Results are applied through the session's pending-work drain, as Looks are (`pending_portraits`, applied in
  `drain_pending` between turns), so a save never sees a half-applied change.

### 8.3 Failures

The pipeline distinguishes:

- **Transient** (network, a 5xx, a rate limit): retried on a later sweep, at most 3 attempts in all, waiting 2 turns
  between attempts.
- **Moderation** (the model refuses the prompt): not retried. One extra attempt is made with a softened prompt that
  drops everything but the tags and the first sentence of the description; if that fails too the record is `failed`
  with reason `moderation`, and the character simply has no picture.
- **Quota or auth** (billing, a bad key): the pipeline switches itself off for the rest of the server run and logs one
  line. Games continue.
- A bad reply (no image, unreadable bytes) counts as transient.

A `failed` record is shown to clients as no portrait; it is not an error to the player. The debug view lists failures.

### 8.4 When the Look changes

The Look reviser ([LOOKS.md](LOOKS.md) 7) bumps `rev` when the story adds a lasting detail (a scar, a new beard).
A portrait with an older `look_rev` is **stale**. The pipeline regenerates it, but at most once per character per 20
turns. **The old picture stays on the page until the new one is ready.** Old files
stay in the library.

## 9. The API

Nothing is pushed; clients pull, as for the Look.

- `GET /characters/{name}` and `GET /compendium/entities/{id}` gain a `portrait` field:
  `null` when portraits are off, the character has none yet and none is coming, or the style is `"none"`; otherwise
  `{ "state": "pending" | "ready", "url": "/portraits/p_3fa9...?session_id=default", "style": "modern" }`. `url` is
  absent while `pending`.
- `GET /portraits/{image_id}` returns the bytes with the right content type and
  `Cache-Control: private, max-age=31536000, immutable` (the id is a hash of the content's inputs, so it never changes
  meaning). It takes `session_id` and answers `404` unless **this session shows that image to the player**: a party
  member's current portrait, or an NPC's whose compendium entry is visible. Image ids cannot be guessed, but the check
  is what keeps a hidden NPC's picture secret.
- `GET /health` gains `"images": true | false`.
- `GET /status` (and the character roster) gain `"art_style": "modern"` (or `null`).

A `pending` portrait means one is queued or running. A client that shows a pending character polls the page every 5
seconds while that page is open, for at most 5 minutes, then stops until the page is refreshed. Nothing is added to
the SSE stream in this step.

## 10. Clients

### 10.1 The graphical app

- **Status, character tab**: the portrait at the top of the sheet, beside the name, headline and vitals, about 160 px
  square on desktop and 120 px on a phone, with the **Appearance** text below it as today. While `pending`, a quiet
  placeholder (the character's initials in a frame) with the text "Painting a portrait..."; if there is none and none
  is coming, nothing at all, as today.
- **Compendium, NPC entry**: the same block at the top of the entry, above the facts and Appearance. A met NPC with no
  facts shows the portrait and the Appearance text only.
- A broken image falls back to the initials frame and never an error. Alt text is the Look's summary.
- Tapping the portrait opens it large in a modal (step 3, optional).

### 10.2 The terminal client

Shows nothing new in this step: no image, no placeholder. Appearance text already appears. (Kitty or sixel graphics via
`textual-image` is a possible later step; see open questions.)

## 11. Safety, privacy and cost

- **Sent to OpenAI:** only the prompt of section 7: a style text and a physical description. No names, no story, no
  session id, no user data. This should be said in the README (images are generated by an outside service when a key is
  set).
- **Secrecy:** a portrait is shown under the same rule as a Look: PCs always; NPCs once discovered (section 9).
- **Content:** the style texts forbid text and gore; the Look's own rules already keep it to visible, ordinary
  appearance. Moderation refusals are expected sometimes and are handled quietly (8.3).
- **Licensing:** check the model's commercial-use terms before any release ([ART.md](ART.md) 7). Generated images are
  stored with their prompt and model for that purpose.
- **Cost:** one image per character, plus stale regenerations, with no limit per game in this step (a cap is
  left for later, open question 5). The cost per image depends
  on the model, size and quality; step 1 measures it for the configured model and records it in this document.

## 12. Tests

All offline. A `FakeImages` generator (like the scripted curator) returns a small valid PNG made with the standard
library (a solid color from a hash of the prompt, so different prompts differ), can be told to fail in each way, and
counts calls. `aigm --test` uses it too, so the app can be driven without a key.

- Settings: portraits are off without the key or the model, or with `AIGM_IMAGES=false`.
- Styles: every ruleset has a default; every id in the catalog is usable; no direction names a person or a product.
- Prompt: parts in order; only the Look's words and tags; never the name; stays under the limit; the same inputs give
  the same prompt and the same id.
- Pipeline: who is due and in what order; two at a time; a Look revision makes a portrait stale and the old
  one stays until the new one is ready; no regeneration within 20 turns; transient, moderation and quota failures;
  `pending` is not saved; a record whose file is missing is rebuilt; it never raises.
- Session 0: `set_art_style` works in Session 0 only, rejects unknown ids, `"none"` stops generation, the default
  follows a later ruleset change.
- API: `portrait` on both pages in each state; `/portraits/{id}` content type and caching headers, `404` for another
  session's image and for a hidden NPC's; `/health`.
- Persistence: version 11; older saves load; the image library survives a save and restore.
- App: the character tab and the NPC entry render ready, pending and absent portraits and survive a broken URL; the
  page polls while `pending` and stops. Jest tests for the logic, one browser test with `--test` mode.
- A live test, **not** in the suite and run by hand like the Looks live pass: one real image per style, to tune the
  style texts and to record the cost.

## 13. Build steps

Each step leaves the suites green and is useful alone.

1. **Probe and styles.** Add the settings. Make one real call per style with a sample Look, to learn which parameters
   the configured model accepts, the response shape, the file format and size, and the cost. Write `art.py` (catalog,
   defaults, prompt builder) and tune the style texts from the results. Record findings in this document.
   *Done when* twelve samples (one per style) look like sets and the catalog is final.
2. **Pipeline for the party.** `Portrait` record, `GameState.portraits`, save format 11, the image folder, the fake
   generator, `portraits_due` and `run_portraits`, the pending-work plumbing, failures and staleness, and the hook
   in `curate()`. *Done when* a `--test` game produces portraits for the party on disk.
3. **Style in Session 0.** `GameState.art_style`, `set_art_style`, the prompt step, `/status` carrying the style.
4. **API and app.** The `portrait` field on the character page, `GET /portraits/{id}`, `/health`, and the app's
   status tab with polling and the initials fallback. Update API.md and the README. *Done when* a real game shows its
   party's portraits.
5. **NPCs.** `Entity.portrait`, the visibility rule, the compendium field and the app's entry, and the
   ordering. Live pass on a real save, as for the Looks.
6. **Later, not planned here:** the large view, regenerate on request, reference images for a more consistent face, the
   similarity library, terminal graphics.

## 14. Decisions and open questions

Decided here (change any by saying so):

1. Direct HTTP calls with `httpx`, no SDK; the prompt is built in the pipeline; images live in a shared content-named
   library folder and the save holds only the record.
2. The style is fixed at the start of the adventure; there is no mid-game switch.
3. Party Looks are used as soon as they exist. NPC portraits wait until the player can see the NPC.
4. Stale pictures are replaced, at most once per 20 turns, and the old one stays visible until the new one is ready.
5. The terminal client shows no image.
6. The prompt uses no names and no facts.

Open:

1. **The model's parameters.** `gpt-image-2.5-sunburst` is not a model this document can describe in detail, so which
   options it accepts (`quality`, `output_format`, transparency, sizes, edits with a reference image) is learned in
   step 1, and sections 4 and 6.3 are adjusted to match.
2. **A custom style.** Allow a short free-text style from the player ("like an old woodcut") on top of the catalog?
   It is flexible but risks naming artists and products; it would need the same filtering as the catalog. Left out.
3. **A consistent face across a game's regenerations,** using the previous portrait as a reference image where the
   model supports edits. Worth testing in step 1 because stale replacements would otherwise change a face.
4. **Terminal graphics.** Worth adding for terminals that support them?
5. **A spending limit.** There is none for now: a game makes one image per character, plus stale replacements (at
   most one per character per 20 turns). A per-game cap, and for a hosted product a per-account budget
   ([TURN_COST.md](TURN_COST.md)), are left for later.
6. **Regenerate on request** ("I do not like this one"), and how many tries a player gets.
