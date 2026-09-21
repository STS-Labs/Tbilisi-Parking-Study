# Stage 2 — Time & capture model

Read `SPEC.md` §5, §6, §7 and `CLAUDE.md`. Stages 0, 1 and 0b gates must have passed.

## Purpose

Convert kilometres into **hours**. Every campaign estimate so far rests on assumed
speeds; this stage replaces them with a model, and — just as important — builds
that model so Stage 6 can refit it from real GPS traces.

---

## Item 0 — add `service_role` (carry the service decision forward, don't settle it)

Stage 0b showed 92.2% of `highway=service` carries no `service=*` subtag, so the
tag cannot decide the scope question. **Connectivity can.** Classify every service
segment by how its service-only component attaches to the non-service network:

| `service_role` | Rule | Meaning |
|---|---|---|
| `through` | component touches ≥ 2 distinct non-service nodes | carries traffic between streets — functionally a street |
| `spur` | component touches exactly 1 | dead-end tree: driveway, yard, parking aisle |
| `orphan` | touches 0 | unreachable from the street network |

Reference measurement to reconcile against (union-find over service arcs, counting
pair representatives only):

| | All service | Untagged service |
|---|---:|---:|
| `through` | 1,237.2 km | 1,150.4 km (56.8%) |
| `spur` | 888.6 km | 810.7 km (40.1%) |
| `orphan` | 67.5 km | 63.1 km (3.1%) |
| total | 2,193.3 km | 2,024.1 km |

Add `service_role` as a column. **Change no default and exclude nothing** —
variant A remains what the pipeline builds. This carries the decision to Stage 4,
which is the first stage that actually consumes an include set.

---

## Item 1 — the speed model

Per-arc `capture_speed_kmh` and `capture_time_s`, built in this order:

1. **Base free-flow by `highway_class`.** Document every constant in `config`.
2. **Override with `maxspeed`** where tagged (9.5% of arcs).
3. **Gradient penalty** from `gradient_pct`. Heed Stage 0 §10: a 30 m DEM samples
   terrain, not road deck. Cap the penalty, and treat `structure` in
   {bridge, tunnel} as flat. Median |gradient| is 3.4% and p90 is 10.5%, so this
   term is material across the whole city, not just the hillsides.
4. **Surface and width penalty** for unpaved and narrow arcs.
5. **Hard cap at `capture_speed_max` = 40 km/h** on every required traversal,
   **except** arcs with `capture_quality = "reduced"` (SPEC §3.2), which run at
   their free-flow speed.
6. **Turn time** from `config.TURN_PENALTY_S`, already isolated by Stage 1.

## Item 2 — congestion, and being honest about it

There is no traffic data for Tbilisi in this pipeline. So:

- Implement congestion as a multiplier by `highway_class` × time-of-day band, with
  every constant declared in `config` and **labelled an assumption in the report**.
- **This is the weakest link in the whole model.** Do not hide it behind a
  plausible number. Instead, produce a **sensitivity table**: campaign length at
  −25%, baseline, +25%, +50% congestion. If the campaign estimate is not robust to
  that range, say so plainly — it is a scheduling risk, not a modelling detail.
- Structure the model so its coefficients are **fittable**: Stage 6 will map-match
  real traces and refit. Write the interface for that now; a hard-coded speed table
  cannot be calibrated later.

## Item 3 — day capacity and campaign estimate

`productive_hours = 9.0 − 0.75 break − outbound leg − return leg`

Depot legs are real: the depot at 41.730736 N, 44.734583 E is ~8 km WSW of centre
and the city runs east (SPEC §7.1). Estimate legs by straight-line distance bands
from the depot for now; Stage 4 replaces the estimate with routed times.

Produce the campaign estimate **for three scope variants**, so the Stage 4 decision
is made in hours rather than kilometres:

| Variant | Service roads included |
|---|---|
| A | all (as built) |
| D | `through` only — drop `spur` and `orphan` |
| C | none |

## Outputs

- `capture_speed_kmh`, `capture_time_s`, `service_role` added to `network.gpkg`
- `reports/02-time-model.md` — the model, every constant with its justification,
  the sensitivity table, and the A/D/C campaign estimate table
- `data/derived/02-time-model.json`

## Gate — tests must assert

- Every included arc has a non-null positive `capture_time_s`.
- No required traversal implies a speed above 40 km/h **except** where
  `capture_quality = "reduced"` (invariant I7).
- `service_role` reconciles to the reference table above within 1 km per bucket.
- Σ `capture_time_s` over required traversals equals the reported capture hours.
- The sensitivity table is present and spans at least −25% to +50%.
- Determinism holds; all 412 existing tests still pass.

## Non-goals

No routing. No zoning. No lower bound. Do not exclude service roads. Do not choose
a variant — Stage 4 does that, with these hours in hand.
