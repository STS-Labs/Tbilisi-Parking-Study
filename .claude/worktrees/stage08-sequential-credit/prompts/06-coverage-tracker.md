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

**DECIDED 27 Aug 2026 — native HMM over our own L(G).** Not Valhalla, not fmm.

(The original brief named `fmm`. That was an unverified package name on my part:
the PyPI project called `fmm` is an unrelated numerical-computing library, not Fast
Map Matching. Do not install it.)

Build a Hidden Markov Model matcher directly against the `arcs` table:

- **Emission probability** from perpendicular distance to the arc, gated by bearing
  agreement (use `bearings.py`).
- **Transition probability** from **L(G)** — the legal-manoeuvre graph. A transition
  between two arcs is possible only if L(G) contains that manoeuvre, and its cost
  is that manoeuvre's cost. No off-the-shelf matcher has this information.
- **Viterbi** decode over the trace.

Rationale, so it is not re-litigated later: **coverage is defined on our
`arc_id`s.** Valhalla and fmm match onto their own re-processed graphs, requiring
an edge-ID → `arc_id` join afterwards. That join is lossy and many-to-many in
places, and it is precisely where "marked covered but never filmed" enters — the
failure this stage exists to prevent. A native matcher has no join. It is also
deterministic and seedable (CLAUDE.md rule 5), which a tile build is not.

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

## The trap in testing a native matcher

A native matcher shares its graph with the synthetic trace generator. **The
round-trip test is therefore nearly tautological** — you generate points from arcs
and match them back to arcs, proving little beyond that arcs equal arcs. This is a
weakness of the *test*, not of the matcher, and it must be fixed deliberately or
the whole suite is theatre.

Every synthetic trace must be passed through a **GPS error model** before matching:

- lateral noise ~5–15 m, with occasional 30–50 m excursions
- 1 Hz sampling, plus dropouts of 10–60 s (tunnels, underpasses)
- **parallel-street ambiguity** — the case where a trace genuinely sits closer to
  the street one block over than to the street actually driven. This is the real
  mechanism behind false coverage, and a nearest-arc matcher fails it every time.
  Tbilisi's centre has dense parallel one-way couplets; construct fixtures there.
- hillside multipath: the Mtatsminda and Vake slopes are the worst case in the city.

A matcher that passes clean synthetic traces and has never seen noise is untested.

## Confidence, and what to do with it

Every matched traversal carries a **confidence**. Below a configured threshold the
arc **stays required** — see the closing note. Report the distribution of
confidences per day, and the total km sitting in the marginal band; if that band is
large, the threshold or the error model needs work before the campaign relies on it.

## Gate — tests must assert

- **Round trip under noise:** a synthetic trace generated from a planned route,
  **passed through the error model**, yields ≥ 99% coverage of that route's
  required elements. A clean-trace round trip may be kept as a smoke test but does
  not count as evidence.
- **Parallel-street rejection:** a trace driven on street X, noised toward parallel
  street Y, must not mark Y covered. This is the single most important assertion in
  the stage.
- **Direction:** the same trace reversed yields coverage only where the pair
  requirement permits either direction, and **zero** on directed arcs.
- **Speed:** a synthetic trace at 60 km/h over `full`-quality arcs yields zero
  coverage; over `reduced` arcs it yields full coverage.
- Coverage is monotonic — a re-plan never marks something uncovered that was
  previously covered, absent an explicit exception.
- Remaining set + covered set + exceptions = the original required set, exactly.
- Determinism; all 886 existing tests still pass.

## Calibration will be unexercised — say so

Item 4 has no real traces to run on, so the turn coefficients stay **[CONFIRM]**.
Build it, wire it, test it against synthetic traces with known generating
parameters (the fit must recover them), and report it as **unexercised on real
data** rather than quietly shipping it as done.

## Non-goals

No dashboard — Stage 7 consumes these outputs. Do not change the plan's scope.
Do not build Valhalla tiles. If an independent cross-check is ever wanted, that is
a one-off referee run against a real trace, never a pipeline dependency.

---

**The failure that matters here** is the opposite of Stage 5's. There, a wrong GPX
sent the driver somewhere else. Here, a matcher that is too lenient marks streets
covered that were never filmed — and nobody finds out until the footage is
reviewed, weeks later, with the car long gone. **When a match is marginal, leave
the arc required.** Re-driving a street is cheap; discovering a hole in the data
after the campaign is not.
