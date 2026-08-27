# Stage 3 — Bound the problem, and produce the first real deadhead number

Read `SPEC.md` §4 (Stage A), §8, §9 and `CLAUDE.md`. Stage 2's gate must have passed.

## Purpose

Two things, and the second matters more than the brief originally implied:

1. A **provable lower bound** on total driving time — the benchmark every later
   result is scored against (CLAUDE.md rule 2).
2. A **constructive upper bound**: a single closed tour that actually covers the
   whole city legally. This is a real, drivable plan, and its deadhead percentage
   is the number that decides the A/D/C scope question.

Stage 2's estimate is a floor because it counts capture + turn only. Stage 3 is
where deadhead stops being assumed.

---

## Item 1 — the node-split transform (get this right first)

`L(G)` has **nodes** that must be visited, but postman problems are defined over
**edges**. Split every L-node before doing anything else:

- Each L-node `a` becomes `a_in → a_out`, joined by a **required edge** of cost
  `capture_time_s(a)` and lower bound `min_passes(a)`.
- Each legal manoeuvre `a → b` becomes `a_out → b_in`, cost = turn penalty.

Call the result `L*`. Covering arc `a` at least `k` times is now exactly
"traverse required edge `(a_in, a_out)` at least `k` times" — a Directed Chinese
Postman with lower bounds, which **min-cost flow with lower bounds solves exactly**.

Do not skip this. Trying to cover *nodes* directly is the standard way this
problem gets solved wrongly.

## Item 2 — the constructive upper bound (a real plan)

1. **Orient the narrow pairs.** For each shared pair, choose one direction as
   required and set the other's lower bound to 0. Start from a greedy orientation
   that minimises node imbalance, then local-search by flipping orientations that
   reduce total imbalance.
2. **Solve the DCPP exactly** for that orientation: min-cost circulation with
   lower bounds (OR-Tools `SimpleMinCostFlow`, or `networkx.network_simplex`) to
   find the cheapest way to balance the graph.
3. **Extract an Euler circuit** (Hierholzer) over the augmented multigraph.

This yields a **complete, legal, closed single tour of Tbilisi**. Report its total
time, its capture time, and:

> **`deadhead_ratio = (total_time − capture_time − turn_time) / capture_time`**

Because the orientation is fixed by a heuristic, this is an **upper** bound on the
relaxation, not a lower one. Label it as such everywhere. It is nonetheless a valid
feasible solution and the best schedule evidence available before Stage 5.

## Item 3 — the genuine lower bound

Fixing an orientation constrains the problem, so it cannot bound from below.
Compute a valid lower bound separately, by the cheapest method that is actually
tight enough to be useful:

- **Preferred:** the LP relaxation of the generalised routing MIP, where each
  narrow pair contributes a single "at least one of the two" constraint and the
  integrality of traversal counts is relaxed. HiGHS handles a problem of this size.
- **Fallback if the LP does not solve in reasonable time:** Σ capture time over
  required elements plus the minimum balancing flow computed with each narrow pair
  allowed to take whichever direction is cheaper. Weaker, but valid and cheap.

Report which was used. Report `optimality_gap = (upper − lower) / lower`.

## Item 4 — run it for all three variants

Produce the full table for **A** (all service), **D** (`service_role = through`
only — drop `spur` and `orphan`) and **C** (no service). Per variant:

| capture h | turn h | deadhead h | deadhead % | total h | lower bound h | gap % | days |

`days = total_hours / productive_hours_per_day`, with `productive_hours_per_day`
taken from Stage 2 and **stated explicitly in the report**.

Add a second table at a **10:00-hour shift window (08:00–18:00)** alongside the
9-hour baseline. This is the cheapest schedule lever available and it needs to be
quantified, not guessed.

## Outputs

- `data/derived/03-bounds.json`
- `reports/03-bounds.md`
- `reports/03-tour-A.gpx` — the constructive tour for variant A, as a sanity
  artifact. It is not a day plan; do not present it as one.

## Gate — tests must assert

- **I1** every required element is traversed ≥ its lower bound in the tour.
- **I2** every consecutive manoeuvre in the tour is a legal edge of `L*`.
- The tour is **closed** and uses only edges present in `L*` (**I6**).
- `upper ≥ lower` for every variant. A violation means one of the two is wrong.
- Tour total time equals the sum of its edge costs, recomputed independently.
- Determinism: identical tour and identical bounds across runs.
- All 566 existing tests still pass.

## Non-goals

No zoning. No day-splitting. No depot legs. Do not choose a variant. The single
tour is a bound and a sanity check, not a deliverable.

---

**Process note.** Stage 2 was written implementation-first rather than gate-first.
For Stage 3 the order matters more than it did there: the invariant suite is the
only thing separating a plausible tour from a wrong one, and a wrong tour looks
entirely convincing. Write I1, I2 and the closure test before the solver.
