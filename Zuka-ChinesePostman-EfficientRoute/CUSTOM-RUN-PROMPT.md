# Autonomous run — Zone B custom campaign

Run the full EfficientRoute pipeline, Stages 0 → 7, for a customer-supplied zone.
**Run it to completion without stopping to ask questions.** Every decision that
required a human in the Tbilisi run is pre-answered below. If you hit one that
isn't, choose the option SPEC §1.1 (accuracy first) implies, log it in the final
report under "Decisions I had to make", and keep going.

---

## 1. Hard constraints

1. **Every output goes to `/Users/mat/Desktop/EfficientRoute/CUSTOM-OUTPUT/`.**
   Mirror the normal layout inside it: `data/derived/`, `reports/`, `surveys/`.
2. **Do not modify, overwrite or delete anything in the existing `data/derived/`,
   `reports/` or `data/raw/`.** The committed 47-day Tbilisi plan must still
   regenerate byte-identically when you are done. Verify this at the end.
3. Implement this as an **output-root parameter** (e.g. `OUTPUT_ROOT`,
   `--output-root`), not by copying the repo or branching the code. One codebase,
   two runs.
4. `data/raw/` is shared and read-only for this run — reuse the same
   `georgia-latest.osm.pbf` and DEM. Do not re-download.
5. The repo is a git repo. Commit at each stage boundary. Note: the working tree
   is on a mount that has previously left stale `.git/*.lock` files behind; if a
   commit fails for that reason, remove the lock and retry.

---

## 2. What is actually in the input folder — already inspected, don't re-derive

`data/custom/B Zone_Streets/` contains two ESRI shapefiles. **They are not in the
same coordinate system**, which is the single most likely thing to go wrong.

### `AB_zones.shp` — THE BOUNDARY

| | |
|---|---|
| Geometry | **PolygonZ (shape type 15)** — has Z values; drop them |
| CRS | **EPSG:4326** (WGS84 geographic, lon/lat) |
| Features | **1** — `Name = "Zone B"` |
| Rings | 1, 216 vertices |
| Area | **23.96 km²** |
| Perimeter | 41.87 km — highly convoluted (a circle of that area would be 17.4 km) |
| Provenance | `FolderPath` says it came from `Tbilisi Possible parking zones.kmz` |

This polygon **replaces OSM relation 1996871** as the Stage 0 boundary.

### `Streets.shp` — NOT the routing network

| | |
|---|---|
| Geometry | Polyline, 3,368 parts across 3,358 features |
| CRS | **EPSG:32638** (WGS 84 / UTM zone 38N) — *different from the boundary* |
| Total length | **347.0 km** (median part 65 m, p90 233 m, max 1,479 m) |
| Attributes | `Id` (all zero) and `Length` (a stale value in degrees) — **nothing else** |

**There is no name, no highway class, no `oneway`, no `lanes`, no `width`.** The
entire coverage model depends on those: `min_passes`, the narrow-pair rule,
`capture_quality`, the class-based speed model, one-way handling. This layer
therefore **cannot drive the pipeline**.

Its bounding box matches Zone B's almost exactly, so it is the customer's own
extraction for this zone. Use it as a **reconciliation layer** (§6), not as input
geometry.

### Depot

Unchanged: **41.730736 N, 44.734583 E**. It is **outside Zone B**, 394 m from the
nearest boundary vertex and 4.1 km from the zone centroid. Depot legs are short;
this is not a problem, but it does mean legs run over non-required streets, so
"capture on the commute" has little to work with. Expect it to reclaim near zero
and do not treat that as a bug.

---

## 3. The one real architectural change

In the Tbilisi run, **required = everything in the clip**, which quietly reduced
the problem to a Chinese Postman. Zone B separates the two for the first time:

- **Required set** = arcs whose geometry lies inside the Zone B polygon.
- **Routable set** = required arcs **plus** a surrounding buffer the car may
  deadhead over, including the roads between the depot and the zone.

Use a **2 km buffer around Zone B** for the routable network (same figure as the
Tbilisi clip), and confirm it contains the depot with margin.

Stage 0 must therefore carry `required` and `included` as genuinely independent
flags. An arc in the buffer is `included = True, required = False`: legal to drive,
never needs filming.

> **This makes it a true Rural Postman instance for the first time.** The solver
> was written for it and Stage 3 already calls it that, but it has only ever run
> with required = all. Watch for: the LP lower bound behaving differently, the
> orientation heuristic having less to bite on, and connected components appearing
> in the required set that were previously impossible. If Stage 3's bracket looks
> strange, this is the first place to look — it is a new regime, not necessarily a
> bug.

Boundary rule: an arc is required if **its midpoint falls inside the polygon**.
Report how much length sits within 50 m of the boundary, since that is where the
rule is arbitrary and where a customer dispute would land.

---

## 4. Decisions — settled, do not ask

