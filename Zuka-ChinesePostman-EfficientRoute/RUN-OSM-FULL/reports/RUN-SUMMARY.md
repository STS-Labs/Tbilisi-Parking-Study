# Run 1 — everything OSM has in Zone B, service roads included

> **Zone A was requested and is not in the data.** `data/custom/B Zone_Streets/AB_zones.shp` holds one polygon, `Name = "Zone B"`, despite the layer being called `AB_zones`; its `FolderPath` names `Tbilisi Possible parking zones.kmz` as the source, so Zone A presumably exists there and was never exported. **This run covers Zone B only.** Nothing in it is an A+B result, and no Zone A boundary has been inferred or approximated.


Variant **A**. The same campaign as `CUSTOM-OUTPUT/` in every other respect — same
Zone B polygon, same depot at 41.730736 / 44.734583, same 9 h shift with a 45 min
break, same p75 sizing quantile, same reserved commute profile, same far-zones-first
sequence, same motorway narrowing, same native HMM matcher, same 2 km deadhead
buffer, same midpoint-inside-the-zone required rule.

Reproduce with `sh tools/run-osm-full.sh`; gates with `sh tools/gates-osm-full.sh`.

## Headline

> ## 21 driving days, 2026-08-29 → 2026-09-18
>
> **100.8 h** of driving — 29.8 h capture, 33.8 h deadhead,
> **37.1 h turns** — to cover **674.4 km** of required
> traversal inside a 2,888.2 km drivable clip.
> No day exceeds its window.
>
> **22.1 km of what this scope requires can never be driven**, and
> **37% of the driving is turning**.

| | |
| --- | ---: |
| Required traversal (variant A) | 674.4 km |
| Required centreline | 622.3 km |
| Driving days | 21 |
| Total driving | 100.8 h |
|   capture / deadhead / turns | 29.8 / 33.8 / 37.1 h |
|   depot legs | 6.1 h (6.0%) |
| Days over window | 0 |
| Stage 3 bracket | 54.4 – 88.0 h |
| Optimality gap over the Stage 3 bound | 116.0% |
| Zones sized by Stage 4 | 9 |
| Zone splits forced by Stage 5 | 12 |
| Arc traversals | 44,988 |

## The number to check first: 21 days, against an expected 11–14

**Diagnosed, not accepted.** The scope is right and the driving content is inside the
expected band; the day count is not, and the reason is entirely the sizing constant.

- **Required traversal is 674.4 km**, exactly the figure the brief predicted for
  variant A. Stage 0 and Stage 0b agree, and Stage 2 costs it at 60.2 h of capture
  plus turns.
- **Stage 3 brackets the whole scope at 54.4 – 88.0 h**, which at 8.25 productive
  hours a day is 6.6 – 10.7 days of tour before any depot legs.
- **Stage 5 drives 100.8 h.** At 8.25 h a day that is **12.2 days of content** —
  inside the brief's 11–14 band.
- **The plan is 21 days because Stage 4 sized the zones on a constant that is 51%
  too low for this scope.** `ZONE_OVERHEAD_MEASURED = 2.2598` is Tbilisi's p75,
  transferred by instruction and pinned per CLAUDE.md. Variant A actually drives an
  intra-zone overhead of **3.41 (p75)**. Every one of the nine zones overran its 9 h
  window, twelve splits followed, and each split adds a depot leg pair.

The constant has **not** been re-derived mid-run: CLAUDE.md is explicit that this
loop does not converge and that changing the value is a deliberate, reviewed act.
See `reports/RUNS-COMPARISON.md` §6 for the full sizing analysis across all three
runs — the finding there is that the constant does not transfer across *scopes*, not
just across cities.

## What variant A adds, and what it costs

Against the committed variant C run over the same zone:

| | Variant C | Run 1 | Change |
| --- | ---: | ---: | ---: |
| Required traversal | 390.9 km | 674.4 km | +283.4 km (+72.5%) |
| Total driving | 35.5 h | 100.8 h | +65.3 h (+184%) |
| Driving days | 7 | 21 | +14 |
| Turns | 8.2 h | 37.1 h | **+28.9 h** |
| Turns as a share of driving | 23% | **37%** | +14 pp |
| Deadhead as % of capture | 102% | 113% | +11 pp |
| Required length unreachable | 3.4 km | **22.0 km** | +18.6 km |
| Of the customer's own 347.0 km, filmed | 336.6 km | 337.5 km | **+0.9 km** |

**The extra kilometre costs 0.247 h against variant C's 0.091 — 2.7 times.** The
brief predicted the deadhead ratio would worsen and it does, from 102% to 113%. But
that is not where the money goes.

**The money goes on turns.** Capture rises 16.3 h; turning rises 28.9 h. A
`highway=service` spur is a dead end by construction: the car drives in, makes a
U-turn costing 20 s, and drives out. Every metre is filmed once and driven twice, and
the manoeuvre at the tip costs more than the street it serves. Turn time is now the
largest single term in the day, ahead of both capture and deadhead. **This is
topology, not a regression** — but it is much worse than the raw kilometre count
implies, and it is the reason the honest price for service roads is a separate line
item rather than a blended rate.

