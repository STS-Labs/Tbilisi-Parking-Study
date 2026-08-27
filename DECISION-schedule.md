# Schedule decision — required before Stage 4

Raised 25 Aug 2026, on Stage 3 evidence. SPEC §7.3's revisit condition is met.

## The measured position

Stage 3 brackets the optimum. Upper end is a real, legal, closed tour.

| Variant | Capture h | Turn h | Deadhead h | Total h | Lower bd h | Gap |
|---|---:|---:|---:|---:|---:|---:|
| A — all service | 270.9 | 190.0 | 176.3 (65.1%) | **637.1** | 381.6 | 67.0% |
| D — through-service only | 215.3 | 106.6 | 123.9 (57.5%) | **445.8** | 285.2 | 56.3% |
| C — no service | 139.2 | 51.0 | 81.5 (58.5%) | **271.7** | 178.3 | 52.4% |

**Better routing will not rescue this.** Stage 3 showed the 67% gap is bound
looseness, not tour slack: LP 381.6 h → integral single-orientation flow 631.1 h →
connected tour 637.1 h. The routing is within 1% of optimal *for its orientation*.
The LP sits far below any integral solution because it may cover half of one
direction of a narrow pair and half of the other — a fractional answer no car can
drive. Do not budget for savings that are not there.

The one genuine routing lever left is the **orientation** heuristic, which removed
only 5.7% of junction imbalance. SPEC §4 Stage D's orientation-flip local search
has never been run. Headroom unmeasured, and it is the only place Stage 5 might
still find material savings.

## Days, including a depot-leg allowance

Stage 3's day counts exclude depot legs. Allowing 1.2 h/day (Stage 4 measures it):

- 9 h window ⇒ 7.05 productive h/day · 10 h window ⇒ 8.05 productive h/day

| Config | Days | Must start driving by |
|---|---:|---|
| A · 1 car · 10 h | 79.1 | **impossible** — needed 13 Aug |
| A · **2 cars** · 10 h | 39.6 | 22 Sept |
| D · 1 car · 10 h | 55.4 | 6 Sept |
| D · **2 cars** · 10 h | 27.7 | 4 Oct |
| C · 1 car · 10 h | 33.8 | 28 Sept |

"Must start by" = 1 November minus the day count. Stages 4 and 5 are not built yet.

## What this means

1. **Variant A is impossible with one car this year.** Not tight — impossible, at
   either shift length, before depot legs are even counted.
2. **Variant D with one car is effectively lost too.** It needs to start driving by
   6 September. Stage 4 and Stage 5 will not be finished and validated by then.
3. **A second vehicle is the only lever that preserves full scope.** Two cars make
   even variant A fit, with a 22 September start. It costs a second rig and driver,
   and a modest change to Stage 4 — partition into two vehicle-streams from the
   same depot.
4. **One car, this autumn, means variant C** — and C drops 1,150 km of
   through-connected service roads that function as streets. Under SPEC §1.1 that
   is the weakest option on the table.
5. **Or accept a winter tail.** Not fatal, but low winter sun and long shadows
   degrade stereo capture, which is an accuracy cost, not just a comfort one.

## The decision

Pick one:

- **Two cars, variant A or D** — preserves scope, fits the window.
- **One car, variant C** — fits the window, loses real streets.
- **One car, variant D, winter tail** — preserves most scope, finishes ~mid-Nov
  with degraded light on the tail.

Everything downstream — Stage 4 zoning, Stage 5 routing, the whole day plan —
consumes this answer.

## Also outstanding

- **129.9 km of required traversal is unreachable** by any closed tour: 117.4 km
  never entered L(G) (Stage 0 fragments) and 12.5 km are legal traps inside it.
  Reported, not absorbed. Under §1.1 this needs a disposition before Stage 5.
- **Variant E** (both directions everywhere, `prompts/03b`) has not been run. Stage 3
  showed the narrow-pair rule manufactures deadhead, so E may cost far less than its
  kilometre count implies — and it would retire risk R1 outright.

---

## DECIDED — 25 Aug 2026

**One car, variant C.** 33.8 days at a 10 h window, 38.5 at 9 h; either fits before
1 November. Scope: no `highway=service`.

Schedule certainty was chosen over completeness. This is the single point in the
project where §1.1 (accuracy first) was overridden, and it is recorded as such in
SPEC §2.1 rather than quietly absorbed.

The 1,150 km of through-connected service roads become **phase 2** (SPEC §2.1.1) —
deferred, not discarded, and re-includable as a config change. Budget ~25–30 days
for it as a separate campaign, more than the 174.1 h of raw work implies, because
scattered remainders route worse than contiguous ones.

Next: Stage 4 zoning, with `VARIANT = C`.

---

## CONFIRMED — variant C, after the 4b re-check

