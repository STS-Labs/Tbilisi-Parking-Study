# Run 2 — the customer's own network as the required set

> **Zone A was requested and is not in the data.** `data/custom/B Zone_Streets/AB_zones.shp` holds one polygon, `Name = "Zone B"`, despite the layer being called `AB_zones`; its `FolderPath` names `Tbilisi Possible parking zones.kmz` as the source, so Zone A presumably exists there and was never exported. **This run covers Zone B only.** Nothing in it is an A+B result, and no Zone A boundary has been inferred or approximated.


> **The customer's layer says WHAT to cover. OSM says HOW to drive it.**

`data/custom/B Zone_Streets/Streets.shp` — 3,368 polyline parts, 347.0 km, no name,
no class, no `oneway`, no `lanes`, no `width` — defines what has to be filmed. OSM
supplies the graph, the attributes, the turn restrictions and every metre of legal
deadhead. The two are joined by geometry, because the customer layer has nothing else
to join on.

Reproduce with `sh tools/run-customer-net.sh`; gates with
`sh tools/with-run-env.sh customer-net uv run pytest -q`.

## Headline

> ## 13 driving days, 2026-08-29 → 2026-09-10
>
> **71.4 h** of driving — 16.6 h capture, 29.0 h deadhead,
> 25.9 h turns — to cover **445.5 km** of required
> traversal. No day exceeds its window.
>
> **343.2 km of the customer's 347.0 km is filmed — 98.90%.**
> The remaining 3.8 km is street the drivable network cannot reach.

| | |
| --- | ---: |
| Customer layer supplied | 347.0 km |
| **Filmed by this plan** | **343.2 km (98.90%)** |
| Required traversal | 445.5 km |
| Required centreline | 393.1 km |
| Required share of the drivable clip | 24.9% |
| Driving days | 13 |
| Total driving | 71.4 h |
|   capture / deadhead / turns | 16.6 / 29.0 / 25.9 h |
|   depot legs | 3.3 h (4.6%) |
| Deadhead as % of capture | **174%** |
| Days over window | 0 |
| Stage 3 bracket | 40.6 – 63.0 h |
| Zones sized by Stage 4 | 5 |
| Zone splits forced by Stage 5 | 8 |

**Why 445.5 km of traversal for a 347.0 km layer.** The customer's linework maps onto
**393.1 km** of OSM centreline: where two carriageways of a divided road lie under one
customer line, both are required, because filming one does not film the other. SPEC
§1.1 resolves that toward coverage. The remaining step to 445.5 km is the passes
model — 1.13 passes per centreline metre, from wide streets needing one pass per
direction.

## 1. Noding the layer — how much of its topology is real

3,368 parts is not a graph. Measured before anything was moved:

| Endpoints | Count | What it means |
| --- | ---: | --- |
| Already share a vertex with another street | 5,396 | properly digitised junctions |
| **Lying on another street's interior** | **833** | visually a T-junction, topologically nothing — noded |
| Closed by snapping (≤ 2 m) | 13 | drafting slips |
| **Attached to nothing within 2 m** | **494** | dead ends, real or false |
| Total | 6,736 | over 3,400 distinct locations |

**The 833 are the ones that mattered.** Each was an endpoint touching another street
without a shared vertex — a junction to the eye, a dead end to a solver. Left alone
every one of them costs a U-turn and a doubled-back street. `unary_union` splits the
linework at each; 3,368 parts became **4,577 noded pieces** and total length was
preserved to 0.5 metres in 347 km.

Snapping is deliberately small at 2 m. Only 13 endpoints fall in the band, so the
layer's near-misses are rare; anything larger would start welding a street to its
neighbour across a kerb.

The 494 unattached endpoints are mostly genuine — cul-de-sacs, and streets that stop
where the customer clipped their extract at the zone edge. Those latter are not false
dead ends in the plan, because the required arc is carried by the OSM street, which
continues.

## 2. Matching to OSM — and the basis that decides the answer

