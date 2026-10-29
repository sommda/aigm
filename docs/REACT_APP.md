# AIGM React App: the First Build

Status: **built** (web). This is the first cut of the graphical client described in [APP.md](APP.md): a React Native
(Expo) app that, for now, runs in the browser on a Mac or PC. It does everything the terminal client does for a normal
game, with the same text interaction, and nothing more. It is the frame the later features (choices, portraits, maps,
a phone layout) are meant to slot into.

The code is in `app/`. It is its own npm project and shares nothing with `server/` or `client/` but the HTTP API
([API.md](API.md)).

## 1. Running it

```bash
# terminal 1: the server (debug mode adds the hidden tab and per-turn timings)
cd server && uv run aigm --debug        # or: uv run aigm --test   (scripted, no model)

# terminal 2: the app
cd app && npm install && npm run web    # opens http://localhost:8081
```

The app talks to `http://127.0.0.1:8000` by default. Another server or session can be chosen in the page address,
`http://localhost:8081/?server=http://host:8000&session=name`, and the choice is remembered; or with
`EXPO_PUBLIC_AIGM_URL` and `EXPO_PUBLIC_AIGM_SESSION` when starting.

The server already allows browser pages served from `localhost` on any port (CORS), so no server change was needed.

**Saves are the server's.** Save, load and delete call the same routes the terminal client uses, and the files are the
same files in `server/saves`, so a game saved in one client loads in the other. The app and the terminal client share
the server's `default` session while they use it, so use one at a time, or give one of them another session name.

## 2. What is in it

| Area | Built |
|---|---|
| Story | one large scrolling pane; streamed narration with formatting; dice rolls; system lines (saves, chapters, awards, errors); a Reasoning toggle for the model's thinking |
| Input | a smaller multi-line pane at the bottom: Enter sends, Shift+Enter adds a line, Stop and Esc cancel a running turn; slash commands work at any time |
| Tabs | **Status** (the place, then one tab per character) and **Compendium** (Locations, Characters, Other, and Hidden on a debug server), opened from the top bar |
| Layout | an open tab takes the **upper half** of the story area and the story keeps the lower half; the player can keep playing with a tab open; the tab refreshes after each turn |
| Compendium | tabs with counts and unread marks, a list and the entry beside it (stacked on a narrow screen), links between entries with Back, name filter (asked of the server), unread only, next unread, mark all read, read marks after a second of reading |
| Game menu | Save, Load, New game dialogs (list of saves with preview, overwrite and discard confirmations, delete); `/save`, `/load`, `/new`, `/saves`, `/info`, `/delete` |
| Session | Session 0 and the adventure exactly as in the terminal client; phase, ruleset, game name with `*` for unsaved, story chapter, and the compendium's unread count in the bar |
| Debug servers | the Hidden tab, `/story`, `/thinking`, and the per-turn timing line |

Not in it yet, on purpose: the context viewer (`/context`; use the terminal client), the pager (the terminal client
holds text back page by page; here the story simply scrolls and follows the newest text unless the player scrolls up),
choices, portraits, maps, any chrome beyond a plain dark theme, a phone layout, and the native iOS, Android and macOS
targets.

## 3. How it is built

```
app/
  App.tsx                 the root: loads the config, shows the game screen
  src/core/               no React Native imports; Jest-tested
    sse.ts events.ts      the stream, decoded into typed events
    api.ts                the HTTP client; the transport is injected
    markdown.ts           a small markdown parser that is safe on partly received text
    blocks.ts session.ts  the transcript and how each event changes it (a port of the terminal client's session.py)
    compendiumModel.ts statusModel.ts panels.ts   what the two tabs show, and when they ask the server
    controller.ts         the flows: startup, a turn, save, load, new game, slash commands
  src/platform/           the seams: transport.ts (fetch and XMLHttpRequest), config.ts
  src/ui/                 React Native components and the design tokens (theme.ts)
  tests/                  Jest tests of src/core
  e2e/                    Playwright tests against the built bundle and a scripted server
```

Decisions worth knowing:

- **The core has no UI.** `controller.ts` runs every flow and asks the UI for anything it needs (a dialog, a panel)
  through a small `Prompter` interface. The UI is thin, so a new platform or layout reuses all of it
  ([APP.md](APP.md) section 3.2).
- **The event stream is read with `XMLHttpRequest`,** which hands over text as it arrives in the browser and in React
  Native alike, while `fetch` in React Native does not stream. One implementation serves every platform, and the choice
  is isolated in `src/platform/transport.ts` so it can change (a WebSocket, or the numbered event log in APP.md
  section 6) without touching anything else. The native path has not been run yet (see section 5).
- **Streaming markdown is parsed, not healed.** The terminal client patches the text with extra markers so a renderer
  shows formatting early. Here an inline style still open at the end of the text simply stays on to the end, and a
  half-received block or marker draws nothing. A test feeds every prefix of a sample reply to the parser.
- **Updates are coalesced** (about 30 a second) so a fast stream does not redraw the whole story on every word.
- **One panel at a time.** The Status and Compendium buttons act as tabs for the dock; each has its own inner tabs.
  Opening one replaces the other, and closing the dock gives the story the whole height back.

## 4. Tests

Run in `app/`; all three must pass.

| Command | Covers |
|---|---|
| `npm test` | Jest: the SSE decoder and event parser, the markdown parser, the session, the API client against a fake transport (odd chunking, rejected and dropped streams, abort), the controller flows with a fake player, the compendium and status models and panels |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run e2e` | exports the web bundle, starts a scripted server (`aigm --test --debug`, in a throwaway save folder) and drives the page in Chrome with Playwright: streaming and formatting, Enter and Shift+Enter, the tabs sharing the screen (it measures that the dock and the story are about equal in height), save, load and new game against the real routes, slash commands, Esc cancelling, and the story following new text. Screenshots go to `e2e/shots/` |

## 5. Known gaps and risks

- **Not a native Mac window.** The Mac used for this build has no Xcode, which a React Native macOS app needs, so the
  build runs in the browser (the choice made when starting). A native Mac window, an iOS build and an Android build all
  need Xcode or Android Studio and have not been tried. The code uses only core React Native components, so they
  should come with little change; the one thing to check first is that the `XMLHttpRequest` stream delivers text
  progressively on a device ([APP.md](APP.md) section 3.5).
- **A long game rerenders its whole transcript** when it changes. That is fine for hundreds of blocks; thousands will
  want a virtualized list.
- **Page-level keyboard shortcuts** (Esc) are installed only on the web.
- **Chrome is minimal by design** ([ART.md](ART.md) section 8): flat panels, a serif story face and a dark palette, all
  from tokens.

## 6. Where it goes next

1. Try it against a real model, in a real Session 0, and fix what the scripted server cannot show.
2. The phone layout: a single column with the tabs as sheets, so the same screens work on a narrow window.
3. Choice cards and their sub-choices ([CHOICES.md](CHOICES.md)), which need the server's `choices` event first.
4. A native build once Xcode is available, starting with the spike in [APP.md](APP.md) section 3.5.
5. The context viewer, if the terminal client is not enough.
