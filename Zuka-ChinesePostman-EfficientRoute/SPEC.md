# EfficientRoute — Specification

Camera-car coverage planner for the Tbilisi street network.
Status: draft **v0.4** — 25 Aug 2026. Items marked **[CONFIRM]** are still open.

---

## 1. Objective

Minimise total driving time for a **single** camera-equipped car to capture the
complete drivable street network of Tbilisi, subject to daily shift limits from a
fixed base, producing day-by-day routes and re-planning against actual coverage.

Success = every required street element captured at usable quality, in the fewest
driving hours, with a plan the driver can follow and that repairs itself when
reality diverges.

### 1.1 Governing principle — accuracy first

**Capture accuracy is a hard constraint. Efficiency is the objective function
*subject to* it.** Driving time is minimised only within the set of plans that
achieve complete, usable coverage.

Operationally this settles every ambiguous case in the same direction:

- Where lane count, width or class is untagged or ambiguous, the arc defaults to
  the **more demanding** requirement.
- Where a cheaper route risks a marginal capture (wrong side, occluded, too fast),
  the more expensive route wins.
- Deadhead loops incurred by repeat passes are **accepted, not traded away**.

---

## 2. Capture model

**Rig:** Stereolabs stereo cameras — one forward-facing, one rear-facing.
A single pass yields both an *approaching* and a *receding* oblique view of
everything within usable depth range on both sides of the vehicle.

**Capture speed limit:** 40 km/h. Footage above this is not usable.

### 2.1 The passes model

Coverage is expressed as a **required number of traversals per directed arc**,
not as a coverage "class". This single mechanism covers every case:

| Situation | Model |
|---|---|
| One-way street, ≤ 3 lanes | arc `min_passes = 1` |
| **One-way street, > 3 lanes** | arc **`min_passes = 2`** — same direction, different lane group |
| Two-way narrow street | the arc **pair** carries a shared requirement of 1 — either direction satisfies it |
| Two-way wide undivided street | each arc `min_passes = 1` (2 traversals, opposite directions) |
| Divided carriageway | each direction is already a separate one-way way; each is rated on its own lane count |

**[CONFIRM]** Does a 6-lane one-way need `min_passes = 3`? The model supports any
integer; only the threshold table needs deciding.

**Lane thresholds — resolved by §1.1.** `lanes > 3` is the trigger where the tag
exists. Where `lanes` is **absent**, fall back in order to `width`, then to
carriageway class; if all three are inconclusive, the arc is assigned
`min_passes = 2`. Stage 0 must report how many arcs reach that fallback — if the
count is large, the threshold gets calibrated against imagery before Stage 4.

**RESOLVED 25 Aug 2026 — `highway=service` is OUT of scope (variant C).**

This is the one decision in the project where **schedule overrode §1.1**, and the
record should stay legible. Accuracy-first defaults to include. Stage 3 measured
deadhead at 65.1% of capture, which put variant A at 79 days and variant D at 55 —
neither reachable before the 1 November daylight limit with one vehicle, given that
Stages 4 and 5 were not yet built. Variant C fits at 33.8 days.

What it costs: **1,150 km of through-connected service roads** — segments whose
service-only component attaches to the street network at two or more points, i.e.
roads that carry traffic between streets and function as streets. These are not
driveways. They are being dropped for time, not because they are out of scope.

**This is reversible, and the architecture already supports it.** See §2.1.1.

### 2.1.1 Phase 2 — the deferred service network

The system is a re-planner (SPEC §10), so the dropped service roads are a *deferred
requirement*, not a discarded one. `service_role` remains a column; re-including
`through` service and re-running Stages 4–5 against the already-covered set is a
configuration change, not a rebuild.

Sizing, honestly: going from C to D is **174.1 h** of additional required work by
Stage 3's figures — but run as a **separate later campaign it will cost more than
that**, because what remains is scattered across the city rather than woven into a
contiguous tour. Budget ~25–30 days rather than the ~22 the raw hours imply.
Splitting a coverage campaign in two always costs more than running it once.

That penalty is the real price of this decision, and it is worth paying only if
phase 2 actually happens. Schedule it, or the 1,150 km is simply lost.

