# AIGM Graphical App: Platform and Architecture

Status: **brainstorm, no code**. This is the first of several documents about turning AIGM into a graphical product.
The others are [CAMPAIGNS.md](CAMPAIGNS.md) (predesigned campaigns and the tools to make them),
[CHOICES.md](CHOICES.md) (the choose-your-own-adventure interaction), [ART.md](ART.md) (a deliberately small art
scope, and the interface "chrome"), [TURN_COST.md](TURN_COST.md) (LLM cost, speed and pricing mechanics) and
[LAUNCH_RULESETS.md](LAUNCH_RULESETS.md) (which rules to ship without a license). It builds on the existing
[API.md](API.md), [CLIENT.md](CLIENT.md) (the terminal client), [WORLD.md](WORLD.md), [STORY.md](STORY.md) and
[ROLEPLAY.md](ROLEPLAY.md).

Decisions already made (from the product owner), which this document follows:

1. **React Native first**, with a browser build and possibly a desktop app. Claude Code is expected to help with
   ports.
2. **Art is "just enough"**, not the selling point. Chrome is whatever is simplest and cheapest.
3. **The differentiator is narrative and storytelling quality.** That is why predesigned campaigns exist.
4. **Pricing**: pay as you go plus subscription tiers, with an intentionally limited free tier. Amounts come later.
5. **Rulesets**: launch with one or two, no license fee ([LAUNCH_RULESETS.md](LAUNCH_RULESETS.md)).

## 1. Goal and scope

A polished client for an AI game master whose stories are better than the usual AI game, in these forms:

- **iOS app** (first), then **Android**, both from the React Native codebase.
- **Browser app** for PCs, from the same codebase.
- **Desktop app**: optional, a wrapper around the browser build (section 3.3).

In scope for the first release: streamed narration, tappable choices with sub-choices and a limited free-text option
([CHOICES.md](CHOICES.md)), a library of predesigned campaigns plus custom games ([CAMPAIGNS.md](CAMPAIGNS.md)),
portraits and a few illustrations used sparingly ([ART.md](ART.md)), a simple map, a journal/compendium, a character
sheet, dice animations, accounts and billing.

Out of scope for the first release: tactical combat on a grid (the design should not rule it out), voice, multiplayer,
user-generated campaigns, a creator marketplace, runtime image generation.

What stays the same: the game is a model-run game master over the existing world knowledge base. **Hidden facts and
motives never reach a client or an image prompt.**

## 2. Where the product stands, and what a paid product needs

The server already has most of the game. It does not yet have the product around it.

Reusable as it is:

- `POST /chat` as an SSE stream of text, thinking, tool and dice events, plus `/status`, `/characters`, `/compendium`
  and the save routes.
- The world knowledge base with `known`, `hinted` and `hidden` facts, the story plan with chapters, milestones and
  endings ([STORY.md](STORY.md)), the chronicle and next-tale flow ([NEXT_TALE.md](NEXT_TALE.md)), and motives with
  the `social_check` mechanics ([ROLEPLAY.md](ROLEPLAY.md)).
- Per-request metrics (tokens, cache use, latency) in `saves/metrics`.

Missing for a paid, multi-user product:

| Need | Today | Needed |
|---|---|---|
| Accounts and auth | none; one global conversation | sign-in (Apple, Google, email), a token per request |
| Multi-tenancy | sessions by name, in-memory, saves are files | per-user games in a database, isolation, quotas |
| Resumable turns | a dropped connection loses the stream | a turn is a server task with a numbered event log the client can re-read (section 6) |
| Structured turns | free text plus tool events | choices, art and map events ([CHOICES.md](CHOICES.md)) |
| Campaign library | Session 0 builds every game from scratch | campaign packs, a loader and variation ([CAMPAIGNS.md](CAMPAIGNS.md)) |
| Entitlements and credits | none | a ledger of credits, subscription state, and a check per turn ([TURN_COST.md](TURN_COST.md) section 11) |
| Metering and limits | metrics only | cost per user per day, caps, abuse controls |
| Moderation | none | input moderation; a way to report output (store rules) |
| Secrets | API key in the server's environment | unchanged; the server is the only LLM caller |

None of this depends on the client platform, but it dominates the schedule, so section 7 puts it first.

## 3. The client platform: React Native

### 3.1 Choice and shape

**One TypeScript codebase on React Native with Expo**: native iOS and Android apps, and a browser build through React
Native for Web. Expo supplies the build service, over-the-air updates, file-based universal routing (Expo Router) and
well-maintained modules for secure storage, images, sound and in-app purchases.