An OSM arc is required when at least **50%** of its length lies within **15 m** of the
customer's linework; a customer piece counts as carried when the same test passes the
other way.

**Match against *drivable* arcs, and this is not a detail.** The question is whether
the routing network can carry a street, and an arc the filter excluded — a footway, a
track, a gated road — cannot carry anything. Measured five ways, all true:

| Compared against | Covered | Uncovered |
| --- | ---: | ---: |
| Variant C's network inside Zone B | 340.2 km (98.03%) | 6.8 km |
| The same, service included | 341.7 km (98.48%) | 5.3 km |
| Every drivable arc in the clip, no service | 340.9 km (98.23%) | 6.1 km |
| **Every drivable arc in the clip** — the basis used here | **342.3 km (98.65%)** | **4.7 km** |
| Every arc in the table, undrivable included | 347.0 km (100.00%) | 0.0 km |

Matched against the whole arc table the layer is 100% "in OSM", which would have
counted 4.7 km of gated and unbuilt road as covered and silently dropped it from the
plan. That is the failure this choice avoids.

**Result: 4,497 of 4,577 noded pieces matched, 342.3 km of 347.0 km by length.**

## 3. The 80 pieces the network could not carry — and what OSM actually says

The brief expected 127 parts and 10.3 km "OSM does not have", clustered around
44.795–44.800 E / 41.695–41.701 N, and suggested adding them to OSM. **That is not
what they are.**

| OSM says | streets | What that means |
| --- | ---: | --- |
| `highway=construction` | 51 | OSM knows the street; it is being built |
| `access=private` | 11 | OSM knows the street; there is a gate |
| `barrier` blocks the way | 6 | OSM knows the street; there is a bollard |
| `footway` / `steps` | 11 | the customer digitised something that is not a road |
| `access=no` | 1 | OSM knows the street; entry is signed off |

Every one has an OSM way underneath it. **The cluster the brief predicted is exactly
where it said it would be — and it is tagged `construction`.** OSM has caught up with
that development; it is telling us the roads are not finished. Adding them to OSM
would achieve nothing. *Retagging* the ones since built is the smaller, precise job,
and is what `surveys/unverified-streets.md` sends the driver to establish.

**The layer is an OSM derivative.** 99.2% of its vertices sit under a **millimetre**
from an OSM node; the median distance is 46 micrometres. That explains the 98.65%
agreement, and it means a reconciliation between the two is not the independent check
it appears to be.

## 4. Stitching them in

All 80 unmatched pieces (5.40 km) were injected as synthetic two-way `residential`
ways so Stage 0 splits, orients and prices them like any other street.

| | |
| --- | ---: |
| Pieces injected | 80 (5.40 km) |
| Distinct endpoints | 110 |
| **Endpoints landing on an existing OSM node** | **110 (100%)** |
| Largest snap distance | **0.00 m** |
| Endpoints that could not be connected | 0 |
| Synthetic interior nodes created | 218 |

The zero-metre snap is not a bug: it follows from §3. The layer is an OSM derivative,
so its vertices *are* OSM node coordinates and every endpoint adopted an existing node
id exactly, without moving.

**Nothing was invented.** Every injected coordinate is a vertex the customer
digitised, and no connector geometry was synthesised — the endpoints adopt existing
node ids rather than being joined by a new segment. Every injection is logged in
`00-dropped-ways.csv` under `injected_customer_street`, because CLAUDE.md rule 4
applies to what enters the network as much as to what leaves it.

**22 of the 80 (1.07 km) still cannot be reached, and that is the network's fault,
not the stitching's:**

| | ways | Why |
| --- | ---: | --- |
| Reachable and driven | 58 (4.34 km) | attached to the main network |
| Touch no drivable OSM node at all | 18 | their endpoints belong only to ways the filter excluded — footways, construction |
| Touch a drivable node, but of an isolated component | 4 | the OSM streets they join are themselves stranded |
| Touch the largest component and are still stranded | **0** | — |