---

### 2.2 Two same-direction passes are structurally expensive

This is the most important cost consequence in the spec.

- On a **two-way** street, two passes are cheap: in and out are naturally balanced,
  and the return traversal is itself a required element.
- On a **one-way** street, two passes cannot be achieved by reversing. The car
  must drive the arc, loop back around to its start, and drive it again. The
  return loop is **pure deadhead** unless it happens to run along other required
  arcs.

Practical mitigation, to be exploited by the solver: where a wide one-way belongs
to a **one-way couplet** (a parallel street carrying the opposite flow), the return
leg is itself required, and the extra pass becomes nearly free. Tbilisi's central
grid has many such couplets. The solver must therefore treat repeat passes as
ordinary arc requirements inside the global optimisation — **never** as a local
"drive it twice now" instruction — so that return legs get reused as coverage.

> Cost of a wide one-way pair of passes ranges from ≈ 2× its length (couplet
> available) to ≈ 3× (isolated). The `lanes > 3` threshold therefore has outsized
> cost impact and is worth calibrating against real streets, not just tags.

### 2.3 Lane instruction

Where `min_passes ≥ 2` on a single arc, the driver output must state **which lane
group** each pass uses (e.g. "pass 1 — right lanes; pass 2 — left lanes").
Without this the driver repeats the same lane and the second pass is wasted.

---

## 3. Graph model

### 3.1 Base network

- **Source:** Geofabrik `georgia-latest.osm.pbf`, clipped to the Tbilisi
  municipality boundary plus a configurable buffer.
- **Included and REQUIRED:** `highway` in {motorway, trunk, primary, secondary,
  tertiary, unclassified, residential, living_street} **plus all `*_link` ramps
  and slip roads** (+ service, pending CONFIRM).
- Motorway- and trunk-class roads are **coverage targets, not merely deadhead
  corridors**. Every interchange ramp is a required arc in its own right.
- **Excluded:** pedestrian, footway, steps, path, track, construction, and
  anything failing the drivability filter (`access=private`, locked barriers,
  impassable `surface`, `incline` above a limit).
- Every way becomes one or two **directed arcs**.

Arc attributes: `geometry`, `length_m`, `highway_class`, `lanes`, `width`,
`surface`, `incline` (from DEM where untagged), `maxspeed`, `min_passes`,
`pair_requirement`, `zone_id`.

**Connectivity:** take the largest strongly connected component. Everything
dropped must be reported, not silently discarded — orphan fragments in the
hillside districts are a data-quality signal, not noise.

### 3.2 Motorway capture — resolved: reduced-quality pass

Motorway and trunk mainlines are captured **at prevailing traffic speed**, with
stereo quality accepted as degraded. Consequences:

- Arcs of class {motorway, trunk} and their `*_link` ramps carry
  `capture_quality = "reduced"` and are **exempt from `capture_speed_max`**.
  Everything else remains hard-capped at 40 km/h.
- The flag propagates to every output, so downstream processing knows which
  geometry came from a degraded pass. It is a data attribute, not a footnote.
- Wide motorway mainlines (`lanes > 3`) still take `min_passes = 2` per §1.1.
  The loop cost is high in *distance* but low in *time*, and time is the KPI —
  so this is cheap accuracy. **[CONFIRM]** if you would rather not.
- No safety conflict remains, so this is no longer blocking on Stage 4.

### 3.3 Turn expansion — L(G)

Turn restrictions are modelled from the start, not post-validated.

- **Node of L** = one directed arc of the base network.
- **Edge of L** = one legal manoeuvre from arc `a` to arc `b`, where
  `head(a) == tail(b)`.
- Manoeuvres removed using OSM `type=restriction` relations (`no_left_turn`,
  `no_u_turn`, `only_straight_on`, …), including via-way restrictions.
- **Edge cost** `(a→b)` = traversal time of `b` + turn penalty by turn class
  (straight ≈ 0 s, right ≈ 3 s, left ≈ 8 s, u-turn ≈ 20 s) **[CONFIRM values]**.
