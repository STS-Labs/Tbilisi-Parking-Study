# EfficientRoute — standing rules

Camera-car coverage planner for the Tbilisi street network.
**`SPEC.md` is the contract.** Read it before every stage. If a request conflicts
with SPEC.md, stop and say so rather than resolving it silently.

## Governing principle

**Accuracy is a hard constraint; efficiency is the objective subject to it.**
Every ambiguous case resolves toward more coverage, not less. See SPEC.md §1.1.

## Non-negotiables

1. **Never invent geometry.** Every coordinate in every output must trace back to
   an arc in the base network. No interpolation, no smoothing, no synthesised
   connectors.
2. **Every result is reported against the Stage 3 lower bound.** A route with no
   stated optimality gap is an incomplete result.
3. **Total driving hours is the KPI.** Deadhead ratio is a diagnostic, not a
   target — the coverage rules deliberately inflate it. Never optimise for it.
4. **Exclusions are logged, never silent.** Any way, arc or node dropped from the
   network carries a machine-readable reason. An unexplained drop is a bug.
5. **Determinism.** Same inputs, same outputs. Seed everything. No wall-clock or
   random behaviour in the pipeline.
6. **Stages are gated.** Do not begin a stage until the previous stage's gate has
   passed. Do not optimise on top of an unconfirmed assumption.

## Invariants — assert these in tests, not in prose

I1–I8 are defined in SPEC.md §8. Every stage that produces or transforms a route
runs the full invariant suite. A failing invariant is a hard stop.

## Repository layout

```
SPEC.md              the contract
CLAUDE.md            this file
prompts/             one prompt per stage
src/efficientroute/  package code
data/raw/            downloaded sources, never edited
data/derived/        generated artifacts (network.gpkg, graph.pkl, …)
reports/             human-readable stage reports + maps
tests/               invariant + unit tests
```

`data/derived/` and `reports/` are regenerable. Never hand-edit them.

## Stack

Python 3.11+, `uv` for dependency management. Geospatial: `pyrosm`/`osmium`,
`geopandas`, `shapely`, `pyproj`, `rasterio`. Graph: `networkx` (correctness
reference) with `scipy.sparse` / `igraph` where scale demands. Optimisation:
`ortools` min-cost flow, `highspy` for MIP. Map matching: Valhalla Meili or `fmm`.
Output: `gpxpy`, `folium`.

## Working style

- Write the test that asserts the gate **before** the code that passes it.
- Persist stage outputs to disk; never rebuild an upstream stage in memory.
- Report real numbers, not estimates. If a number is estimated, label it.
- Prefer a slow correct implementation first, then optimise with a benchmark.
- When a data-quality problem appears, surface it in the stage report. Do not
  paper over it — Tbilisi's OSM tagging is uneven and that is a finding.