A street whose only connection is to a building site connects to nothing a car can
use. No injected piece failed because a snap failed.

## 5. Coverage

| | |
| --- | ---: |
| Required traversal | 445.5 km |
| Not covered | 5.5 km (1.23%) |
|   unreachable by any legal tour | 5.4 km |
|   of which injected customer geometry | 1.07 km |
|   **reachable and simply missed** | **0.073 km** |
| **Of the customer's 347.0 km, filmed** | **343.2 km (98.90%)** |

The 73 m is the same three arcs — 2.6 m, 12.0 m and 19.2 m — that every campaign in
this repository misses, unchanged by scope.

Where the requirement verdict is arguable: **97.9 km of arc length has coverage
between 25% and 75%**, so a 50% threshold decides it. Almost all of that is streets
crossing the zone edge, where the customer clipped their extract and OSM did not. It
is the required-network analogue of the 218.7 km the polygon rule reported near the
zone boundary, and the same kind of number: not a defect, but where a dispute lands.

## 6. Unverified attributes reach the driver

The 80 injected streets have **no** OSM attributes. They are modelled as two-way
`residential` at the 30 km/h default free-flow, no lane count, no width, no turn
restrictions — the brief's instruction and also the §1.1 choice, since a driver who
finds a one-way sign loses nothing by having planned to drive it both ways.

Every one is flagged `attributes_unverified` in the arc table and **the flag follows
the arc into the turn sheets**:

- 9 of the 13 day sheets carry a warning block naming how many arcs on that route
  are unverified;
- each affected instruction row reads `(unnamed) **[UNVERIFIED]**`;
- a run of steps never folds an unverified street into a verified one's instruction,
  so the flag cannot be hidden by the fold.

`surveys/unverified-streets.md` lists all 80 with location, length, way id and what
OSM says about each. A warning that stops at a JSON artifact never reaches the
windscreen.

## 7. Why this run costs what it does

**71.4 h against variant C's 35.5 h for a nearly identical set of streets.** The cause
is in one number: the required set is **24.9%** of the drivable network the car has to
cross, against variant C's 37.3%. The customer's layer is a *list of streets*, not a
*region*, and between any two of them the car drives roads nobody is paying it to
film — for 29.0 of its 71.4 hours, a deadhead ratio of 174% against variant C's 102%.

Full economics, and the recommendation on which run to quote, in
`reports/RUNS-COMPARISON.md`.

## 8. Constants transferred rather than measured

| Constant | Value used | Where it came from | What Run 2 says |
| --- | --- | --- | --- |
| `ZONE_OVERHEAD_MEASURED` | 2.2598 | Tbilisi p75, 49 solved days | Run 2 measures **4.4927** — **98.8% higher**, the worst transfer of any campaign |
| `TURN_PENALTY_S` | left 8 s / right 3 s / u-turn 20 s | SPEC §3.3 estimate | still **[CONFIRM]**; 36% of driving here |
| Speed model coefficients | as fitted for Tbilisi | Stage 2 free-flow + gradient | unchanged; no Zone B traces exist |
| Congestion multipliers | by class × time band | Tbilisi assumption | unchanged |
| `CAPTURE_SPEED_MAX_KMH` | 40 | SPEC §5, confirmed | policy, not a measurement |
| Residential default free-flow, 30 km/h | `BASE_FREE_FLOW_KMH` | Stage 2 | applied to 80 streets with **no evidence at all** — see §6 |

Stage 4 sized 5 zones expecting 42.4 h over 5 days; Stage 5 drove 71.4 h over 13,
because a zone sized on 2.26 and driven at 4.49 overruns by 99%. The constant is
**pinned, not fed back** (CLAUDE.md), and has not been re-derived mid-run.

## 9. Decisions made in this run

