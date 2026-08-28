# Stage 8 — Coverage credit and a joint multi-day solve

Read `SPEC.md`, `CLAUDE.md`, `reports/05-routes.md` and `prompts/06-coverage-tracker.md`.

## The defect

Stage 4 assigns each required arc to one specific day; Stage 5 solves each day as a
closed circuit over its own zone. **Coverage credit is therefore per-day.** The car
drives a street on day 3 while deadheading, earns nothing for it, and returns on
day 7 to film it.

Measured across the four campaigns: **7.5%–13.3% of all driving**, and **42.8 h on
Tbilisi alone**. Same-day double traversals are *not* waste — a Rural Postman tour
drives them because parity or connectivity demands it, and you cannot delete one
pass and still have a closed circuit. Only the cross-day portion is recoverable.

## The fix is a credit rule, not a camera rule

The camera is already always on. The binding constraint is
`capture_speed_max = 40 km/h` (SPEC §5). So:

> **Any traversal of a required arc, in a permitted direction, at ≤ 40 km/h,
> discharges that requirement — on whatever day it happens.**

Crediting a deadhead pass means *slowing it to 40*, which costs time on that day and
can push the day over its window. **Credit is not free. Model it, never assume it.**

---

## 1. One implementation of "covered", shared with Stage 6

Stage 6 already decides what a real GPS trace discharges. Stage 8 must **reuse that
exact code** to decide what a planned traversal discharges — same speed rule, same
bearing rule, same `capture_quality` exemption for motorway and trunk.

If plan-time and run-time crediting are implemented separately they will drift, and
the driver's real coverage will stop matching the plan's assumption. **One function,
two callers.** Assert in a test that both paths agree on a shared fixture.

## 2. "Joint multi-day solve" — what it actually means

You asked for the joint solve. Be clear about what is and is not achievable:

- A monolithic MIP over all days and all required arcs **will not solve**. Tbilisi
  is ~47 days and tens of thousands of required arcs, and Stage 3 already showed the
  LP bound is too loose to guide a branch-and-bound at this scale. Do not attempt it.
- The tractable joint formulation is **Large Neighbourhood Search over day
  assignments**: start from the incumbent plan and repeatedly *ruin* part of it and
  *recreate* it, accepting improvements. This genuinely moves work between days —
  which is the whole point — and it scales.

Required LNS move set:

| Move | Why it matters |
|---|---|
| Relocate an arc to another day | the basic unit |
| Swap arcs between two days | balance without changing day count |
| Relocate a connected fragment | single arcs move poorly in arc routing |
| **Ruin a spatial region across all days and rebuild** | the move that finds cross-day savings |
| **Merge two days** | the only move that removes a day — where the real money is |

After any move, the affected days must be **re-solved as routes** (Stage 5's solver)
and re-credited, not merely re-costed. A day whose arc set changed has a different
optimal circuit.

## 3. Build it as a ratchet — never ship a worse plan

Each tier is a complete, shippable plan. Attempt the next only on top of the last.
**Adopt a tier only if it beats the incumbent: fewer days wins; on equal days, fewer
total hours wins.** If a tier fails to improve, keep the incumbent and report it.

| Tier | What it does | Risk |
|---|---|---|
| **0** | Baseline — the existing committed plans, as the control | none |
| **1** | **Passive credit**: credit qualifying traversals the route *already* drives, then re-derive the remaining required set and re-solve later days in sequence | cannot lose; guaranteed floor |
| **2** | **Active detour**: the solver may deliberately route through still-owed arcs when the detour beats a dedicated visit later | moderate |
| **3** | **Joint LNS** over day assignments, with merge-day moves | may not improve on 2 |

Report each tier's result separately. **The value of this exercise is knowing what
each tier bought**, not just the final number — if tier 1 gets 90% of the gain, that
is the most important finding in the stage.

## 4. Order of work — do not start with Tbilisi

Build and validate on **Zone B variant C (7 days)** — small enough to iterate in
minutes. Then Run 2 (13 d), Run 1 (21 d), and **Tbilisi (47 d) last**. Tbilisi is
where the biggest absolute prize is and where a slow, wrong implementation costs the
most time to discover.

Time-box the LNS per campaign and **report the improvement curve** (best objective
vs iterations), so it is visible whether more compute would still be buying
anything.

## 5. Invariants — these change, restate them

- **I1 becomes campaign-wide**: every required arc has ≥ `min_passes` *qualifying*
  traversals somewhere in the campaign — not "on its assigned day". The old per-day
  form is now wrong and must be removed, not kept alongside.
- **New I9**: every traversal counted as credit satisfies the Stage 6 rule
  (direction, ≤ `capture_speed_max` or `capture_quality = "reduced"`).
- **New I10**: every arc credited on a deadhead pass is costed at capture time, not
  deadhead time, in the day that drives it.
- **I4 still binds**: no day exceeds its window *after* credited passes are slowed.
- Determinism: LNS must be seeded and reproducible. Same seed, same plan, byte for
  byte.

## 6. Operational consequence — the turn sheets change

Some deadhead passes become **speed-constrained**. The driver has to know which:

> "Deadhead — but hold ≤ 40 km/h, this street is still owed."

Every credited pass must carry that instruction into the turn sheet and the GPX.
A credited pass driven at 60 km/h silently un-covers a street, and nobody finds out
until footage review. This is the same failure class Stage 6 exists to prevent.

## 7. Camera policy — settled

Camera stays **on** throughout. Footage of streets outside the required set is
neither optimised for nor avoided. Log the incidental km as a line item so the
volume is known, but do not let it influence routing.

## 8. Outputs

- New output roots per campaign, e.g. `OPT-<campaign>/` — **do not overwrite any
  committed plan.** All four existing plans must still regenerate identically.
- `reports/08-optimisation.md` per campaign: tier-by-tier table, improvement curve,
  credited km, days removed, hours saved, and what each tier bought.
- `reports/08-SUMMARY.md` across all four: does the saving generalise across
  big/small and dense/sparse, or is it specific to one geometry?
- Regenerated GPX, turn sheets and playback for whichever tier is adopted.

## 9. Failure policy

If the joint solve does not beat tier 2, **say so plainly and adopt tier 2.** A
negative result here is a real finding and is worth more than a forced improvement.
Never weaken a gate or the credit rule to manufacture a saving — the whole point of
crediting is that the street genuinely got filmed.