Carry forward everything from the Tbilisi run:

| Setting | Value |
|---|---|
| Scope variant | **C** — `highway=service` excluded |
| Coverage rule | passes model per SPEC §2.1 (narrow pair / directed / wide) |
| `capture_speed_max` | 40 km/h; motorway + trunk exempt, `capture_quality="reduced"` |
| Shift window | **9 h, 09:00–18:00**, 45 min break |
| Working days | 7 per week |
| Depot | 41.730736 N, 44.734583 E |
| Turn expansion | full, incl. via-way restrictions; **motorway narrowing adopted** |
| Zone sizing | `p75` of the measured overhead distribution |
| Commute reserve | reserved profile (`ZONE_PREFER_FEWEST_DAYS = False`) |
| Zone sequence | far zones first |
| Matcher | native HMM over L(G) — **never** Valhalla, never the PyPI `fmm` |
| Governing principle | SPEC §1.1 — accuracy first; ambiguity resolves toward more coverage |

**Campaign start date: the day after this run completes.** State it explicitly.

### On the transferred constants

`ZONE_OVERHEAD_MEASURED` was calibrated on Tbilisi-wide zones. Per CLAUDE.md, it is
**pinned, not fed back** — reuse the Tbilisi value, and label it in the report as
**transferred, not measured for this zone**. Let Stage 5 report what the zone
actually achieves. Do not silently re-derive it mid-run.

---

## 5. Stages — expected shape, and pre-answered gates

Expected size, so you can tell "wrong" from "small": roughly **340–400 km of
required traversal** and **4–7 driving days**. If you get 30 days or 0.5 days,
something is wrong — stop and diagnose rather than reporting it.

| Stage | Pre-answered |
|---|---|
| **0** | Boundary = Zone B (reprojected). Variant C. Report the required/buffer split. |
| **0b** | `service_role` still computed as a column even though C excludes service. |
| **1** | Motorway narrowing on. Traps: classify `clip_boundary` vs `genuine` as before. |
| **2** | Same speed model and coefficients. Turn coefficients remain **[CONFIRM]**. |
| **3** | Both bounds. **This is the true-RPP stage — comment on how it differs.** |
| **4** | p75, reserved profile, far-zones-first. Few zones is expected, not an error. |
| **5** | Full GPX + turn sheets + lane instructions. |
| **6** | Build it; no real traces exist, so calibration is **unexercised** — say so. |
| **7** | Full animated playback per the Stage 7 brief. |

**Degenerate cases to handle rather than crash on:** the whole job may be a handful
of zones, possibly one. Daylight taper and campaign-calendar logic will have almost
nothing to do. Balance statistics over 4 zones are not meaningful — report them,
but do not fail a gate on stdev with a sample that small.

---

## 6. Reconciliation — the deliverable the customer will actually check

Compare **OSM-clipped-to-Zone-B** against the customer's `Streets.shp` (reproject
to a common CRS first). Produce `reports/CUSTOM-reconciliation.md`:

1. **In the customer's layer but not in OSM.** These will **never be covered** by
   the plan, and the customer will notice. List them with length and location, and
   put the total km in the summary. This is the most important table in the run.
2. **In OSM but not in the customer's layer.** Extra coverage — is the plan doing
   work the customer did not ask for? Quantify it.
3. **Matched.** Total km agreeing within a stated buffer tolerance.
4. Customer total is **347.0 km** — reconcile your matched + unmatched against it
   and explain any gap.

Match by geometric proximity with a stated tolerance (~15 m), not by attributes —
the customer layer has none.

---

## 7. When something fails

- **A gate fails:** fix it and continue. Record what failed and what you changed in
  the final report. Do not weaken a gate to make it pass; if a threshold genuinely
  does not transfer to a zone this small, say so explicitly and justify the new one.
- **A stage produces an implausible number:** stop and diagnose. Reporting a wrong
  number confidently is the worst outcome available.
- **You need a decision not covered here:** choose per SPEC §1.1, log it, continue.

Use subagents freely. Note that Stages 0→5 are inherently sequential and gated, so
the parallelism worth having is in the **reconciliation analysis**, **independent
verification of gate results**, and **drafting the final report** — not in trying
to run the pipeline stages concurrently.

---

## 8. Final report

`CUSTOM-OUTPUT/reports/CUSTOM-SUMMARY.md`:

- The plan: days, dates, total hours, required km, capture/deadhead/turn split
- Comparison table against the Tbilisi run — per-km efficiency, deadhead ratio,
  overhead factor. **Is a small dense zone more or less efficient per km?** Nobody
  knows yet; this run answers it, and the answer prices every future customer job.
- Reconciliation summary, with unmatched customer streets front and centre
- Every constant transferred rather than measured, listed as such
- Every decision you had to make
- Confirmation that the Tbilisi artifacts still regenerate byte-identically
