# AIGM Time: Design

Status: **spec, not built**. First of two prerequisites to the stakes feature ([STAKES.md](STAKES.md)); the second is
the retry rules for failed actions (ATTEMPTS.md, to be written). Stakes needs deadlines, and a deadline means nothing
unless the clock moves by a believable amount when the party does things, above all when it travels.

## 1. Goal

Time passes by what the party does, and the GM decides how much, as the story makes sense. A journey takes as long as
the road is long, a lock takes minutes, a search takes half an hour. A plain exchange of words, a question or a look
around takes no time worth counting, and that is fine. The clock is in minutes. Time passage lives in the
tools the GM already uses (rolls, setting the scene) plus one for the cases they do not cover. The server adds time
of its own only for a journey, so that moving between places cannot be done for nothing.

Requirements taken from the request:

1. **The clock is in minutes.**
2. **Distances are established as the world is built**, in new worlds by the seed, the plotter, the curator and the GM,
   with a fallback for worlds that already exist.
3. **Actions cost time.** An action that takes time, a retry above all, is never free, even in early chapters. This spec
   builds the mechanism; the action types and their durations come with the retry rules.
4. **Changing location costs time**, enough that a deadline can be meaningful.
5. **The player feels it.** The status view shows the time, and the narration gives a sense of time passing whenever
   it does.

### Non-goals

- Weather, seasons, calendars and moon phases. The clock gives days and hours; what they mean is for later.
- Places or factions changing while the party is away (WORLD.md 1).
- Random encounters on the road, and the party's travel speed by mount, load or terrain beyond a simple pace.
- A map or any new client screen. The status page shows the time as it does now, with minutes.

## 2. Today

- `WorldTime` is `day` and `hour`. `plus()` takes whole hours (`world/model.py`). The status page shows
  `Day 3, 14:00` and a period of the day. The briefing has one clock line.
- The clock moves only when the GM passes `elapsed_hours` to `set_scene` (capped at 30 days) or when the curator reads
  an elapsed time in the narration (`settle_reported_hours`, WORLD.md 2.4). The curator takes the larger of the two so
  the same hours are not counted twice (`World.reported_hours`).
- Nothing knows how far apart two places are. A place has a parent and free-text facts ("3 miles east of Ashby"). The
  GM can move the party across a country with `elapsed_hours` of 0 and nothing objects. The playtests show the GM often
  under-reports time.
- A sub-hour action (picking a lock, a corridor, a conversation) costs nothing.

## 3. The clock in minutes

`WorldTime` gains `minute` (0 to 59, default 0).

- `total_minutes` replaces `total_hours` as the unit of arithmetic; `plus_minutes(n)` is the one way to move the clock.
  `plus(hours)` stays as a convenience.
- Display: `Day 3, 14:20`. The period of the day (dawn, morning, afternoon...) is still from the hour. The briefing
  shows the time to the nearest 5 minutes, and so do the clients' status views.
- `set_scene` takes `elapsed_minutes` (0 to 43200, thirty days). `elapsed_hours` is still accepted and multiplied by
  60, so the GM's habit does not break, but the tool prompt now asks for minutes.
- The curator reports `elapsed_minutes` in place of `elapsed_hours`, and `World.reported_hours` becomes
  `reported_minutes`.
- `/status` and the history summary carry `world_time: {day, hour, minute}`. A save from before this has no `minute`,
  which reads as 0. Clients that ignore the new field keep working. API.md changes to match.
- The deadlines of STAKES.md use the same type, with `minute` optional (0).

## 4. What moves the clock

The GM decides how much time passes, as it makes sense for the scene. There is **no ambient time**: a turn that is
only talk, a question, or a quick look can take no time at all, and especially a turn that triggers no dice.

Time passage is part of the tools the GM already uses, so that saying what happened and saying how long it took are one
call. There are three ways to spend time:

| Way | When | Argument |
|---|---|---|
| A **roll** | The action being tested takes time: a lock, a climb, a search, a negotiation | `minutes` on `roll_dice` and `social_check`: how long the action takes |
| **Setting the scene** | The party moves, waits, rests or sleeps | `elapsed_minutes` on `set_scene`; for a move the server computes the journey from the route (section 5) |
| **`pass_time`** | Time passes with no roll, or a roll's result forces more time | `minutes` and a short `reason` |

Rules:

- **The sources add up**, so each stretch of time is declared once, in the tool that fits it. `set_scene`'s
  `elapsed_minutes` is the time that passed *beyond* what the rolls and `pass_time` calls of this turn already
  counted: waiting, resting, the road. The prompts say so.
- A roll's `minutes` is the time of the action the roll tests. A damage roll, a re-roll and the second die of
  advantage carry none: only the roll that decides the action does.
- **Each call moves the clock when it runs**, as `set_scene` does now, so the clock the GM and the briefing see is
  always current. There is no per-turn bookkeeping and no ambient time: the server only adds time of its own for a
  journey (5.3) and for the end of a combat (section 6).
- A call with no time argument passes none. A roll with no `minutes` is a moment, which suits an attack roll and a quick
  save.