- **U-turn edges** `(a → reverse(a))` exist **only** where physically possible:
  at dead-end tips, and at junctions where carriageway width permits and no
  `no_u_turn` restriction applies. Elsewhere they are *absent*, not merely
  penalised. **[CONFIRM]** minimum width for a mid-street U-turn.
- Motorway and trunk nodes carry **no** U-turn edges and are enterable only via
  ramp arcs.

> **Invariant U1:** any path through L is a legally and physically drivable
> manoeuvre sequence in the base network.

### 3.4 Coverage requirement, expressed in L

- Arc `a` with `min_passes = k` → node `a` must be visited ≥ `k` times.
- Two-way narrow pair → **at least one of** `{a, reverse(a)}` visited ≥ 1.

The second line is the source of the difficulty: "at least one of a pair" is a
*generalised* coverage requirement, and it is what moves this out of the
polynomial-time class.

---

## 4. Problem class and solver architecture

**Formally:** a Generalised Directed Rural Postman Problem with arc multiplicities,
on a turn-expanded graph, with vehicle capacity (shift time) and a fixed depot —
i.e. a capacitated arc routing problem with turn constraints. **NP-hard.**

No exact global solution exists at city scale, so: *bound first, cluster second,
solve exactly third.*

**Stage A — Bracket the optimum (corrected, v0.4).**
Two computations, in opposite directions. An earlier version of this spec called
the first one a lower bound. **That was wrong** — fixing an orientation *adds* a
constraint, so its result can only bound the optimum from above.

- **Upper bound (constructive).** Fix an orientation for every two-way narrow pair
  heuristically → purely directed graph with arc lower bounds `min_passes` →
  Directed Chinese Postman as a **min-cost flow with lower bounds** on the
  node-split graph `L*` → Euler circuit. Polynomial and exact *for that
  orientation*. Yields a real, legal, closed tour — a feasible solution, not just
  a number.
- **Lower bound (genuine).** LP relaxation of the generalised routing MIP, where
  each narrow pair carries a single "at least one of the two" constraint and
  traversal counts are relaxed to continuous. Fallback: capture time plus the
  minimum balancing flow with each pair free to take the cheaper direction.

Every later result is reported against **both**, as `gap = (upper − lower)/lower`.

**Stage B — Zoning.**
Partition required elements into connected, compact zones, each ≈ one shift of
capture time *net of depot legs*. Balanced graph partitioning (METIS/KaHIP)
weighted by capture time — **not** geometric clustering, because the Mtkvari and
the ridgelines mean two points 500 m apart can be 6 km of driving.

**Stage C — Per-zone exact solve.**
Zones hold ~1,000–3,000 required elements, within reach of a MIP formulation of
the generalised rural postman. HiGHS (free) or Gurobi, time-limited,
warm-started from Stage D.

**Stage D — Heuristic fallback.**
Frederickson-style construction plus local search (2-opt on deadhead segments,
orientation flips on narrow pairs, repeat-pass placement). Guarantees feasibility
always exists and seeds the MIP.

**Stage E — Day assembly.**
`depot → zone entry → zone tour → zone exit → depot`, validated against shift time.

### KPI warning

The hybrid coverage rule *raises* the deadhead ratio while *halving* total driving.
**Deadhead ratio is a misleading KPI here. Total driving hours is the KPI.**

---

## 5. Operating parameters

| Parameter | Value | Status |
|---|---|---|
| `capture_speed_max` | 40 km/h | confirmed |
| Shift window | 09:00 – 18:00 (9 h gross) | confirmed |
| Depot | 41.730736 N, 44.734583 E | confirmed |
| Break allowance | 45 min, inside the shift | confirmed |
| Working days | 7 per week | confirmed |
| Daylight | Non-binding until ~1 Nov, see §7.3 | derived |

Depot legs are consumed **inside** the 9-hour window. Productive capture time per
day is therefore `9 h − breaks − outbound leg − return leg`.

---

## 6. Time and cost model

- Free-flow speed by `highway_class`, overridden by `maxspeed` where tagged.
- Hard-capped at `capture_speed_max` on every **required** traversal.
  Deadhead segments are uncapped.
