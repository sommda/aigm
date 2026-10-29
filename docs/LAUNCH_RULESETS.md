# AIGM Launch Rulesets: Avoiding a License

Status: **brainstorm, no code, and not legal advice**. Part of the graphical app design; start with [APP.md](APP.md).
It answers the open question in APP.md section 8: launch with one or two rulesets (a stripped-down "Simple" one and a
full "Tabletop" one) without paying for a license. Have a lawyer who knows game and software licensing confirm the
conclusions here before you sell anything; it is a small one-time cost next to the risk. Facts about licenses below
are from memory and must be re-checked against the current license texts.

## 1. Short answer

You do not need to pay for a ruleset if you build on rules that are **openly licensed** or that you **design
yourself**:

- **Simple**: an original rules-light system of your own. No license, any name you like.
- **Tabletop**: a system published under an open license, used within the terms of that license. The best candidate is
  the **D&D 5.2 System Reference Document (SRD)** published by Wizards of the Coast under Creative Commons CC-BY-4.0,
  which is the content of the 2024 rules you already default to. The alternative is **Pathfinder 2e**, open under the
  ORC license.

The real costs are not license fees. They are:

1. **Not using the trademarks**: no "Dungeons & Dragons", "D&D", logos, setting names or product-identity creatures in
   the product, the store listing, the marketing or the generated art.
2. **Keeping the game inside the open content.** Today the game plays "D&D 5.5e" by telling the model to use the rules
   "from memory", and the model remembers the whole published game, not only the open part. That has to change.
3. **Compliance work**: attribution text, a content allow-list, and a one-time legal review.

## 2. What can and cannot be protected

(General principles, mainly US law; confirm for the countries you sell in.)

- **Game mechanics as ideas** (roll a d20, add a bonus, beat a target number, advantage and disadvantage) are
  generally not protected by copyright. Anyone may design a game that works that way.
- **Expression is protected**: the text of the rule books, the wording of spell and monster descriptions, the art, the
  named settings, characters and creatures that a publisher reserves ("product identity").
- **Trademarks are protected separately**: names, logos and trade dress. A license to the text is not a license to the
  name, and you may not suggest the publisher endorses your product.
- **Open licenses** grant the text of one specific document (the SRD) under stated terms, usually requiring an
  attribution notice and forbidding trademark use.

Consequence for AIGM: designing your own mechanics is free; copying or closely reproducing a publisher's text, tables
or named content outside an open license is not; and the name on the box must be yours.

## 3. Where AIGM stands today

- The twelve rulesets in `rulesets.py` are prompts that name an edition and tell the model to apply it "from memory"
  (about 400 to 600 words each; they hold very little rule text). The rules text itself comes from the model.
- The user-facing names are the publishers' product names: "D&D 5.5 Edition", "AD&D 2nd Edition", "Pathfinder" and so
  on.
- World, quest and NPC generation is the model's own, with no required setting. That part is fine, but the model can
  and does produce non-open creatures and names if not told otherwise (a beholder in a cave, the Forgotten Realms in a
  town name).
