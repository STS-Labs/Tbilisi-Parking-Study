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

## Reports compute their conclusions; they never hard-code them

A sentence of interpretation written by hand into a generated report is a lie
waiting for the next run. Stage 8's first `08-SUMMARY.md` asserted "Tbilisi saves
hours and no days" — true of tier 1, falsified by tier 2 an hour later. Rewriting it
to derive its conclusions from the artifacts immediately caught a *second* stale
claim in the same file.

If a report states a finding, it must compute that finding from the data it is
reporting on. Prose that cannot be re-derived does not go in a generated file.

## `git add -A` from the repo root reaches into worktrees

Commit `f071fcd` intended two small edits and swept in 589 files / 1.22M lines —
an entire second checkout under `.claude/worktrees/`, including a 47 MB `.gpkg` and
a 14 MB `.pkl`. Worktrees live inside the repo, so a blanket add finds them.

- `.claude/` is now in `.gitignore`. Keep it there.
- Check `git status --short` before any blanket add. Blind `git add -A` in a repo
  that contains generated geodata is how 107 MB enters history permanently.

## History rewrites: before the first push, never after, never without a bundle

This repository has **no remote**. It is the only copy of the work. A history
rewrite on a sole copy, to reclaim disk, is a bad trade at any size. The rule:

1. `git bundle create <path> --all`, and verify it by cloning from it.
2. Rewrite only when the bloat has a real cost — i.e. immediately before adding a
   remote and pushing for the first time, when the objects would otherwise be
   published forever.
3. Never rewrite history that has been pushed.

## A run that cannot fail is not a run that passed

Twice now this project has produced a confident green result over broken work:

1. Hierholzer returning an **open walk** on an unbalanced graph without complaining
   — a convincing-looking non-tour (caught by `tourcheck.py`, written first).
2. A sweep runner piping each campaign into `tail`, so the shell saw **tail's** exit
   status. Two of four campaigns crashed; all four reported success.

The second is the worse defect, because the first was a wrong answer and the second
was a wrong answer that suppressed the evidence.

Rules:

- **Never pipe a step whose exit status matters.** Capture output to a per-step log,
  check the status explicitly, and propagate a non-zero exit.
- A multi-item runner reports **per item**, not in aggregate. "All four succeeded"
  must mean four checked statuses.
- Where a result is a claim about correctness, the check must be capable of
  **failing on real data** — not just on a fixture built by the same code path.

## Calibration constants are pinned, not fed back

Some constants are read by an early stage and measured by a later one
(`ZONE_OVERHEAD_MEASURED` is the live example: Stage 4 reads it, Stage 5 writes it).
**Such a loop does not converge** — re-running the early stage on the later stage's
last output produces a different plan, not a better one, and the partition can be
knife-edge sensitive to the value.

Rules:

1. Pin the value explicitly in `config`, at full precision, with a comment naming
   where it came from and when.
2. Changing it is a deliberate, reviewed act with a measured justification — never
   an automatic refresh.
3. When a constant is derived, check that the derived quantity is the one the cost
   model actually wants. Stage 4c's defect was not a stale number but a *wrong
   quantity*: `route_h / capture_h` already contains depot legs, which the cost
   model then added again.

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
