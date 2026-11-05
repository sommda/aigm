# Desktop layout of the graphical client

Status: **built** (all five steps of section 10). It changes how the screens of the graphical client
([REACT_APP.md](REACT_APP.md)) are laid out on a wide window. The server, the terminal client and the core logic of the
app stay as they are, apart from the small changes in section 8.

## 1. Why

Today the story fills the window and the Status and Compendium tabs open as a dock that takes the upper half of it, so
looking at a character means hiding half the story. The location picture and the party's health are what a player
glances at most. On a desktop they should always be in view, beside the story, and the details of whatever the
player is interested in should open next to it, not over it.

## 2. The screen

```
+------------------------------------------------------------------------------+
| AIGM  [Compendium] | Save Load New Reasoning            status line           |  top bar
+----------------------------------------------+-------------------------------+
|                                              |  STATUS                       |
|                                              |  Sedge Hollow Farm            |
|  the story                                   |  Day 1, 22:25 · night         |
|  (scrolls, follows new text)                 |  [ picture of the place ]     |  right,
|                                              |  Drex Dreer   Paladin 3  22/25|  top
|                                              |  Galdric      Cleric 3   24/24|
|                                              |  Audain       Ranger 3   25/25|
|                                              +-------------------------------+
+----------------------------------------------+  DETAILS                      |
|  your reply                                  |  (the place, or the character |  right,
|  (about three times as tall as before)       |   you clicked, in full)       |  bottom
|                                              |                               |
+----------------------------------------------+-------------------------------+
        left pane                                         right pane
```

- **Top bar**: as it is now, minus the Status button: the title, **Compendium**, Save, Load, New, Reasoning, and the
  status line (the working spinner and note on the left; phase, game name, story, unread count and connection on the
  right).
- **Left pane**: the story above, the reply field below. The story is the whole of the pane except the reply field.
- **Right pane**: split into a top section (the status) and a bottom section (the details). Sections 4 and 5 describe
  them; section 6 describes how the Compendium takes the right pane over.

### 2.1 Sizes

- The left pane takes 60% of the width below the bar and the right pane 40%, but the right pane is never narrower than
  360 px nor wider than 560 px. Within the right pane the status takes 45% of the height and the details 55%. Each
  section scrolls by itself when its content is taller. Fixed proportions come first; a draggable divider is a
  later addition (section 10).
- **The reply field is three times as tall as now.** The field is 76 px high today (three lines of text plus padding)
  and it becomes 228 px, growing no taller than 40% of the left pane. There is no Send button: Enter sends and
  Shift+Enter adds a line. A Stop button shows over the field's bottom right corner while a turn runs.
- **Narrow windows.** Below 900 px of width the two panes would be too cramped, so the layout falls back to one column:
  the top bar, then the right pane as a block of 40% of the height (the status above, the details below, or the
  Compendium) with a **Hide** button on its title, then the story and the reply field. This keeps the app usable on a
  phone-sized window without a second design; it is not tuned further in this spec.

## 3. Navigation

There is no Status button and no dock. The right pane is always showing something:

- Its **default** is the status in the top section and **the place** in the details. A fresh window, a new game and a
  loaded game all start there.
- Clicking a **character** in the status shows that character's full sheet in the details (the page the Status tab's
  character tabs show today: portrait, headline, hit points and conditions, Look, the sections of the sheet).
- Clicking the **place** (its name or its picture) shows the place in the details again: the overview, the view, who is
  here, key items, what lies inside, the ways out and the table of everyone here (or the fight).
- The clicked row is highlighted. What the details show survives a turn: after each turn the page being shown is
  fetched again, and a character who has just been written out of the party falls back to the place.
- **Compendium** (the button, which toggles) replaces the whole right pane, section 6. Esc closes it, as it closes the
  dock today (a dialog first, then a running turn, then the Compendium).
- The slash commands keep working: `/status` returns the right pane to the status with the place in the details (and
  closes the Compendium if it is open), and `/sheet NAME` does the same with that character's sheet in the details.
  `/compendium [TAB|NAME]` opens the Compendium as it does today.

## 4. The status (top right)

From the top down:

1. **The place.** Its name; under it where it lies and when it is ("in Northern Reaches, Kingdom of Aurendell · Day 1,
   22:25 · night"); and its picture. The picture keeps the shape the server gives it (landscape fills the width of the
   pane at 3:2) but is no taller than the section, so the party below it stays in view; if the section is too short
   for both, the section scrolls. While the picture is still being painted the pane shows what it shows today
   (a waiting frame) and looks again every few seconds.
2. **The party.** One row per member: the first name (the click target), the headline short form ("Paladin 3"), hit
   points as "22/25" (green; yellow below half, red below a quarter) and the conditions, if any, after them. Nothing
   else: the rest is in the sheet.

