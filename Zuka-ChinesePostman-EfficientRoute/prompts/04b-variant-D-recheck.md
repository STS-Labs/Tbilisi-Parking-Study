# Stage 4b — Re-test variant D, and dispose of the motorway traps

Two items. The first may reverse a scope decision; run it before Stage 5.

## Item 1 — re-run Stage 4 with `VARIANT = D`

**Why.** Variant C was chosen on 25 Aug because D "needed to start driving by
6 September". That figure came from a flat **1.2 h/day** depot-leg allowance.
Stage 4 has now measured the real thing: **17.1 h across the entire campaign**,
about 32 minutes per day — roughly 2.2x less than assumed. The arithmetic that
ruled D out is therefore wrong.

Recomputing on Stage 3's totals with the measured leg cost:

| Variant | Total h | Est. days @10 h | Finishes if started 25 Aug |
|---|---:|---:|---|
| C (built) | 271.7 | **32** (measured) | 25 Sept |
| D | 445.8 | ~51 | **~15 Oct** — inside the 30 Oct limit |
| A | 637.1 | ~73 | ~6 Nov — still outside |

If that holds, **D fits with about two weeks of margin**, and the 1,150 km of
through-connected service roads do not need to be deferred at all.

Run the full Stage 4 pipeline at `VARIANT = D` and report the same table as
variant C: zone count, day durations, stdev, depot-leg total, taper analysis,
calendar start→finish, and latest feasible start. Change no defaults — C remains
what the pipeline builds until the numbers are in and the decision is remade.

**Do not** reason from the C zoning by scaling. D has more and more scattered
requirements; its legs and balance must be measured, not extrapolated. That
extrapolation error is exactly what caused this re-check.

## Item 2 — dispose of the trapped motorway and trunk arcs

The unreachable set halves under C (129.9 → 64.5 km), but its character changed:
of the 14.0 km trapped *inside* L(G), **12.1 km is motorway or trunk**. Against a
motorway + trunk requirement of ~187 km, that is ~6.5% of the fast network
unreachable — not a rounding error, and SPEC §1.1 requires a disposition.

Investigate whether the cause is:

- **Stage 1's mainline-entry rule** — motorway/trunk enterable only via `*_link`.
  If a mainline's only OSM connection is a plain junction rather than a tagged
  ramp, the rule strands it. Check how many of the 12.1 km fail this way.
- **The no-U-turn-on-motorway policy**, stranding a mainline stub with no
  legal turnaround.
- **Clip-boundary geometry** already classified in Stage 0b.

Report the split. Where the cause is a modelling rule rather than physical
reality, propose the narrowest fix that restores reachability without weakening
invariant U1 — and state what it costs. Do not widen the U-turn policy globally.

## Item 3 — take the extra day

Stage 4 defaulted to fewest days, reserving no room for commute capture, because
`DECISION-schedule.md` had turned on the calendar. **That constraint is gone**:
the latest feasible start is 6 October, giving 42 days of slack.

SPEC §4 states total driving hours is the KPI. Switch the default: reserve the
room, reclaim ~3x the commute capture, and accept the 33rd day for a 9.3 h saving
in total driving. Put the constant in `config` with both profiles reported.

If Item 1 moves the project to variant D, re-derive this trade-off there rather
than carrying C's number across.