Why this is a good fit for this app, and what to watch:

| Concern | Position |
|---|---|
| Mostly text, images and panels | Fits React Native well; no custom rendering engine is needed |
| Streamed rich text | Narration uses a small subset of markdown (paragraphs, emphasis, quotes, lists). Write a tiny renderer for that subset, shared on all platforms, instead of depending on a large library whose web and native behavior differ |
| Streaming over HTTP | Core React Native `fetch` has not streamed response bodies; Expo's own `fetch` and several libraries add streaming. Verify in the first spike. The design in section 6 (a numbered event log that can be read in pieces) makes the transport swappable |
| Long transcripts | Use a virtualized list; keep the transcript model as plain data |
| Look and feel (chrome) | No CSS-only tricks. The chrome plan in [ART.md](ART.md) section 8 is chosen to work in React Native: flat tokens, a few images, and SVG ornaments |
| Browser quality | The web build is the least native of the three. A PC layout must be designed on purpose (section 5), and every library chosen must have a web implementation or an adapter |
| Purchases | RevenueCat's SDK covers the stores; web payments use Stripe; both feed one ledger ([TURN_COST.md](TURN_COST.md) section 11) |

### 3.2 Staying portable (and easy for Claude Code to port)

The aim is that a feature is written once and a port is a small, checkable change. Habits that make that true:

1. **A UI-free `core` package**: the API client, the turn-stream reader, the event reducer that turns server events
   into state, the view models (choices, status, compendium, map, campaign library), the formatting rules and the
   narration renderer's parser. No React Native import is allowed in it. It is tested with ordinary unit tests and
   shared by every build.
2. **A `ui` package of components built on design tokens**, with layout driven by container size (section 5).
3. **Platform seams as interfaces**: `Purchases`, `SecureStore`, `Haptics`, `Share`, `Notifications`, `AudioPlayer`,
   `FilePicker`. Each has a native and a web implementation, chosen with Metro's platform file extensions
   (`.native.ts`, `.web.ts`, `.ios.ts`). A port is "implement this interface for the new platform".
4. **A written `PORTING.md`** with the rules above, the list of seams, and a checklist for a new platform. It is also
   the file Claude Code reads first.
5. **Executable truth for ports to be judged against**:
   - recorded server event streams replayed through the reducer in every build (the existing
     `client/tests/fake_server.py` seeds this);
   - screenshots of the same screens at fixed sizes on each platform (Maestro for phones, Playwright for the browser);
   - CI that builds every target on every change, so a platform never silently falls behind.
6. **One contract with the server**, generated, not hand-copied: TypeScript types from the OpenAPI schema FastAPI
   already publishes, and from a JSON Schema bundle for the stream events (defined as Pydantic models on the server).
   A test fails the build when they disagree.
7. **A capability handshake**: the client sends its version and features; the server answers with what it supports and
   a minimum client version, so an old app in the field can be told to update and new server features can be switched
   on gradually. This matters once a build sits in a store review queue.

Honest limits of "Claude Code will do the ports": it is good at translating a well-tested feature to a new seam and at
repetitive layout work; it is weaker at judging how something feels on a device. Plan for you or a tester to run each
release on real phones and a real browser, and keep the screenshot checks as the safety net.

### 3.3 Desktop

Options, cheapest first:

1. **The browser build as a PWA.** Installable from the browser, no extra work. Likely enough at launch.
2. **A wrapper around the web build** (Electron or Tauri): a real window, an installer, notifications, and a place in
   desktop stores such as Steam. Almost no new code; the wrapper is a thin shell with the same seams. Add it when
   there is a distribution reason.
3. **Native React Native desktop** (the Microsoft-maintained macOS and Windows targets): more native feel, more
   maintenance, and the libraries you rely on need desktop support. Not recommended unless the wrapper proves
   inadequate.

### 3.4 What changed from the earlier draft

The first draft recommended web technology wrapped for the phones. React Native was chosen instead. The consequences
are the shape of the chrome (no CSS borders), the need for an event-log transport that does not depend on browser
streaming, and the need to design the browser layout deliberately. The decision gate that remains: if the browser
build cannot reach the quality a PC player expects, build a separate web view layer over the same `core`. The UI-free
core makes that affordable.

### 3.5 First spike (one week)

A first build now exists in the browser ([REACT_APP.md](REACT_APP.md)); the spike below still has to be run on a
phone-sized native build.