**And 22.0 km of it cannot be driven at all.** Orphan service components — a car park
whose only OSM connection is through a barrier, a yard behind a gate — are required
by the midpoint rule and unreachable by any legal tour. Variant C strands 3.4 km;
variant A strands 22.0. So of the 283.4 km variant A adds, 18.6 km is coverage that
exists only on paper. It is logged, not silent: every one appears in the Stage 1
unreachable attribution.

## Coverage

| | |
| --- | ---: |
| Required traversal | 674.4 km |
| Not covered | 22.1 km (3.27%) |
|   unreachable by any legal tour | 22.0 km |
|   **reachable and simply missed** | **0.073 km** |

The 73 m is the same three arcs — 2.6 m, 12.0 m and 19.2 m — that the Zone B campaign
documented and that every run in this repository misses. It does not move with the
scope and it is not a sampling artefact; the decoder reaches the far side of each by
an alternative legal path, so no gap exists to bridge.

## Constants transferred rather than measured for this scope

| Constant | Value used | Where it came from | What Run 1 says |
| --- | --- | --- | --- |
| `ZONE_OVERHEAD_MEASURED` | 2.2598 | Tbilisi p75, 49 solved days | Run 1 measures **3.4081** — 50.8% higher |
| `TURN_PENALTY_S` | left 8 s / right 3 s / u-turn 20 s | SPEC §3.3 estimate, never measured | still **[CONFIRM]**, and now **37% of all driving** — by far the largest unmeasured assumption in this run |
| Speed model coefficients | as fitted for Tbilisi | Stage 2 free-flow + gradient | unchanged; no Zone B traces exist to refit from |
| Congestion multipliers | by class × time band | Tbilisi assumption | unchanged |
| `CAPTURE_SPEED_MAX_KMH` | 40 | SPEC §5, confirmed | policy, not a measurement |
| `MATCH_MAX_CANDIDATE_DIST_M` | 25 | provisional, never calibrated | no real trace in any campaign |

**The u-turn penalty deserves a measurement before this scope is ever quoted.** At
23% of driving it was already the biggest soft number in the Zone B run. At 37% it
dominates the result: a 20 s u-turn that is really 30 s moves this plan by roughly
five hours, and nobody has stood at a junction with a stopwatch.

## Decisions made in this run

| Decision | Choice | Why |
| --- | --- | --- |
| Zone A is absent from `AB_zones.shp` | Ran Zone B alone and stamped every report | The brief forbids inferring or approximating a Zone A boundary under any circumstances. The caveat is written from config into each report so it regenerates rather than being pasted on. |
| Scope variant is a tracked constant | Made it environment-overridable (`EFFICIENTROUTE_SCOPE_VARIANT`) | One checkout has to run variant A and variant C without editing a tracked file between them. Unset it stays "C", so the committed Tbilisi plan does not move. |
| 21 days against an expected 11–14 | Diagnosed and reported, not adjusted | The driving content is 12.2 days and inside the band. The gap is the transferred sizing constant, which CLAUDE.md pins. Re-sizing on the measured 3.41 is a reviewed act, not something this run may do to itself. |
| gate4 asserted `highway_class != "service"` | Replaced with a scope-relative assertion | It was Tbilisi's scope *decision* written down as an invariant, and it failed a variant A campaign for being configured correctly. The gate now asserts the arcs in the tour scope are exactly the arcs the configured variant keeps — which still forbids every service road under C, and catches an undeclared filter under A. |

## Gates

`sh tools/gates-osm-full.sh` — **933 passed, 31 skipped, 0 failed.**

The 31 skips are the Tbilisi-specific regression fixtures that do not apply to a
Zone B campaign, unchanged from the committed Zone B run, plus the Stage 4c
re-zoning comparison this run does not perform.

**One gate remains UNMET rather than passed**, exactly as in the Zone B campaign:
twenty junctions must be checked against satellite or street imagery by a person
before this campaign's turn graph has the standing Tbilisi's has. Nothing here
substitutes for it and nothing was invented in its place.

## Artifacts

| Path | What it is |
| --- | --- |
| `data/derived/00-network-stats.json` | Stage 0 measurements, required/buffer split |
| `data/derived/03-bounds.json` | lower bound and constructive tour, all three variants |
| `data/derived/04-zones.json`, `04-zones.gpkg` | the 9 sized zones |
| `data/derived/05-routes.json`, `05-routes.gpkg` | 21 solved days, every manoeuvre |
| `reports/05-routes/day-NN.gpx` / `.md` | one GPX track and one turn sheet per day |
| `reports/07-playback/index.html` | animated playback, 21 days — double-click it; opened from disk it hands off to the self-contained build |
| `reports/07-playback/playback-standalone.html` | the same playback with all 21 days inlined, 11.1 MB — no server, no network |
