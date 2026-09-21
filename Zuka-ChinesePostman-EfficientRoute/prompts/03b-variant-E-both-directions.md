# Stage 3b — Variant E: both directions everywhere

A cheap experiment to run alongside the pending A/D/C batch. It may retire the
project's largest accuracy risk for free.

## Why

SPEC §7A (risk R1) accepts, unmeasured, that 4,095 km of streets are narrow enough
that **one pass covers both sides** — assigned on class evidence alone, with
`width` tagged on 1.6% of arcs. If that assumption is wrong anywhere, it surfaces
at footage review, after the driving.

Stage 3 has now shown that the narrow-pair rule is not as cheap as it looked: it
saves capture time but **creates deadhead**, because a street covered in one
direction still has to be left, and single-attachment trees are 100% deadhead by
construction. Variant A's deadhead is 65.1% of capture.

So the saving from the one-pass rule is smaller than the raw kilometre count
suggests — and the price of abandoning it may be much lower than assumed.

## What to run

**Variant E** — every two-way street requires **both** directions. All narrow-pair
shared requirements become two independent required arcs.

This is *easier* than what you have already built: with no orientation choice
remaining, the problem collapses to a **pure Directed Chinese Postman** on `L*`.
No heuristic, no orientation search, no generalised-routing gap. The min-cost flow
result is **exactly optimal** and the LP bound should meet it.

Scope: run E over variant D's include set as well as A's, so the comparison is
available for whichever scope is chosen.

## What to report

Alongside A/D/C in `reports/03-bounds.md`:

| Variant | capture h | turn h | deadhead h | deadhead % | total h | gap % | days |

Then the single comparison that matters:

> **E total hours ÷ A total hours.**

- If E costs **less than ~25% more** than A: recommend adopting E outright. It
  gives guaranteed complete two-sided coverage, retires risk R1 entirely, removes
  the need for any calibration drive, produces two viewpoints of every facade for
  stereo reconstruction, and is *exactly* solvable rather than heuristic.
- If E costs substantially more: R1 stands as accepted, and the calibration drive
  becomes worth reconsidering at Stage 4.

## Gate

Same invariant suite as Stage 3 (I1, I2, closure, I6, determinism). Additionally:

- Every two-way street appears in the tour in **both** directions.
- For variant E the LP lower bound and the constructive solution should coincide
  to within solver tolerance. **If they do not, one of the two is wrong** — this is
  a free correctness check on the Stage 3 machinery, since E has no relaxation gap
  to hide behind.

## Non-goals

Do not change any default. E is a measurement, reported beside A/D/C.
