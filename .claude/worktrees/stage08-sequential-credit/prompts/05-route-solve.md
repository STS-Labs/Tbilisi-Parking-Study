# Stage 5 — Solve each day's route, and produce the GPX

Read `SPEC.md` §4 (Stages C–E), §2.3, §8 and `CLAUDE.md`. This is the NP-hard core
and the first stage whose output a human actually uses.

## Prerequisite — rebuild first

Three settings changed together. Rebuild Stages 1–4 once, then solve:

1. `SCOPE_VARIANT = "C"` (confirmed)
2. Shift window **9 h, 09:00–18:00** (confirmed; C = 38 days, finish 1 Oct)
3. **Adopt the motorway narrowing** — ramp-only entry relaxed at un-ramped
   junctions, the 3 verified manoeuvres. It changes L(G), so it must land before
   any route is solved.

Confirm the rebuilt Stage 4 plan matches expectations before proceeding.

## Purpose

For each zone, produce a route that starts at the depot, covers every required
element in that zone, returns to the depot, and is legal and drivable throughout.

## Method

### 1. Per-zone problem
Required set = that zone's elements. **Deadhead is allowed over the entire
network**, not just the zone — restricting deadhead to zone boundaries produces
worse routes and can make a zone infeasible. Solve on the node-split turn-expanded
graph `L*` from Stage 3.

### 2. Heuristic first, always
Frederickson-style construction plus the Stage 3 balance-and-connect machinery →
a feasible route for every zone. This is the floor: **no zone may end this stage
without a valid route.** Never let a MIP time-out leave a day unplanned.

### 3. Exact solve, time-limited
MIP formulation of the generalised directed rural postman with multiplicities,
per zone, HiGHS, warm-started from the heuristic. Cap solve time per zone and
**report the per-zone optimality gap** — a zone that hit its limit is a known
approximation, not a silent one.

### 4. Run the orientation local search — the untouched lever
SPEC §4 Stage D's orientation-flip search has never run. Stage 3's heuristic
removed only **5.7%** of junction imbalance, and Stage 3 showed routing is already
within 1% of optimal *for its orientation* — so orientation is where the remaining
savings are, if any exist. Quantify what it recovers. If it recovers little, say
so plainly and close the question.

### 5. Resolve the turn estimate
Stage 2's turn time was a 91.2–145.0 h range swinging the campaign 7.3 days;
Stage 3's tour came in at 190.0 h. Stage 5 makes the turn count **exact**. Report
the final figure against both, and note that per-turn *seconds* remain unvalidated
assumptions from SPEC §3.3 — the count is now settled, the coefficients are not.

## Outputs

- `data/derived/05-routes.gpkg` — ordered manoeuvre sequence per day
- `reports/05-routes/day-NN.gpx` — one file per driving day
- `reports/05-routes/day-NN.md` — turn-by-turn sheet, human-readable
- `reports/05-routes.md` — per-day table (capture h, deadhead h, turn h, total h,
  optimality gap), campaign totals against the Stage 3 bracket, calendar

**Lane instructions (invariant I8).** Any arc with `min_passes ≥ 2` must state
which lane group each pass uses. Without it the driver repeats the same lane and
the second pass is wasted footage.

## Gate — tests must assert

- **I1** every required element covered ≥ its `min_passes`, summed across all days.
- **I2** every consecutive manoeuvre in every day is a legal edge of `L*`.
- **I3** every day starts and ends at the depot.
- **I4** no day exceeds its window: capture + turns + deadhead + legs + break.
- **I5** campaign total lies within the Stage 3 bracket (381.6–637.1 h scaled to C).
- **I6** every arc in every route exists in the base network.
- **I7** no required traversal above 40 km/h except `capture_quality = "reduced"`.
- **I8** every multi-pass arc carries a distinct lane instruction per pass.
- Every zone has a route. No zone left unsolved by a timeout.
- **GPX validation:** parses as XML, geometrically closed, all points inside the
  Tbilisi bbox, and the point sequence matches the solved manoeuvre sequence
  arc-for-arc. A GPX that parses but diverges from the solution is the worst
  possible failure — it looks fine and sends the driver somewhere else.
- Determinism; all 861 existing tests still pass.

## Non-goals

No coverage tracking, no re-planning — Stage 6. No dashboard — Stage 7.

---

**A note on what this stage is for.** Everything before this was analysis; this is
the first artifact a person follows in a car. A route that is 3% suboptimal but
clear and legal beats one that is optimal and ambiguous at a junction. Where the
two conflict, favour the driver.
