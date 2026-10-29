# AIGM Art: Just Enough

Status: **brainstorm, no code**. Part of the graphical app design; start with [APP.md](APP.md). The first draft of
this document proposed a rich illustrated-novel motif. The product owner has since decided that **art is not the
selling point; narrative quality is** ([CAMPAIGNS.md](CAMPAIGNS.md)). This version keeps only what the product needs,
defers the rest, and makes the interface "chrome" as cheap as possible.

## 1. Scope

| Element | First release | Later |
|---|---|---|
| Portraits | a **shared library** for generic people, plus a **portrait for each speaking cast member of a campaign pack** | per-game custom portraits; expressions |
| Illustrations | **a few per campaign pack** (opening, chapter turns, endings), made once and reused | generated plates for custom games |
| Maps | a **region map** drawn from world data with fog of war, and simple **site plans** for key places | tactical grids |
| Chrome | a **token-based theme**, free fonts and icons, a texture or two | a commissioned kit |
| Runtime image generation | **none** | optional premium feature |

The principle: **pay for each picture once, use it in every playthrough.** Campaign packs make that possible because
their cast and places are known in advance ([CAMPAIGNS.md](CAMPAIGNS.md) section 6). Custom games, whose cast is
invented during play, get library portraits and no illustrations at first. Because the first campaigns are short and
share worlds, a **world pack** owns the map, the place plates and the recurring cast's portraits, and each campaign
adds only a few plates of its own (4 to 6), so most art is made once per world, not once per campaign.

## 2. Ground rules

1. **Art is derived from what the player knows.** A picture shows only `known` facts (and `hinted` ones only as vague
   mood). A hidden fact must never reach a portrait, a plate or a caption.
2. **Art never carries information the text lacks.** The game is fully playable with images off, missing or slow.
3. **Art attaches to people, places and moments, never to plot roles,** so variation in a pack never invalidates it.
4. **Appearance is data.** What a portrait shows is written as a known fact on the entity, so the narrator does not
   contradict it.
5. **Nothing is generated while a turn waits.** Everything in the first release is pre-made.
6. **One written style bible,** versioned, so assets made months apart match.

## 3. Portraits

### 3.1 The library

A set of portraits tagged by ancestry, age, build, gender presentation, role (guard, merchant, noble, thief, priest,
innkeeper...) and mood. The server picks the closest match for a new person from their `known` appearance facts and
never gives two people in the same game the same face. Aim for roughly 200 to 400 for launch; fewer is acceptable if
tags are broad and the matcher avoids repeats.

How to make it cheaply:

- **Generate in bulk and curate** with an image model, once, offline: prompt from the style bible and the tag matrix,
  discard misfits, retouch the best. A person reviews every image before it ships. Check the model's license terms for
  commercial use and for a style or fine-tune you rely on.
- **Or commission** a set from an illustrator if the generated look is not good enough; budget one fixed fee.
- **Fall back to initials in a frame** for any person without a match, so the interface never shows a broken image.

### 3.2 Pack portraits

Each speaking cast member of a pack gets a specific portrait made for them (generated and curated, or commissioned),
because they recur and their appearance is described in the pack. It ships in the pack's `assets/` folder.

### 3.3 The player's character

Pick from the library by tag, or from the pack's pregenerated heroes (each has a portrait). No custom generation at
launch.

## 4. Illustrations

A pack declares a few named **moments** (the opening, the turn of each chapter, each ending, and a handful of set
pieces). Each has one illustration, made once. The client shows it at that moment, full width, as a book plate.

- A **plate budget per pack**: for a short campaign, 4 to 6 of its own, plus the world's place plates; for a longer
  pack, 8 to 15. Plates are the most expensive and least necessary art; everything in a pack that is not on the list
  gets a portrait, a map or no picture.
- **Reuse** by place: a place's plate appears again when the party returns; add time-of-day variants only if cheap.
- A **book view** (the playthrough as chapters with the plates and portraits in place, shareable) falls out for free
  from the pack's assets and the chronicle, and is a good keepsake feature; build it only after launch.

## 5. Maps

Maps are **data rendered by the client**, never generated pictures. They can then fill in as the player learns, and
the same data later supports tactical combat.

| Level | Shows | Data | First release |
|---|---|---|---|
| Region map | known places and routes | the knowledge-base graph plus a position per place | yes |
| Site plan | the rooms of one site on a grid | a small tile grid with room labels | for key places |
| Tactical grid | the scene with tokens | the site plan plus positions and rules | later |

Fog of war follows the disclosure model: a place is drawn when its entity is known, a route when a known fact states
it, a room once visited. A hinted place can be a smudge with a "?" (a hint channel in the spirit of
[ROLEPLAY.md](ROLEPLAY.md)).