- The curator's narrated time is still a backstop: when the narration describes more time than the turn's calls
  reported, the clock catches up as it does today (`reported_minutes` is the sum of everything above).
- A failed turn rolls the clock back with the rest of the working copy.

### 4.2 The `pass_time` tool

A new tool, available in the adventure phase:

```jsonc
{ "minutes": 45, "reason": "Kit and the steward talk through the household accounts" }
```

- For time that passes without a roll: a conversation that needs no check, a wait, a watch kept, the party studying a
  map. Also for the time a roll's **result** forces: a failed climb that cost an hour of searching for another way. The
  GM calls it after it has seen the roll.
- `minutes` is 1 to 1440 (a day) per call; longer stretches belong to `set_scene` (a journey, a long wait).
- `reason` is one line, kept with the clock history so the debug view can say why the time moved.
- The result gives the new time. The GM does not call it for a moment.

### 4.1 The player feels the time

Time passing has to be felt, and the clock has to be visible:

- **The status view** shows the time with minutes, as `Day 3, 14:20` with the period of the day, in the terminal client
  and the app (it does this now, to the hour). The app's status panel and the terminal client's status screen both
  refresh it each turn.
- **The narration** gives a sense of the passage whenever it is more than a moment. The briefing tells the GM how much
  time the last turn took (declared or added) and the rules for the prompt are:
  - at about **half an hour** or more, a cue: the light, the weariness, a candle burned down, "a little while later";
  - at about **four hours** or more, the time of day too, and what changed with it (shops closing, dusk, hunger);
  - for a **day or more**, say how many days and how the party fares (rations, sleep, the weather turning);
  - for a journey, say how long it took and what the party saw on the way, never a skip in one line.

  The curator's backstop catches a narration that says "two days later" with no `set_scene`.

## 5. Distances and travel

### 5.1 Places have a scale

A location gets a **scale**, so the server can estimate a distance between places it has no figure for:

| Scale | Meaning |
|---|---|
| `room` | A room, a cave chamber, a stall, a yard |
| `site` | A building, a dungeon, a ruin, a camp: made of rooms |
| `settlement` | A village, a town, a city |
| `region` | A forest, a valley, a coast: made of settlements and sites |

`establish` takes `scale` for a new location. The curator's checklists already tell a site from a settlement
(WORLD.md 5.3), and the plotter and seed already create places of each sort; they now say which.

### 5.2 Routes

A **route** is a recorded travel time between two places:

```jsonc
{ "a": "e004", "b": "e011", "minutes": 2880, "how": "over the Harrow Pass on foot", "source": "seed" }
```

- Routes are symmetric and stored on the world (`World.routes`). `source` is `seed`, `plotter`, `generated`,
  `improvised`, `play` (learned, 5.4) or `estimate`.
- `establish` gains `routes` on a location entity: `{"to": "Icehold", "hours": 48, "how": "..."}` (or `minutes`).
  A route may name any recorded place; the entity it joins is the new location.
- **A new place that is not inside the place the party is in must have a route to somewhere recorded.** That is the
  rule that "establishes distances as we build out the world". `establish` asks for it and the tool result says what is
  missing; it does not refuse the place, since a refusal costs the GM a round.
- The seed, the plotter and the curator's expand pass are told to give each new settlement, site and region a route to
  a place already recorded, with a believable time at walking pace (a long day on foot is about 8 hours, 25 miles on a
  good road is a day). The chapter 1 plan's quest places get routes first.
- The briefing's "From here" lines give the GM the recorded routes out of the current place, so it does not invent
  different ones. `recall` shows a place's routes.

### 5.3 What a move costs

When `set_scene` changes the location, the server finds the cost of the journey from where the party was:

1. **A recorded route** between the two places, or the shortest path over recorded routes (summing minutes).
2. Otherwise an **estimate** from the scales and the tree (section 5.5).