- Congestion multiplier by class × time-of-day band.
- Gradient penalty from DEM — a 12% Tbilisi lane is 12 km/h, not 40.
- Turn penalties per §3.3.
- Idle/stop allowance.

---

## 7. Operational findings

### 7.1 The depot sits on the western edge

41.7307 N, 44.7346 E is roughly 8 km west-southwest of the centre, in the western
hills. Tbilisi's mass extends well to the east and north. Straight-line distance
from depot to the eastern districts (Varketili, Lilo) is ≈ 22 km — call it 27–30 km
of driving, 50–60 min each way in traffic.

> **CORRECTED 25 Aug 2026 by Stage 4 measurement.** The claim below was wrong.
> Routed over L(G), the *entire* variant-C campaign spends **17.1 h** on depot legs
> — an average round trip of **32 minutes**, not two hours. The original figure
> extrapolated the eastern worked example across the whole city; most zones are
> nowhere near the east. Stage 2's straight-line bands (20.5 h) were 20% pessimistic;
> the flat 1.2 h/day allowance used in `DECISION-schedule.md` was ~2.2x too
> pessimistic, and that error materially shaped the variant-C decision.

#### Original claim (retained for provenance)

**Consequence:** eastern days lose up to ~2 h of a 9-hour shift to commuting, a
~22% productivity loss on exactly the days that are already longest.

The base is **fixed**. Three solver-side mitigations, in order of value:

1. **Capture on the commute.** A depot leg is only deadhead if the corridor it
   runs along is already covered. The solver must route depot legs *through
   uncovered required arcs* wherever the detour cost is below the coverage value
   gained. **Measured: 3.5 h reclaimed, not "most of two hours"** — and Stage 4
   found the binding constraint is not the detour but the day budget: a zone sized
   to fill its shift has no room for a longer leg. Reserving that room reclaims ~3x
   as much and cuts 9.3 h of total driving, at the cost of one extra day.
2. ~~**Far zones early — a hard scheduling rule.**~~ **SUPERSEDED by Stage 8
   (28 Aug 2026) — do not reinstate as a rule.**

   The original reasoning: early in the campaign the connecting corridors are still
   uncovered, so long legs absorb productive work; late on they become pure
   deadhead, so distant zones should be sequenced first.

   That reasoning was a **crude approximation of coverage crediting**. It tried to
   capture value from cross-day passes by ordering the days, because the planner
   could not credit those passes directly. Stage 8's credit rule captures that value
   properly and on every pass, not just depot legs — so the approximation is now
   redundant, and on Zone B it is actively worse: largest-zone-first beat
   far-zones-first outright (5 days vs 6).

   **The replacement is not another rule.** Baking in largest-zone-first would
   repeat the same mistake with a different heuristic. Zone order is now a **search**
   (Stage 8 tier 2), seeded with both heuristics and free to pick per campaign.
   Tbilisi's western depot and distant eastern zones may still favour far-first;
   that is for the search to determine, not for this document to assert.
3. **Zone sizing on net productive time.** Eastern zones carry less capture work
   so the day still closes on schedule. Prevents overruns rather than saving time.

### 7.2 The shift window straddles both rush hours

A 09:00 start puts the outbound leg inside the morning peak; an 18:00 finish puts
the return inside the evening peak. Since both legs are unproductive deadhead
anyway, this is the *right* time to be commuting — but it argues for scheduling
the most distant zones on days when an earlier start is possible.

### 7.3 Daylight IS binding — condition met 25 Aug 2026

> **Superseded by evidence.** Stage 3 measured deadhead at 65.1% of capture for
> variant A, against the 14.1% this section's original analysis could tolerate.
> Variant A cannot finish before 1 November with one car at any shift length, and
> variant D must start driving by 6 September to do so. The revisit condition below
> has fired. See `DECISION-schedule.md` — a scope, vehicle-count or calendar
> decision is required before Stage 4 can run.

#### Original analysis (retained for provenance)


Tbilisi sunset runs ~19:48 in late August (corrected from ~20:05 by Stage 4's
solar model; day length 13h27m is right for 41.7 N), and drops below 18:00 on
**30 October**. At 7 days a week a
25–40 day campaign starting now finishes well inside that window, so the
09:00–18:00 shift is not daylight-constrained.