Data needs: the knowledge base has links but no geometry. For pack campaigns the designer supplies positions and site
grids (from a few hand-made templates such as an inn, a crypt and a street). For custom games, use a graph layout of
the known places and skip site plans. Draw with SVG from a handful of icons.

## 6. Asset pipeline (offline, not a service)

Because nothing is generated at runtime, there is no art service in the first release. There is a **build step**:

1. The designer's pack lists the assets it needs (`assets` manifest in [CAMPAIGNS.md](CAMPAIGNS.md)).
2. Assets are generated or commissioned, reviewed by a human, and committed with their source and license recorded.
3. A checker confirms every cast member has a portrait, every moment has a plate, alt text exists, files meet size
   limits and formats (WebP, a few sizes), and nothing is missing.
4. The app downloads a pack's assets when the player starts it (and caches them), from storage behind a CDN. The app
   bundle contains only the library's essentials.

A runtime art service (jobs, moderation, quotas, a provider adapter) is a later design, needed only for custom-game
portraits or plates as a premium feature.

## 7. Legal and policy checks

- Commercial rights to the images you ship: the image model's terms, or the illustrator's contract (buy outright, with
  the right to modify).
- Store rules for AI-generated content and age ratings.
- Content limits in the style bible (no real people, no explicit content; violence suited to the rating).
- A deny-list of publisher product-identity creatures and names, so art does not draw them
  ([LAUNCH_RULESETS.md](LAUNCH_RULESETS.md)).

## 8. Chrome: the simplest thing that works

Chrome is the decoration of the interface itself. It never carries game information. Aim for the cheapest result that
does not look unfinished.

### 8.1 Recommendation

**A restrained theme made from tokens, free fonts and free icons, with one parchment-like background texture.** Spend
nothing on commissioned art for the first release. Revisit when the product has users and revenue.

### 8.2 The parts

| Part | Cheap approach |
|---|---|
| Colors and spacing | **design tokens** (a palette of about 10 colors, a spacing scale, corner radii, shadows) in one file; light and dark variants; every component reads tokens, none hard-codes a color |
| Type | a **display face** for titles and a **readable serif** for narration, from an open font collection (check the font's license for app embedding); a plain UI face for labels |
| Panels and buttons | **flat shapes**: rounded rectangles, a thin double border, subtle inner shadow. No nine-slice art needed |
| Ornaments | a few **SVG** pieces drawn once: a divider, a corner flourish, a chapter-header rule, a drop cap style |
| Texture | one small **tileable parchment** or paper texture used at low contrast behind the story; a flat color fallback |
| Icons | an **open icon set** for the interface, plus a fantasy icon set for skills, items and conditions (check each set's license and its attribution rule; several fantasy sets require credit) |
| Dice | simple drawn dice with a short tumble animation; no 3D |
| Motion | an ink-in for new text, a page-turn fade for chapters, a dice tumble; all off with reduced motion |
| Map art | a parchment tint, a few landmark icons by kind, route lines, a fog tint |

### 8.3 Technical notes for React Native

- Everything above is plain React Native styling and a few SVG components (via an SVG library), which also render in
  the browser build. No platform-specific image tricks are needed.
- Keep image textures small and few; avoid stacked transparent layers on low-end phones.
- Theme through a context so a different palette (a darker, a sea or a steampunk look) is a token swap.
- Contrast ratios checked in both themes; text never on a busy texture without a backing panel; tap targets at least
  44 points; the app usable with all images off.

### 8.4 Upgrade path

If users respond to the game, commission one cohesive kit later (panels with ornate borders, button states, a title
screen, an app icon set) and swap it in behind the same tokens. Because components read tokens, the swap touches the
theme, not the screens. Do commission an **app icon and a store listing set** at launch: they are the first thing a
store visitor sees and are cheap relative to their value.

## 9. Cost sketch

Art cost is now mostly one-time:

> art cost = library (once) + pack portraits and plates (once per pack) + chrome (near zero) + app icon and store
assets

There is no per-turn or per-player art cost in the first release, which also removes a risk from the subscription
margin. Compare with the LLM cost per hour in [TURN_COST.md](TURN_COST.md); the art is a fixed cost to amortize over
all players of a pack.

## 10. Open questions

1. Which image model and style? Run a short bake-off: ten library portraits and three plates, scored for consistency
   across regenerations and for fit with the style bible.
2. Generate-and-curate, or commission, for the library?
3. How many plates per pack is enough for the pack to feel illustrated without a high cost?
4. Should custom games get any generated portrait at launch, or only the library?
5. Is the book view a launch feature or a later one?
6. Site plans from templates (reliable) or from the curator (flexible)? Templates are probably enough for launch.