Build the hardest screen end to end on an iOS simulator and in the browser: streamed narration with an ink-in effect,
a dice animation, a portrait, a choice sheet with sub-choices, and the free-text field with the keyboard open. Success
means: streaming works on both, scrolling stays smooth with 300 messages, and the same components render acceptably at
phone and PC widths.

## 4. Billing and the free tier (summary)

Detail is in [TURN_COST.md](TURN_COST.md) section 11. In short:

- A **free tier** that is intentionally limited: one short campaign (or its first chapters), a daily turn allowance,
  few typed turns, no custom games.
- **Pay as you go**: credit packs bought as consumables (in the app stores, or on the web).
- **Subscription tiers**: a monthly allotment of credits plus features (more typed turns, custom games, cloud saves,
  the full library).
- One **ledger** on the server; the stores and Stripe only add credits or set the tier.
- The stores take a commission on digital purchases made inside the apps. Rules differ by region and have been
  changing; check them before pricing.

## 5. Layout: PC and phone from one component set

| Area | PC browser (wide) | Phone (narrow) |
|---|---|---|
| Story | centered column, large type | full width, shorter paragraphs |
| Choices | a panel under the story, keys 1 to 5 | a bottom sheet with large tap targets |
| Free text | inline field beside the choices | opens from a "Say it yourself" button above the keyboard |
| Portraits | a side column showing who is speaking | a small avatar beside each line of dialogue |
| Party, sheet, journal, map | persistent side panels | drawers or tabs from a bottom bar |
| Illustrations | a banner above the page | a card that collapses as you read |

Rules: one component per concept, layout from container size rather than device sniffing; every action reachable by
touch and keyboard; text scales with the system setting; reduced-motion and high-contrast are tokens.

## 6. Server changes this implies (summary)

1. **Resumable turns as an event log.** A phone locks, a tab sleeps, a train enters a tunnel. Today a dropped stream
   loses the reply. Make `POST /chat` start a turn and return a `turn_id`; the turn runs as a server task writing
   numbered events to a short-lived log; the client reads `GET /turns/{id}/events?after=N` as a stream, and re-reads
   from its last number after any interruption. This is also what lets the transport vary by platform.
2. **Accounts, per-user storage, a credit ledger, limits** (section 2).
3. **Campaign packs**: a loader, variation, authored scenes ([CAMPAIGNS.md](CAMPAIGNS.md)).
4. **Choice protocol** ([CHOICES.md](CHOICES.md)).
5. **Asset serving**: pack and library art from storage behind a CDN; no runtime image generation at launch
   ([ART.md](ART.md)).
6. **Turn pipeline changes** for cost and speed ([TURN_COST.md](TURN_COST.md)).
7. **Schema publishing** for generated client types (section 3.2).

## 7. Suggested phasing

| Phase | Content | Proves |
|---|---|---|
| 0. Server groundwork | event-log turns; accounts and per-user saves; event schemas; capability handshake | the backend can serve a paying public |
| 1. App skeleton | React Native app on iOS and web with streaming story, choices, free text, status, journal, placeholder look; the spike in 3.5 first | the platform choice; the interaction is fun |
| 2. Campaigns | pack format with world packs, loader, variation, authored scenes; a pilot world and two short campaigns, the first distilled from a real game; the designer tools | the narrative-quality hypothesis, before any art spend |
| 3. Economy | credits, tiers, free tier, metering, moderation | unit economics |
| 4. Beta | TestFlight and a public web beta with a few packs and the cheap art kit | retention and cost in real play |
| 5. Launch | iOS and web; then Android | |
| 6. Later | desktop wrapper; more packs; site maps; tactical combat; audio | |

Phase 2 deliberately comes before art and billing: the bet is that stories are the product, so test the stories first.
The first packs are **short campaigns** sharing a few worlds ([CAMPAIGNS.md](CAMPAIGNS.md) section 3), which keeps
both the authoring and the art small.

## 8. Decisions

Settled by the product owner: React Native first; browser build and possibly a desktop wrapper; art is just enough;
chrome is the cheapest path; narrative quality is the differentiator; pay as you go plus tiers with a limited free
tier; one or two launch rulesets.

Still open:

1. **Tabletop ruleset** ([LAUNCH_RULESETS.md](LAUNCH_RULESETS.md)): SRD 5.2 (recommended) or Pathfinder 2e.
2. **Whether campaigns are included in tiers or sold separately** (section 4 of [CAMPAIGNS.md](CAMPAIGNS.md)).
3. **Single-player only** at launch (assumed here).
4. **The desktop wrapper**: at launch, or after, or never.
5. **Amounts and the credit unit**: later, with real cost data from the beta.