If the server has no status page (`/health` lacks `status`), the section says so, as the Status tab does today.

## 5. The details (bottom right)

Exactly the content the Status tab shows today for the place and for a character, in the pane's width (the sheet's
portrait goes above the text when the pane is narrow). Nothing new is added to either page. The Refresh button of the
Status tab goes: the pane refreshes after every turn and when a window regains focus.

## 6. The Compendium in the right pane

The Compendium works as it does now (its tabs, filter, "Unread only", "Next unread", "Mark all read", Refresh, links
between entries, the dwell that marks an entry read, the Hidden tab on a debug server) with two changes:

- It occupies the **whole right pane**: the status and the details are hidden while it is open. A **Close ✕** button
  sits at the top right of the pane and the Compendium button on the bar toggles it too.
- Its two parts are **stacked**, whatever the window's width: the tabs, filter and buttons, then the **list** of
  entries in the top half, and the **detail** of the selected entry in the bottom half. The list no longer has a fixed
  width of 300 px (it fills the pane), and the "‹ List" and "Back" buttons of the narrow layout are not needed: the
  list is always visible, and "‹ Back" (back along the links followed) stays above the detail when there is a trail.

Opening it does not lose the place in the status: closing it brings back the same character or place in the details.

## 7. The story and the reply

Unchanged apart from the pane they live in and the taller reply field. The story keeps following new text unless the
player has scrolled up. The placeholder text, the busy state, the Stop button and the slash-command behavior do not
change.

## 8. What changes in the code

- `GameScreen.tsx` stops having a dock. It builds the two columns (and the single-column fallback). The `panel` state
  becomes `compendiumOpen: boolean`; the status panel object lives as long as the screen, so the pane has data from the
  start. It still refreshes the status and the open Compendium when a turn ends.
- A new `SidePane.tsx` holds the right pane: the status section, the details section, and the Compendium when it is
  open. `StatusView.tsx` is split into the status section (`StatusSection`: the place and the party rows) and the
  details (`Place` and `Sheet`, reused unchanged, exported).
- `NavBar.tsx` loses the Status button and its `panel` type; the Compendium button becomes a toggle on a boolean.
- `InputPane.tsx`: `minHeight` 228, `maxHeight` 40% of the pane, `numberOfLines` 9.
- `CompendiumView.tsx` gets a `stacked` mode (always on in the right pane) in place of the width test.
- `core/statusModel.ts` and `StatusPanel` keep a page per tab as they do, but a load now always fetches the status
  page (the place and its picture) next to the roster, and the page of the selected tab if it is a character. The
  status section reads `pages.status` and `roster`; the details read the selected tab's page. The roster already
  carries what the party rows need (`name`, `headline`, `level`, `hp`, `conditions` from `GET /characters`).
- `core/pictures.ts` `frameFor` takes a maximum height in place of the "a third of the window" rule, so the status
  section can say how tall a picture may be.
- `core/controller.ts`: `openPanel("status", ...)` selects the status and the details instead of opening a tab; the
  `/status` and `/sheet` flows keep their meaning (section 3).

No server change is needed.

## 9. Tests

- **Jest**: the status model keeps the status page while a character is selected; a load fetches the status page and
  the selected character's page; a character who has left the party falls back to the place; the controller opens
  the status with the place or a named character for `/status` and `/sheet`; `frameFor` respects a maximum height.
- **Playwright** (replacing the tests of the dock): the left and right panes sit side by side with the reply field in
  the left pane and about the widths of 2.1; the right pane has two sections one above the other; the reply field is
  at least 200 px high; there is no Status button; the status shows the place, its picture and the party rows; clicking
  a character shows the sheet (and its portrait, once painted) in the details and clicking the place brings the place
  back; the Compendium button replaces both sections, its list is above its detail, and closing it restores the status
  and what the details showed; `/status`, `/sheet` and Esc; at 800 px wide the single-column fallback appears.
  Screenshots of the wide layout, a character in the details and the Compendium go to `e2e/shots/`.

## 10. Build order

1. Split `StatusView` into the status section and the details; change `StatusModel`/`StatusPanel` to load the status
   page and the selected page together; Jest.
2. The two-column `GameScreen`, `SidePane`, the taller reply field, the sizes of 2.1 and the picture limit
   (`frameFor`); remove the dock and the Status button.
3. The Compendium in the right pane: the `stacked` mode, the Close button, the toggle, restore on close.
4. The slash commands and Esc; the narrow-window fallback.
5. Rewrite the Playwright tests; `npm test`, `npm run typecheck`, `npm run e2e`; update REACT_APP.md (the layout, the
   tabs table and the "one panel at a time" rule) and the screenshots.

Later, not in this spec: a draggable divider between the panes and between the two right sections (remembering where it
was put), and showing the people present in the status.
