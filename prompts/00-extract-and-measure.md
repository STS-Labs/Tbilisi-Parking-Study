# Stage 0 — Extract & measure the Tbilisi street network

Read `SPEC.md` (especially §1.1, §2, §3.1) and `CLAUDE.md` before starting.

## Purpose

Produce the canonical directed-arc network for Tbilisi and **measure it**, so that
every later stage works from real numbers instead of estimates. This stage does no
routing and no optimisation.

## Inputs

- Geofabrik extract `georgia-latest.osm.pbf` → `data/raw/`
- Tbilisi municipality boundary from OSM (find the administrative relation; record
  its ID in the report — do not hardcode a bounding box)
- A DEM covering the municipality (Copernicus GLO-30 or SRTM) → `data/raw/`

## Tasks

### 1. Set up
`uv` project, `src/efficientroute/` package, `tests/`. Pin dependencies.

### 2. Extract and clip
Clip the PBF to the municipality boundary plus a configurable buffer (default
2 km, so that routes near the edge are not artificially trapped).

### 3. Build the directed arc table
Every way becomes one or two directed arcs. Required columns:

`arc_id, way_id, from_node, to_node, geometry, length_m, highway_class, lanes,
width, surface, maxspeed, oneway, incline, gradient_pct, min_passes,
pair_id, pair_requirement, capture_quality, excluded, exclusion_reason`

- `gradient_pct` from the DEM where `incline` is untagged.
- `pair_id` groups the two arcs of a two-way street; `pair_requirement` is the
  shared traversal count for narrow two-way pairs (see SPEC §2.1).
- `capture_quality` = `"reduced"` for motorway/trunk and their links, else `"full"`.

### 4. Apply the drivability filter
Exclude per SPEC §3.1. **Every exclusion carries a machine-readable reason.**
Excluded rows stay in the table with `excluded=True` — do not delete them.

### 5. Assign `min_passes`
Implement SPEC §2.1 exactly, including the §1.1 fallback chain:
`lanes` → `width` → class → **default 2**. Count how many arcs reach the default.

### 6. Connectivity
Compute strongly connected components on the included arcs. Take the largest.
Report every fragment that falls out, with its size and location.

## Outputs

- `data/derived/network.gpkg` — layer `arcs`, the canonical network.
- `reports/00-network-stats.md`
- `reports/00-network.html` — interactive map, arcs coloured by `min_passes`,
  excluded arcs and orphan fragments shown in distinct styles.

### The report must contain

1. **Total centerline km** and **total arc km**.
2. **Required traversal km** = Σ (`length_m` × required passes), counting narrow
   two-way pairs once. *This is the headline number — it determines the campaign
   length. State it prominently.*
3. Breakdown of required traversal km by `highway_class` and by `min_passes`.
4. One-way share of the network, by count and by length.
5. **Tagging completeness:** % of arcs with `lanes`, with `width`, with `maxspeed`,
   with `surface`. Then the count and total km of arcs that hit the
   `min_passes = 2` fallback because all three were inconclusive.
6. Exclusions: count and km grouped by `exclusion_reason`.
7. SCC analysis: size of the largest component, list of orphan fragments.
8. `highway=service` isolated as its own line item, so the open scope decision in
   SPEC §2.1 can be made against a real number.
9. Count of OSM `type=restriction` relations found (do not parse them yet — that
   is Stage 1 — just count, so Stage 1 can be scoped).

## Gate — tests must assert

- Re-running the pipeline on unchanged inputs produces a byte-identical `arcs`
  layer (determinism).
- Every arc has a non-null `min_passes ≥ 1`.
- Every excluded arc has a non-null `exclusion_reason`.
- Every two-way `pair_id` maps to exactly two arcs.
- Sum of per-class km equals total km (no double counting, no loss).
- Every arc geometry has ≥ 2 coordinates and non-zero length.
- The largest SCC contains ≥ 95% of included arc km — **if not, stop and report**,
  because it means the drivability filter or the one-way data is wrong.

## Non-goals

No routing. No turn expansion. No time model. No zoning. No optimisation.
Do not tune the `min_passes` thresholds yet — measure first, calibrate at the gate.