Stage 4b measured variant D at 54 days finishing 17 Oct (+13 days margin), so D
*was* feasible and the original justification for dropping it had gone. Presented
with both fitting, **variant C was chosen anyway** — 33 days, finishing 26 Sept,
+34 days margin.

This is now a deliberate preference for a shorter campaign, **not a schedule
constraint**. The 1,150 km of through-connected service roads are deferred to
phase 2 (SPEC §2.1.1) by choice. That distinction matters for the record: nothing
external is forcing this, and phase 2 remains a one-line config change
(`SCOPE_VARIANT = "D"`).

Riding along with it:

- **Shift window: 9 h (09:00–18:00)** — the originally specified window. C needs
  38 days and finishes 1 Oct with +29 days margin, against 33 days / 26 Sept /
  +34 at 10 h. Total driving is near-identical (302.6 h vs 298.6 h), so this trades
  5 calendar days for an hour's later start, with ample margin either way. Override
  if the driver prefers the earlier start.
- **Motorway narrowing: ADOPT.** 4.74 km of trapped motorway/trunk recovered by
  three manoeuvres, U1 verified exhaustively rather than sampled. Under §1.1 this
  is required, not optional — and it must happen *before* Stage 5, since it changes
  L(G) and therefore every route.

Both require the Stages 1–4 rebuild. Do it once, then Stage 5.

---

## Stage 5 actuals — supersedes the "38 days / 1 Oct" figure above

**The committed plan is 50 driving days, 2026-08-25 → 2026-10-13, 327.2 h.**
Everything earlier in this file estimating 38 days is stale; it is retained for
provenance only.

Stage 4's estimate was optimistic in two specific ways, both found by Stage 5:

- Overhead per capture hour was taken as x1.95 from Stage 3's *global* tour;
  measured per zone it is **x2.55 at p90**. A single closed tour amortises
  deadhead across the whole city; a day confined to one zone cannot.
- Stage 4 credited **12.8 h** of capture to commute legs. Stage 5 withdrew it —
  the legs run at deadhead speed and film nothing.

24 of the original 38 days overran; the zones were split to 50.

### Margin, and how to treat it

Finish 13 Oct against the 30 Oct daylight limit: **+17 days**.

SPEC §7.3's revisit trigger has fired — the campaign now lands exactly at
mid-October. It is not breached, and the shift window does not need changing. But
note the pattern across this project: **every stage that moved closer to reality
found more cost, never less.** Stage 2 discovered turn time, Stage 3 discovered
deadhead, Stage 5 discovered per-zone overhead. Actual driving is the next step
closer to reality, and it will find more.

Treat the 17 days as contingency, not slack. Do not plan to spend it.

### The plan is perishable

It is dated from 25 August. Margin decays one-for-one with every day the car is
not driving. Stages 6 and 7 do not need to be finished first — Stage 6 is *better*
built against a real day-1 trace than against a synthetic one.

---

## Stage 4c actuals — the committed plan

**47 driving days, 2026-08-25 → 2026-10-13, 321.9 h.** Margin to the 30 Oct
daylight limit: **+20 days**. Every earlier figure in this file (38 days / 1 Oct,
50 days / 13 Oct) is superseded and retained only for provenance.

Capture is unchanged at 139.3 h, as it must be — the same streets are filmed
either way. Only the driving between them moved: deadhead −4.9 h, turns −0.5 h.

### Root cause, corrected

The Stage 4c brief assumed zone sizing "had never been run with the correct
numbers". Wrong — 2.55 *was* recorded from Stage 5. The actual defect was that
2.55 is **the wrong quantity**: it came from `route_h / capture_h`, which already
includes depot legs, while `zoning.zone_durations` adds legs as a separate term.
Every zone paid for its depot legs twice.

### Why 3 days and not the ten the slack implied

Achieved intra-zone overhead runs from **1.70 to 3.16** — a long tail. A single
global constant cannot serve both ends: size for the median and the tail zones
overrun (each split turning one oversized zone into two undersized ones), size for
the tail and every well-behaved zone starves. The remaining slack is not in the
constant. It is in the partitioner not knowing which zones are intrinsically
expensive *before* it cuts them.

That is the shape of any future gain here: **predict per-zone overhead from local
topology** (dead-end density, junction density, one-way share) rather than applying
one number citywide. Not worth doing for this campaign.

### A standing rule — the sizing constant is pinned, not fed back

`ZONE_OVERHEAD_MEASURED` is read by Stage 4 and written by Stage 5. **This loop
does not converge**: the adopted plan was sized on 2.2598 and its own p75 is
2.2030. There is no fixed point, and the partition is knife-edge sensitive —
rounding the constant moved it from 43 zones to 44.

Therefore: treat it as a **pinned calibration constant with recorded provenance**,
reviewed deliberately, never as an automatic feedback path. Do not re-run Stage 4
against whatever Stage 5 last wrote and assume the result is more correct. It is
merely different.
