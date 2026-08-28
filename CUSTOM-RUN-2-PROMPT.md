# Two more runs — full-scope OSM, and the customer's own network

Two complete pipeline runs (Stages 0 → 7), autonomous, same pre-answered decisions
as `CUSTOM-RUN-PROMPT.md` except where stated. Do not stop to ask.

| Run | Output root | What it covers |
|---|---|---|
| **1 — OSM full scope** | `RUN-OSM-FULL/` | Everything OSM has in the zones, **service roads included** (variant A) |
| **2 — Customer network** | `RUN-CUSTOMER-NET/` | Exactly the streets in `Streets.shp`, no more, no less |

Both must leave the Tbilisi artifacts and `CUSTOM-OUTPUT/` untouched and
regenerating identically. Verify at the end.

---

## 0. BLOCKER — Zone A is not in the data

`data/custom/B Zone_Streets/AB_zones.shp` contains **one** polygon, `Name = "Zone B"`,
despite the layer being called `AB_zones`. Its `FolderPath` says it came from
`Tbilisi Possible parking zones.kmz`, so Zone A presumably exists in that KMZ but
was never exported.

- **If a Zone A polygon has appeared** in `data/custom/` by the time you run: use
  zones A ∪ B as the boundary for both runs.
- **If it has not:** run both against Zone B alone, and put a line at the **top** of
  every report saying Zone A was requested but absent, so no one mistakes a
  Zone B result for an A+B result.

Do not invent, infer or approximate a Zone A boundary under any circumstances.

---

## 1. The two runs answer different questions — keep them separate

Measured in Zone B:

| Definition of "everything" | Required traversal |
|---|---:|
| OSM, service included (variant A) | **674.4 km** |
| OSM, service excluded (variant C) | 390.9 km |
| The customer's `Streets.shp` | **347.0 km** |

The customer's layer is closest to variant **C** — whoever digitised it drew real
streets, not driveways and parking aisles. So "cover absolutely everything" and
"use the customer's network" are **not the same job**: they differ by roughly 2×.
That is precisely why both runs are worth having, and why the comparison report
(§4) is the actual deliverable.

---

## 2. Run 1 — OSM full scope

Only change from the previous run: **`SCOPE_VARIANT = "A"`**. Service roads in.

Everything else identical — 9 h shift, depot 41.730736/44.734583, p75 overhead,
far-zones-first, reserved commute profile, motorway narrowing, native HMM matcher,
2 km deadhead buffer, required = midpoint inside the zone.

Expect roughly **674 km required and 11–14 driving days** for Zone B alone (more
with Zone A). If you get something far outside that, diagnose before reporting.

Note in the report that variant A restores the dead-end service spurs, which are
**100% deadhead by construction** — expect the deadhead ratio to worsen relative to
the variant C run. That is topology, not a regression.

---

## 3. Run 2 — the customer's network as the required set

This is the new build. The principle:

> **The customer's layer says WHAT to cover. OSM says HOW to drive it.**

### 3.1 Build the required set from `Streets.shp`

- Reproject **EPSG:32638 → EPSG:4326**. The boundary layer is already 4326; these
  two are not in the same CRS and that is the most likely thing to go wrong.
- **Node the geometry.** It is 3,368 polyline parts, not a graph. Split at true
  intersections, snap endpoints within a small tolerance, and **report how many
  endpoints did not coincide with anything** — a customer layer digitised for
  display often has streets that visually touch but are not topologically joined.
  Every such gap is a false dead end that will wreck the routing.

### 3.2 Transfer attributes from OSM by spatial match

The customer layer has **no name, class, `oneway`, `lanes` or `width`** — only a
zeroed `Id` and a stale `Length`. Without `oneway` the planner will route the car
the wrong way down one-way streets, which is a legality and safety problem, not a
modelling nicety.

Match each customer arc to the nearest OSM arc within **15 m** and inherit
`highway_class`, `oneway`, `lanes`, `width`, `surface`, `maxspeed`, `name`, and
through the matched OSM identity, the **turn restrictions** as well.

The previous run already measured this: **336.6 km of 347.0 km (97.0%) matches.**
Reuse that machinery rather than writing a second matcher.

### 3.3 The 10.3 km OSM does not have — 127 parts

These need attributes synthesised and, more importantly, **stitching into the
routing graph**, or they become orphans that no tour can reach.

- Snap their endpoints to the nearest OSM node within tolerance; report any that
  cannot be connected at all.
- Attributes: treat as two-way residential at the default residential speed.
- **Flag every one of them `attributes_unverified = True`**, carry the flag into
  the turn sheets, and emit `surveys/unverified-streets.md` listing all 127 with
  location and length. The driver adjudicates one-way signage on the ground,
  because the data to do it in software does not exist.

Worth noting in the report: the unmatched pieces are **clustered** around
44.795–44.800 E, 41.695–41.701 N, not scattered. That looks like one new
development OSM has not caught up with. Say so — adding it to OSM would fix this
permanently for every future run, and is cheaper than carrying the workaround.

### 3.4 What run 2 must NOT do

Do not silently fall back to OSM geometry for the required set. If the customer's
layer says a street exists, it is required; if it does not, it is not — even where
OSM has one. Streets present in OSM but absent from the customer layer are
**routable, not required** (the previous run measured 0.7 km of such over-coverage).

---

## 4. Comparison report — the deliverable

`reports/RUNS-COMPARISON.md`, written once both runs finish:

| | Variant C (done) | Run 1: OSM full | Run 2: customer net |
|---|---|---|---|
| Required km | 390.9 | | |
| Days | 7 | | |
| Total h | 35.5 | | |
| capture / deadhead / turns | 13.5 / 13.8 / 8.2 | | |
| Deadhead as % of capture | 102% | | |
| **h per required km** | **0.091** | | |
| Streets never covered | 10.3 km | | |

Then answer, in plain language:

1. **What does including service roads actually buy?** Extra km covered versus
   extra days — is the marginal km worth the marginal day?
2. **Does the customer's network cost more or less per km than OSM's?**
3. **Which run would you quote a customer for**, and why?

That third question is the one this whole exercise exists to answer.

---

## 5. Failure policy

Unchanged: fix a failing gate and continue, recording it; stop and diagnose an
implausible number; choose per SPEC §1.1 for anything not covered here and log it.
Never weaken a gate to make it pass.