That cost is the journey's time. If the GM gave no `elapsed_minutes` with the move, the journey takes exactly that. If
the GM declared less, the clock is raised to it and the GM told ("The road from Ashby to the mine takes about 6 hours;
the clock is moved to match"). If the GM declared more, the declared time stands: a stop on the way, a delay, or a slow
pace.

**Pace.** `set_scene` may pass `pace`: `normal` (the default), `fast` (mounted, a coach, a river boat: half the time) or
`instant`. **Travel is not instant** unless something in the game demands it, such as a teleportation spell, a portal or
a magic item. Both `fast` and `instant` need a one-line `how` naming the in-game means, and the server refuses them
without it; it keeps the reason with the route. Whether the party really has the means is the GM's judgement, and the
prompt tells it to use them only when the story has given them.

### 5.4 Routes learned in play

When the GM moves the party between two places that have no recorded route, and the declared time is longer than the
estimate, the declared time is recorded as a route with `source: play`. The way back then takes the same time, and so
does the next trip. A route already recorded is never changed by play; only `establish` or the curator corrects one.

### 5.5 The fallback for existing worlds

A world made before this has no scales and no routes. It works at once on estimates:

- **Scale** is read from what the world already records: the curator's site and settlement classification, the place's
  depth in the tree, and whether it has children. A place with no inferred scale is taken as a `site`. The scales are
  stored the first time they are needed, and the curator may correct them in a later pass.
- **The estimate** uses the lowest ancestor the two places share, and the scales of the places below it:

| The two places are... | Estimate |
|---|---|
| The same place | 0 |
| Rooms of the same site | 5 minutes |
| Two sites in the same settlement | 20 minutes |
| A room of one site and another site in the same settlement | 25 minutes |
| Two settlements or sites in the same region | 6 hours |
| In different regions | 2 days |
| With no common ancestor | 1 day |

The figures are data in `aigm/travel.py`, tuned after play tests.

Because every trip a GM makes is also written down as a route (5.4), an old world fills in its own map as it is played.
No migration pass is needed. A one-time curator pass that asks for routes between the places a world already has is an
option for later (section 11).

## 6. What actions cost

An action that takes time costs time, and the GM states how long in the tool that tests it (section 4). The kinds of
action and the durations they usually take come with the retry rules (ATTEMPTS.md), whose `attempt` record carries the
duration of each try by action type. That is what makes a retry cost something even in chapter 1: the second try is
another roll with its own `minutes`.

- **Rolls.** `roll_dice` and `social_check` take `minutes`. The prompts give a guide: a lock ten minutes, a search of a
  room half an hour, a hard climb an hour, a negotiation an hour, a quick check none.
- **Combat.** `set_combat` with `action: "end"` takes `minutes`, and if it is omitted the server assumes 10, since a
  fight takes more than a round.
- **Rests.** The GM declares them in `set_scene`: a short rest is an hour and a long rest eight, whatever the ruleset
  calls them. The ruleset prompts say which.
- **Conversation.** Ordinary talk costs nothing. A long talk the GM wants to count is `pass_time`, or the `minutes` of a
  `social_check` if one is rolled.

## 7. What the GM sees

The briefing shows:

- the time to the nearest 5 minutes and the period of the day;
- how much time the last turn took and why, for the narration cues of section 4.1;
- the routes out of the current place, as `From here: Icehold, 2 days over the Harrow Pass; Millford, 3 hours by road`;
- in a story game, the deadlines and the fraction of time used (STAKES.md 8), which this clock makes meaningful;
- a note when the server added time last turn ("added 6 hours for the road to the mine").

The tool prompts say:

- `set_scene`: give `elapsed_minutes` for everything that passed since the last reply, travel and waiting included; the
  server will raise a journey that is shorter than the road. A turn of talk with no dice can pass none.
- `establish`: give a new place a `scale`, and routes to places already recorded.
- `roll_dice` and `social_check`: give `minutes` for the action the roll tests, and nothing for damage or any roll that
  only follows another.
- `pass_time`: for time that passes with no roll, or that a roll's result forces. Never for a moment.
- the system prompt: time passes when the party acts, and travel takes as long as the road. Never skip a journey in a
  line: say how long it takes and what the party sees.

## 8. Interactions

- **Curator.** Its `elapsed_minutes` is the backstop. If the GM forgot `set_scene` and the narration says "two days
  later", the clock catches up as it does now, and a move the curator records is checked against the routes too.
- **Stakes.** `due_failures` (STAKES.md 3) compares `total_minutes` to deadlines; capture extends or caps hours in
  minutes. Both read this clock and nothing else.
- **Story.** Chapter changes and quest briefs can carry travel times between their places, via routes the plotter wrote.
- **Rolling back a turn.** The clock, the routes learned and the time passed are on the staged copy, so a failed turn
  leaves no trace.

## 9. Data

- `WorldTime`: `minute`. `World`: `routes: list[Route]`, and `reported_minutes`. The clock moves when each tool runs.
- `Entity` (locations): `scale`.
- The save format bumps; an old save reads with `minute` 0, no routes, no scales (5.5).
- The hidden-state debug view lists scales, routes and the reasons the clock moved this turn.
- The compendium and the clients show nothing new except the minute in the time.

## 10. Build steps

1. The clock: `minute`, `plus_minutes`, `elapsed_minutes`, the curator's minutes, the API and the clients' display.
2. Passing time: `minutes` on `roll_dice` and `social_check`, the `pass_time` tool, `set_combat`'s end, the briefing
   line about the last turn's time.
3. Scales and routes: the model, `establish` and its validation, `recall`, the debug view, the briefing lines.
4. Travel: the move cost in `set_scene`, the estimate table, `pace`, routes learned in play.
5. Building the world: the seed, the plotter and the expand pass produce scales and routes.
6. Prompts (including the narration cues of 4.1) and a live check with the real GM: a long trip, a short one, an old
   save.

## 11. Left for later

- A one-time pass that fills routes for an old world.
- Terrain, weather and night travel; a pace by mount or load; encounters on the road.
- Travel that the GM narrates in several legs, each with its own stop.
- A map view of the routes in the app.

## 12. Open questions

None at the moment.