| Decision | Choice | Why |
| --- | --- | --- |
| Zone A is absent from `AB_zones.shp` | Ran Zone B alone; caveat stamped on every report from config | The brief forbids inferring or approximating a Zone A boundary. Written from config so it regenerates rather than being pasted on. |
| Required set defined by geometry, not by copying attributes | A customer street OSM also has is **carried by the OSM arc** | The arc keeps its own class, `oneway`, lanes, width, surface, maxspeed, name and turn restrictions. That is §3.2's attribute transfer done by identity — one matcher, not two — and it is the only way `oneway` and the restrictions can be right. |
| Match basis | Drivable arcs only | Against the whole arc table the layer is 100% matched, which would have dropped 4.7 km of gated and unbuilt street from the plan without a word. See §2. |
| Required rule | ≥ 50% of the arc's length covered | A zone polygon cuts an arc once, so the midpoint settles it. A street layer is not a cut: the whole arc is evidence. 97.9 km sits in the arguable band and is reported (§5). |
| Scope variant | **A**, not C | The variant filter deletes arcs from the network. Running C would let a scope decision made for a different campaign remove a street the customer explicitly asked for. Under A the filter drops nothing; the service roads it leaves in are routable-only and never required. |
| Injected streets' attributes | Two-way `residential`, default speed, flagged | The brief's instruction and the §1.1 choice. There is no data anywhere that can settle their signage in software, so the flag and the survey exist instead. |
| Injected geometry and CLAUDE.md rule 1 | Accepted, logged, and no shape invented | Rule 1 bars interpolating, smoothing or synthesising geometry; every injected coordinate is a customer-digitised vertex, endpoints adopt existing node ids rather than being joined by new connectors, and each injection carries a machine-readable reason. |
| Coverage threshold sensitivity | Reported, not tuned | 0.25 → 35 pieces / 1.6 km; **0.50 → 80 / 5.4 km**; 0.75 → 102 / 7.0 km; 0.99 → 124 / 8.4 km. Recorded in `00-custnet.json` so the choice is visible rather than fitted. |
| gate2's variant-D reconciliation failed by 9.3 km | Fixed the gate to use the **stored** service roles | `summarise` re-derived `service_role` from whatever subset it was handed. `service_role` is a property of the whole network — a service road is `through` because it links two streets — so re-classifying a scattered required set reclassifies 1,322 `through` arcs as spurs. `variant_mask` reads the stored column, so the reconciliation must too. Stronger, not looser: D must drop exactly what the column D consults says it should. |

## 10. Gates

`sh tools/with-run-env.sh customer-net uv run pytest -q` — **933 passed, 31 skipped,
0 failed.**

All four campaigns in this checkout pass with this code in place — Tbilisi 964,
Zone B 933, Run 1 933, Run 2 933 — via `sh tools/verify-all.sh`.

**One gate remains UNMET rather than passed**, as in every custom campaign: twenty
junctions must be checked against imagery by a person. Nothing substitutes for it and
nothing was invented in its place. **For this run there is a second outstanding human
task**: the 80 unverified streets in `surveys/unverified-streets.md`.

## Artifacts

| Path | What it is |
| --- | --- |
| `data/derived/00-custnet.json` | noding census, match basis, stitching report, threshold sensitivity |
| `data/derived/00-custnet-network.geojson` | the noded customer network — the required set |
| `data/derived/00-custnet-injected.geojson` | the 80 injected streets, with what OSM says about each |
| `data/derived/00-extract-custnet.pkl.gz` | OSM extract plus the injected ways |
| `data/derived/00-network-stats.json` | Stage 0, including the required/routable split |
| `data/derived/05-routes.json`, `05-routes.gpkg` | 13 solved days, every manoeuvre |
| `reports/05-routes/day-NN.md` | turn sheets, with `[UNVERIFIED]` flags |
| `surveys/unverified-streets.md` | the driver's work order |
| `reports/07-playback/index.html` | animated playback, 13 days — double-click it; opened from disk it hands off to the self-contained build |
| `reports/07-playback/playback-standalone.html` | the same playback with all 13 days inlined, 9.6 MB — no server, no network |
