# Stage 4c — Re-zone on Stage 5's measured numbers

A cheap re-run that should recover several driving days. Do this **before** Stage 6.

## Why

The current 50-day plan is **not 50 correctly-sized zones**. It is 38 zones sized
on wrong parameters, 24 of which overran and were split under pressure. Splitting
an oversized zone yields two undersized ones, which is why utilisation is poor:

- 327.2 h over 50 days = **6.5 h of driving per day**
- The 9 h window minus a 45 min break allows **8.25 h**
- That is ~1.7 h/day unused — about **85 h**, or the best part of ten days

Stage 4 built those zones believing overhead was x1.95 and that commute legs
captured 12.8 h. Stage 5 measured x2.55 at p90 and withdrew the credit. **Zone
sizing has never been run with the correct numbers.**

## What to do

Re-run Stage 4 with:

1. Overhead factor from Stage 5's **measured per-zone distribution**, not Stage 3's
   global tour figure. Size zones on something like the p75–p90 of that
   distribution rather than the mean — an undersized zone wastes a day, an
   oversized one overruns and gets split, and the split is the more expensive
   failure.
2. **No commute capture credit.** `COMMUTE_ALLOWANCE` still governs how much room
   is reserved, but reserved room is now for reaching the zone, not for filming
   en route. Re-derive whether reserving any is still worth it — Stage 5 showed
   the capture it was reserving for does not exist.
3. Everything else unchanged: variant C, 9 h window, motorway narrowing adopted.

Then re-run Stage 5 on the new zoning.

## What to report

| | Zones | Days | Total h | Mean day h | p90 day h | Days over window | Finish |
|---|---|---|---|---|---|---|---|
| current (38→50 split) | | 50 | 327.2 | 6.5 | | 0 | 13 Oct |
| re-zoned | | | | | | | |

**The number that matters is days over window before splitting.** If the new zoning
produces few or no overruns, the sizing is right and the day count is real. If it
still overruns, the overhead model is still wrong and that is the finding.

## Gate

Same as Stage 4 and Stage 5 — all invariants, determinism, every existing test.
Additionally: **no regression.** If the re-zoned plan is not shorter than 50 days,
keep the committed plan and say so. A re-run that makes things worse must not be
adopted just because it is newer.

## Non-goal

Do not touch scope, shift window, or the motorway fix. This is a sizing correction.
