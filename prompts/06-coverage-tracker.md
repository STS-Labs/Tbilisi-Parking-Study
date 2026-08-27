# Stage 6 — Coverage tracker and re-planner

Read `SPEC.md` §10, §5, §6 and `CLAUDE.md`. This is the stage that decides whether
the project works in practice.

## Purpose

Everything so far assumes the plan is followed. It won't be. Streets are closed,
lanes are blocked, drivers improvise, GPS drops. Stage 6 closes the loop: take what
the car **actually did**, work out what is **actually covered**, and re-plan the
remainder.

SPEC §10's framing holds — this is a re-planner that happened to run once at the
start, not a planner with re-planning bolted on. Day 1 is simply the case where the
remaining set is everything.

## Item 1 — ingest and map-match

Input: the day's GPS trace (GPX/NMEA/CSV from the rig).

Map-match onto the base network with Valhalla Meili or `fmm`. Matching must be
**direction-aware** — the matched heading has to agree with the arc's bearing.

## Item 2 — decide what actually counts as covered

A traversal counts only if **all** hold:

- matched to the arc with heading within ±T° (T in `config`)
- speed ≤ `capture_speed_max`, **except** arcs with `capture_quality = "reduced"`
- the rig was actually recording — cross-check trace timestamps against footage
  timestamps if the Stereolabs output exposes them. **A GPS trace is evidence the
  car was there, not that the camera was on.** If that cross-check is not possible,
  say so explicitly in the report rather than assuming.

Then decrement `min_passes` on matched arcs and recompute the remaining required
set. A wrong-direction or too-fast pass does not count and the arc stays required.

## Item 3 — the exceptions register  *(operationally essential)*

When a street turns out to be undrivable — permanently closed, gated, too narrow,
under construction — the driver must be able to record it, and the re-planner must
**permanently retire** it rather than re-planning it every single day.

Build a simple exceptions file: `arc_id`, reason, date, reporter, and whether it is
permanent or temporary. Temporary exclusions return to the required set after a
configurable interval. Report the running total of retired km, because it directly
reduces what "complete coverage" can mean — and that number belongs in the final
coverage figure, not hidden.

## Item 4 — calibrate for free

The traces contain measurements the model has been guessing at. Extract them:

- **Turn coefficients.** SPEC §3.3's left 8 s / right 3 s / u-turn 20 s are my
  estimates, still marked [CONFIRM], and turn time is **17.4% of all driving**.
  Junction dwell times in the trace measure them directly. This removes the need
  for a stopwatch survey.
- **Speed model.** `SpeedModel.fit` already exists for this. Refit and report how
  far the assumed coefficients were off — including the downhill/uphill ratio (0.5)
  that has never been measured.
- **Congestion multipliers**, by class and time-of-day band.

Report the refit against the assumptions. If the campaign estimate moves materially,
that is a schedule finding and must be surfaced, not absorbed.

## Item 5 — re-plan

Recompute the remaining required set and re-run Stages 4–5 over it. Report the
revised finish date each time.

## Outputs

- `data/derived/06-coverage.gpkg` — per-arc coverage state and evidence
- `data/derived/06-exceptions.csv`
- `reports/06-day-NN.md` — planned vs actual, divergence, coverage gained,
  calibration deltas, revised finish date
- Updated GPX for the following day

## Gate — tests must assert

- **Round trip:** a synthetic trace generated from a planned route yields **100%**
  coverage of that route's required elements. If it does not, the matcher is wrong.
- **Direction:** the same trace reversed yields coverage only where the pair
  requirement permits either direction, and **zero** on directed arcs.
- **Speed:** a synthetic trace at 60 km/h over `full`-quality arcs yields zero
  coverage; over `reduced` arcs it yields full coverage.
- Coverage is monotonic — a re-plan never marks something uncovered that was
  previously covered, absent an explicit exception.
- Remaining set + covered set + exceptions = the original required set, exactly.
- Determinism; all 886 existing tests still pass.

## Non-goals

No dashboard — Stage 7 consumes these outputs. Do not change the plan's scope.

---

**The failure that matters here** is the opposite of Stage 5's. There, a wrong GPX
sent the driver somewhere else. Here, a matcher that is too lenient marks streets
covered that were never filmed — and nobody finds out until the footage is
reviewed, weeks later, with the car long gone. **When a match is marginal, leave
the arc required.** Re-driving a street is cheap; discovering a hole in the data
after the campaign is not.