- Of the twelve, only some editions have an open version: the D&D 5th edition and 2024 revision (SRD under CC-BY-4.0),
  3rd and 3.5th edition (SRD under the Open Game License, which has awkward terms), Pathfinder 1e (OGL) and Pathfinder
  2e (ORC). OD&D, B/X, BECMI, AD&D 1e and 2e, and 4e have no open license for their text (community "retro-clone"
  games exist as separate products with their own licenses, and 4e's license was restrictive).

## 4. Options for the two slots

### 4.1 The full "Tabletop" ruleset

| Candidate | License | What you get | Cost to use |
|---|---|---|---|
| **D&D SRD 5.2** (2024 rules) | CC-BY-4.0, attribution required | core rules; 12 classes with one subclass each; species, backgrounds and origin feats; spells; monsters; magic items; conditions | attribution page; no D&D name or logos; only SRD content; a data set to build |
| D&D SRD 5.1 (2014 rules) | CC-BY-4.0 | the older equivalent | same, and the 2024 rules are what the sheet and prompts target |
| **Pathfinder 2e** (Remaster) | ORC license; some names and the Golarion setting are reserved | a deeper, fully open system with degrees of success and three-action turns | more rules to automate (see 5.2); smaller audience |
| 3.5e / Pathfinder 1e | Open Game License 1.0a | a huge open ruleset | the license has obligations about declaring product identity and carrying the license text; avoid for a new product |
| Retro-clones (for B/X, AD&D feel) | each has its own license (some share-alike) | old-school play | separate legal check per game; small market |

**Recommendation: SRD 5.2.** It is the system people know, it matches the default your prompts, sheet and `dnd55e`
ruleset already target, and it fits the `advantage` reward style in [ROLEPLAY.md](ROLEPLAY.md). Its limits (one
subclass per class, a smaller monster list) are small for a launch, and a game master that only knows the SRD content
is easier to keep consistent. **Pathfinder 2e is the fallback** if the SRD terms or reach turn out to be a problem,
and could be a later second tabletop option.

### 4.2 The "Simple" ruleset

An original system you own outright. It earns its place for new players and phones: a character sheet that fits one
screen, one roll type, and rules the server can run entirely. Because you design it, there is no license, and you can
build the choice-card mechanics ([CHOICES.md](CHOICES.md)) into it from the start.

A straw man to react to, not a design:

| Part | Sketch |
|---|---|
| Traits | four, rated 0 to +3 (for example Might, Quickness, Wits, Presence) |
| Roll | d20 + trait (+2 for a relevant "background tag") against a difficulty: 8 easy, 12 moderate, 16 hard, 20 heroic |
| Good roleplay | advantage on the roll; absolute motives and the rest of [ROLEPLAY.md](ROLEPLAY.md) unchanged |
| Health | a small number of hit points per level plus named conditions |
| Magic and gifts | a short list of "gifts" with a use limit per rest, instead of spell slots |
| Growth | milestones per chapter, tied to [STORY.md](STORY.md), rather than XP tables |
| Sheet | traits, tags, gear, gifts, hit points, a one-line personality |

Keep it truly small: if it needs more than two pages of rules to explain, it is not "Simple".

### 4.3 Whether to launch both

Two is attractive: Simple gets the casual player through the first hour, Tabletop keeps the audience that wants the
real thing. Cost: two prompt sets, two rules modules and two test matrices. Since only two exist, tuning, replay
testing ([TURN_COST.md](TURN_COST.md) section 8) and balancing are far less work than the present twelve.

## 5. What has to change in the product

### 5.1 Names and presentation

- User-facing name for the full ruleset: something like "Tabletop" with the line "compatible with the fifth edition of
  the world's most popular fantasy roleplaying game" only if the license and counsel allow such a statement. Otherwise
  just "Tabletop". Do not use the trademarked names or logos, in the store listing, screenshots, ads, the app name,
  keywords or the metadata.
- The marketing and onboarding avoid "Dungeon Master" too (a term tied to one publisher); AIGM's "Game Master" is
  fine.
- Keep internal ids (`dnd55e`) if you wish, but add a display name map so that no trademarked name appears on screen.
- An in-app and website **Licenses** page with the exact attribution text the SRD license requires, and a `LICENSES`
  file in the repository.

### 5.2 Rules come from data, not from the model's memory

This is the largest engineering item and it pays for itself three times (license, cost, determinism):

1. **Build a structured SRD data set**: classes and their features by level, species, backgrounds, feats, skills,
   spells, monsters, magic items, conditions, equipment. Store it in the repository with its license notice. Start
   from the SRD document itself (check for existing machine-readable versions and their licenses).
2. **The server uses the data**, not the model, for things with exact answers: the character builder and sheets,
   modifiers and proficiency, spell slots and save DCs, monster stat blocks and hit points, check formulas. This is
   exactly the rules code that "server-rolled checks" need ([TURN_COST.md](TURN_COST.md) section 4.2), so the
   licensing constraint and the cost lever are the same project.
3. **The model gets only the slices it needs**, injected into the briefing: the character's class features at their
   level, the monster stat block for the fight, the spell they are casting. The ruleset prompt stops saying "from
   memory" and says "use the reference provided; if it is not in the reference, it does not exist in this game".
4. **Validators enforce the allow-list**: names passed to `update_character`, `set_combat` and the opening character
   builder are checked against the data; a monster or spell that is not in it is refused with a message that suggests
   an in-list alternative or a generic description.

### 5.3 World, monsters and art

- The world curator and story planner prompts get a "no published settings or product-identity creatures" rule: invent
  names, use generic descriptions ("a floating many-eyed horror" rather than a named creature of one publisher). The
  SRD omits several famous creatures for this reason, so the allow-list is also the guide.
- Image prompts for the offline asset pipeline ([ART.md](ART.md) section 6) use the same allow-list and deny-list.
- Check the generated names occasionally: the model has been trained on the published books and may drift back.

### 5.4 The other ten rulesets

Keep them in the repository for your own use and for a developer build, but **do not expose them in the product**:
they rely on the model's memory of non-open books under their trademarked names. A build flag decides which rulesets
the product offers. This also removes ten `03_roleplay.md` files, ten prompts and their tests from the launch quality
bar.

### 5.5 Prompts and the roleplay design

- The ruleset prompts for Simple and Tabletop are rewritten for the data-driven approach (section 5.2) and shorten as
  the data takes over.
- `social_style` is `advantage` for both; Tabletop's reward matches the SRD's advantage rule, and Simple can use the
  same.
- The `rulesets.py` catalog gains `product: bool`, `display_name` and `license_notice` fields.

## 6. Risks that remain

| Risk | Mitigation |
|---|---|
| The model slips in non-SRD names or text | allow-list validators; prompts; periodic audit of saved games by a script that scans for a deny-list of known product-identity terms |
| The license terms change or are misread | counsel review before launch; keep a copy of the license text and the SRD version used; consider keeping the Simple ruleset as the only one if Tabletop is challenged |
| Users expect their D&D books to work | state that Tabletop uses the free SRD content; offer custom content (homebrew) within Simple |
| Trademark conflict on your own name | a clearance search on "AIGM" and the app name before launch |
| Store reviewers question the name or content | the licensing page, a clean listing, and no trademarked terms |
| A publisher's policy on AI products | read the license for any restriction on use in AI products; the SRD CC license is broad, but confirm |
| Share-alike or attribution duties spreading to your content | CC-BY-4.0 requires attribution and notices of changes, not sharing your code; counsel to confirm for a hosted game |

## 7. Effect on the other design documents

- [APP.md](APP.md) records this as decided: launch with Simple and Tabletop only; the model-adjudicated path for the
  other ten rulesets is not part of the product.
- [TURN_COST.md](TURN_COST.md) section 4.2 (server-rolled checks) becomes required, not optional, and is built on the
  SRD data set. The "unautomated rulesets" fallback it mentions goes away for the product build.
- [CHOICES.md](CHOICES.md) can attach prebuilt `check` objects to nearly every action, since the rules are code.
- [ROLEPLAY.md](ROLEPLAY.md) is unchanged except that only the `advantage` style ships.
- [ART.md](ART.md): the allow-list also restricts what art may show.
- [CAMPAIGNS.md](CAMPAIGNS.md): packs must stay inside the launch rulesets' open content; `pack lint` checks monsters,
  spells and names against the allow-list, and a pack states which of the two rulesets it supports.

## 8. Suggested next steps

1. Legal review of: the SRD 5.2 license, what compatibility statement is allowed, the name "AIGM", and the app
   listing.
2. Decide Tabletop = SRD 5.2 (recommended) or PF2e.
3. Write the Simple ruleset (two pages) and playtest it with the current engine, using `dnd55e`'s prompts as a
   template.
4. Build the SRD data set and the allow-list validators; make `dnd55e` use them in the developer build first.
5. Add the product build flag and display names; remove trademarked names from every user-visible string.
6. Run the replay harness to measure quality and cost of data-driven prompts against today's "from memory" prompts.

## 9. Open questions

1. Is Simple a separate game, or a "difficulty" of Tabletop (same engine, fewer options)? One engine with two content
   levels is cheaper, but a truly different feel is a stronger product.
2. Do you want homebrew content (user-written classes, monsters)? It needs moderation and licensing terms of its own.
3. If Pathfinder 2e were added later as a third ruleset, is its audience worth a second data set?
4. Is a plain statement of compatibility worth the legal review it needs, or is "Tabletop" enough?