Two caveats the scheduler must carry: if the campaign slips past mid-October the
final hour degrades before it disappears, and low winter sun produces long shadows
and glare. If Stage 2's estimate pushes the finish past October, revisit the
shift window rather than accepting degraded final hours.

---

## 7A. Accepted risks

### R1 — The narrow-pair assumption is unmeasured (accepted 25 Aug 2026)

4,095.4 km of streets carry a **shared pair requirement** — one pass covers both
sides — assigned on **class evidence alone** (`CLASS_IS_NARROW_PAIR` =
living_street, residential, service, unclassified). `width` is tagged on 1.6% of
arcs, so for the overwhelming majority nothing was measured.

This is the one place the model is permissive rather than conservative, and it is
the place that moves the headline number most: were these streets to require both
directions, required traversal would rise by ~4,527 km.

A calibration drive (sample ~25 streets across the width distribution, review
footage, find the width at which one pass stops covering both sides) was
**considered and deferred**. The risk is therefore **accepted, not mitigated**:
if the assumption fails for a share of these streets, it will surface at footage
review, after the driving.

Revisit before Stage 4 zoning if any early footage shows incomplete coverage on a
residential or service street.

---

## 8. Invariants — asserted by tests at every stage

1. **I1** Every arc is traversed ≥ its `min_passes`; every narrow pair ≥ 1.
2. **I2** Every consecutive arc pair in every route is a legal edge of L.
3. **I3** Every day's route starts and ends at the depot.
4. **I4** No day exceeds the shift window, depot legs and breaks included.
5. **I5** Total driving lies **within the Stage A bracket**: ≥ the LP lower bound
   and ≤ the constructive upper bound. Both ratios are reported. (Corrected in
   v0.4 — the earlier form asserted the bound in the wrong direction.)
6. **I6** Every arc in the plan exists in the base network — no invented geometry.
7. **I7** No **required** traversal is scheduled above `capture_speed_max`,
   except arcs flagged `capture_quality = "reduced"` (motorway/trunk per §3.2).
8. **I8** Every arc with `min_passes ≥ 2` carries a distinct lane instruction per pass.

---

## 9. Metrics

- `required_km`, `driven_km`, `deadhead_ratio = (driven − required) / required`
- `total_hours`, `days`, `avg_productive_hours`, `depot_leg_hours`
- `day_balance` (stdev of day durations)
- `optimality_gap` vs. the Stage A lower bound
- `coverage_pct` — live, from map-matched traces

---

## 10. Feedback loop

1. Ingest the day's GPS trace.
2. Map-match onto the base network (Valhalla Meili or `fmm`).
3. Mark a traversal valid where matched heading agrees within ±T° **and**
   speed ≤ `capture_speed_max`. A wrong-direction or too-fast pass does not count.
4. Decrement `min_passes` on the matched arcs; recompute the remaining set.
5. Re-run Stages B–E on the remainder.

Day 1 is simply the case where the remaining set is everything. This is a
**re-planner that happens to run once at the start** — not a planner with
re-planning bolted on.

---

## 11. Stage plan

| # | Stage | Output artifact | Gate |
|---|---|---|---|
| 0 | Extract & measure | Network stats, exclusion report, passes breakdown, map | Is the scope real? |
| 1 | Turn-expanded graph | L(G) + restriction / U-turn audit | Invariant U1 holds |
| 2 | Time model | Per-arc capture time; campaign length estimate | Estimate accepted |
| 3 | Lower bound | DCPP-with-lower-bounds result | Benchmark fixed |
| 4 | Zoning | Zone map, balance report, depot-leg costs | Zones compact + balanced |
| 5 | Route solve | Per-day routes + lane instructions, GPX | Invariants I1–I8 pass |
| 6 | Coverage tracker | Map-matcher + remaining-set recompute | Replays day 1 correctly |
| 7 | Dashboard | Interactive map, progress, stats | — |

Each stage is independently verifiable and gated. No stage optimises on top of an
unconfirmed assumption from the stage before.
