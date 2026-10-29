# AIGM app: notes for Claude

The graphical client: React Native (Expo), TypeScript, running in the browser first. It talks to the same server as the
terminal client and shares nothing with it but the HTTP API. See `docs/REACT_APP.md` for what is built and why, and
`docs/APP.md` for where it is going.

## Layout

- `src/core/`: everything with logic, **no React Native imports** (API client, SSE, events, markdown parser, session,
  panels, controller). Unit tested with Jest. A feature starts here.
- `src/platform/`: the seams (transport, config). Anything platform specific goes behind one of these.
- `src/ui/`: React Native components built from the tokens in `theme.ts`. Thin; no game logic.
- `tests/`: Jest tests of `src/core`. `e2e/`: Playwright tests against a built web bundle and the real server in
  test mode.

## Commands (run in `app/`)

```bash
npm run web          # dev server at http://localhost:8081 (needs the server: cd ../server && uv run aigm --debug)
npm test             # Jest
npm run typecheck    # tsc --noEmit
npm run e2e          # exports the web bundle, starts a scripted server on :8765, runs Playwright (uses Chrome)
npx expo install <package>   # always use this instead of npm install for libraries
```

`npm test`, `npm run typecheck` and `npm run e2e` must pass before work is called done.

## Rules

- Expo changes between SDKs; check https://docs.expo.dev/llms.txt before using an Expo or React Native API you are
  not sure of.
- No Expo Router yet: the app is one screen. Add it when there is a second one.
- Keep the UI usable by mouse, keyboard and touch, and keep layout driven by container size, not device checks.
- Colours, spacing and fonts come from `src/ui/theme.ts`; never hard-code them in a component.
- Saves are the server's, in `server/saves`. The app never writes save files itself, so the terminal client can read
  them.
