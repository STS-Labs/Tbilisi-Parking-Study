# Stage 7 — Animated route playback

Read `CLAUDE.md`. Consumes Stage 5 (`05-routes.gpkg`) and, when present,
Stage 6 (`06-coverage.gpkg`).

## What this is

**A car moving across a map, replaying each day's driving**, so a person can watch
the order streets get covered and see the campaign build up.

## Why it matters more than "a dashboard"

932 tests prove the plan is *legal*. Nothing proves it is *sensible*. A human
watching the car zigzag across a district, double back, or cross the city
mid-morning will spot in ten seconds what no invariant can express. **This is the
first time anyone can look at the plan and say "that's stupid."** Build it as a
verification tool that happens to be attractive, not a presentation piece.

## Data source

Build against the **planned** routes now — that is all that exists. Structure the
data model so a Stage 6 **actual** trace can be overlaid on the same day later
(planned in one colour, actual in another, divergence visible). Do not stub the
actual layer with fake data; leave it absent and switchable.

## The single most important visual: mode

Every manoeuvre in `05-routes.gpkg` carries a `mode`. Colour the car's trail by it:

- **capturing** — the camera is recording. This is the work.
- **deadhead** — repositioning, filming nothing.
- **depot leg** — travel to and from base.

Deadhead is ~58% of driving. Seeing that as colour on a map communicates more than
any number in any report has so far, and it is the thing most likely to prompt
"why is it doing *that*".

## Architecture — this is what makes it smooth rather than a slideshow

### Prep step (Python, `dashboard.py`)

Emit one compact JSON per day into `reports/07-playback/data/day-NN.json`:

```
{ "day": 1, "date": "2026-08-25", "start_s": 32400,
  "segments": [ {"mode":"capture","t0":0.0,"t1":12.4,"c":[[lon,lat],...]}, ... ],
  "totals": {"capture_h":…, "deadhead_h":…, "turn_h":…, "km":…} }
```

- `t0`/`t1` are cumulative seconds from the day's start — precompute them so the
  renderer only interpolates.
- Round coordinates to 5 decimals (~1 m). Simplify geometry with
  Douglas–Peucker at a tolerance well below display resolution.
- Also emit `network.json` once: the whole variant-C network as context geometry,
  simplified harder. **This is the basemap.** No tile server — the street network
  drawn as thin grey lines *is* the map of Tbilisi, which keeps the page fully
  self-contained and free of any external dependency.

### Renderer (`reports/07-playback/index.html`)

**No libraries.** Plain canvas 2D with a Web Mercator projection and hand-rolled
pan/zoom. MapLibre and deck.gl are both overkill here and add a dependency that
would block publishing the page anywhere with a strict content policy.

Three-layer compositing — this is the performance-critical part:

1. **Network layer** — draw all context streets **once** to an offscreen canvas.
   Redraw only on zoom change (debounced).
2. **Covered layer** — a second offscreen canvas. Append each newly-completed
   segment as it is driven. Never redraw it wholesale.
3. **Per frame** — blit layer 1, blit layer 2, draw the in-progress segment and
   the car marker. That is all.

Redrawing 90,000 segments every frame will not hit 60 fps. Blitting two bitmaps
will.

Interpolate the car along the current segment's geometry by elapsed fraction of
`t1 - t0`. Orient the car marker to its heading.

## Controls

- Play / pause, and a **speed multiplier**: 1×, 60×, 300×, 1000× (a 9-hour day at
  300× is under two minutes).
- **Scrub bar** for the current day, showing simulated clock time (09:00–18:00).
- **Day selector** — jump to any of the 47 days.
- **Cumulative mode** — previous days' coverage shown muted underneath, so the
  city visibly fills in across the campaign. This is the view worth watching.
- Toggles: capture / deadhead / legs, network context, cumulative history.

## Readouts, live as it plays

Clock; km captured today; % of campaign complete; hours elapsed vs the day's
budget; current street name if available.

## Outputs

- `reports/07-playback/index.html` + `data/`
- `make stage7`
- `make stage7-embed DAY=n` — a **single self-contained HTML** for one day with
  its data inlined, for sharing. Must work with no network access at all.

## Gate — tests must assert

- Every segment in `05-routes.gpkg` appears exactly once in exactly one day's
  playback file. **No manoeuvre silently dropped by simplification.**
- Per-day `t1` of the final segment equals that day's total driving seconds from
  Stage 5, within rounding.
- Sum of playback `km` per mode reconciles to the Stage 5 report per mode.
- Simplified geometry deviates from source by less than a stated tolerance —
  assert the tolerance, do not eyeball it.
- The embed build contains no external URL of any kind.
- Determinism; all 932 existing tests still pass.

## Non-goals

No live GPS feed. No editing the plan from the page. Read-only.

---

**Look at it before declaring it done.** Open it, play a day, watch the car. If the
route looks unhinged in a way the numbers never showed, that is the stage doing its
job — report it rather than shipping a pretty page over a bad plan.
