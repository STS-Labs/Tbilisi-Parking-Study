"""Stage 8 — coverage credit that crosses day boundaries.

Stage 4 assigns each required arc to one day and Stage 5 solves that day as a closed
circuit over its own zone, so **credit is per-day**: the car drives a street on day 3
while repositioning, earns nothing for it, and comes back on day 7 to film it.
Measured across the four campaigns that is 7.5%–13.3% of all driving, and 42.8 h on
Tbilisi alone.

The fix is a credit rule, not a camera rule. The camera is already on; the binding
constraint is `capture_speed_max = 40 km/h` (SPEC §5). So:

> Any traversal of a required arc, in a permitted direction, at or below the capture
> speed, discharges that requirement — on whatever day it happens.

**Credit is not free, and this module's whole job is to keep that honest.** Crediting
a pass the plan was going to drive fast means driving it slowly instead, which costs
`capture_time - deadhead_time` on that day and can push the day past its window. Every
function here charges that difference before it banks anything.

Three things are deliberately *not* done here:

**No new geometry, no new manoeuvres.** Stage 8 re-solves days with `routes.solve_zone`
over the same `L*` Stage 5 uses, so every tour it produces is legal by the same
construction. It changes *what a day is required to film*, never what it may drive.

**No credit the driver cannot deliver.** Whether a planned pass counts is decided by
`coverage.qualifies` — the same function that decides whether a *driven* GPS pass
counts in Stage 6. One function, two callers, so plan-time and run-time crediting
cannot drift apart. A plan that banked coverage the rig does not deliver would be the
Stage 6 failure arriving a stage early and much harder to see.

**No un-crediting of a day's own work.** A day must still film the zone it was given.
Only *bonus* credit — passes over arcs belonging to some other day — is optional, and
only bonus credit is dropped when a day runs out of window.
"""

from __future__ import annotations

import numpy as np

from . import config as C
from . import coverage


def edge_costs(star) -> tuple[np.ndarray, np.ndarray]:
    """Per-arc-node capture and deadhead seconds, as `L*` prices them.

    Read off the same cost vector the solver optimised, rather than recomputed, so a
    Stage 8 saving can never be an artefact of costing the tour differently from the
    tour that was solved.
    """
    n = star.n_arc_nodes
    return star.cost_s[:n].copy(), star.cost_s[n : 2 * n].copy()


def requirement_carrier(oriented_lower: np.ndarray, partner: np.ndarray) -> np.ndarray:
    """For every arc node, the node whose requirement a traversal of it discharges.

    `orientation.orient` resolves each narrow two-way pair to a single direction and
    puts the requirement there, because the pair is one street and filming it once is
    enough (SPEC §2.2). The *other* direction is therefore also a permitted direction
    for that requirement — driving it discharges the street just as well, and
    `coverage.requirement_key` already says so for GPS traces.

    Stage 5 cannot use that: its lower bound sits on one specific node and the flow
    has to satisfy it there. Stage 8 can, because it is crediting rather than
    constraining. This is a real extra saving and not a liberty: it is the same rule
    Stage 6 applies to a driven trace.

    Returns `-1` where a traversal discharges nothing.
    """
    n = len(oriented_lower)
    carrier = np.full(n, -1, dtype="int64")
    carrier[oriented_lower > 0] = np.flatnonzero(oriented_lower > 0)
    twin = np.asarray(partner[:n], dtype="int64")
    has_twin = (twin >= 0) & (twin < n)
    # A node with no requirement of its own still discharges its partner's.
    borrow = has_twin & (carrier < 0)
    carrier[borrow] = np.where(oriented_lower[twin[borrow]] > 0, twin[borrow], -1)
    return carrier


def take_credit(counts, remaining, day_lower, carrier):
    """What one solved day can discharge, split into its own work and bonus.

    `own` is what the day was routed to film and is already priced at capture speed by
    `tourcheck.tour_time_s`. `bonus` is everything else the tour happened to drive
    that some other day still owes — the passes this stage exists to harvest.

    Nodes are visited in index order so that two directions of the same street cannot
    both claim the one requirement, and so that the answer does not depend on
    dictionary ordering (CLAUDE.md rule 5).
    """
    counts = np.asarray(counts, dtype="int64")
    remaining = np.asarray(remaining, dtype="int64")
    n = len(remaining)
    own = np.minimum(counts[:n], day_lower[:n])
    bonus = np.zeros(n, dtype="int64")
    left = remaining.copy()

    # The day's own requirement is discharged first; it is not optional.
    for node in np.flatnonzero(own):
        target = carrier[node]
        if target < 0:
            target = node
        taken = min(int(own[node]), int(left[target]))
        left[target] -= taken

    for node in np.flatnonzero(counts[:n]):
        target = carrier[node]
        if target < 0 or left[target] <= 0:
            continue
        spare = int(counts[node]) - int(own[node])
        if spare <= 0:
            continue
        taken = min(spare, int(left[target]))
        bonus[node] += taken
        left[target] -= taken
    return own, bonus, left


def marginal_cost_s(capture_cost: np.ndarray, deadhead_cost: np.ndarray) -> np.ndarray:
    """What one bonus credit costs: the slowdown from deadhead speed to capture speed.

    Never negative — `lstar.build` refuses a network where deadhead is dearer than
    capture — and exactly zero on `capture_quality = "reduced"` arcs, where SPEC §3.2
    films at prevailing speed and the 40 km/h rule does not apply. Those credits are
    free and are the last ones this module will ever give up.
    """
    return np.maximum(capture_cost - deadhead_cost, 0.0)


def fit_bonus(bonus: np.ndarray, marginal: np.ndarray, budget_s: float):
    """Keep as much bonus credit as the day's remaining window can pay for.

    Dearest passes go first. A cheap credit buys exactly the same coverage as an
    expensive one — one street, filmed — so when the window binds, the credits worth
    keeping are the ones that cost the least time, and free `reduced` credits are
    never given up at all.
    """
    kept = np.asarray(bonus, dtype="int64").copy()
    total = float((kept * marginal).sum())
    if total <= budget_s + 1e-9:
        return kept, total
    for node in np.argsort(-marginal, kind="stable"):
        step = float(marginal[node])
        if step <= 0.0:
            break  # everything cheaper is free; dropping it would buy nothing
        while kept[node] > 0 and total > budget_s + 1e-9:
            kept[node] -= 1
            total -= step
        if total <= budget_s + 1e-9:
            break
    return kept, max(total, 0.0)


def check_i9(credited: np.ndarray, arc_ids, capture_speed_kmh, quality) -> list[dict]:
    """I9 — every pass counted as credit satisfies the Stage 6 rule.

    Asserted against `coverage.qualifies`, the function Stage 6 uses on real traces,
    rather than against a restatement of it. A planned pass is `through`, full-length
    and in a permitted direction by construction; what is *not* free is the speed,
    and that is the whole point of checking.
    """
    failures: list[dict] = []
    for node in np.flatnonzero(np.asarray(credited)):
        reason = coverage.qualifies(
            coverage.Pass(arc_id=str(arc_ids[node]),
                          speed_kmh=float(capture_speed_kmh[node])),
            str(quality[node]),
        )
        if reason != "counted":
            failures.append({"node": int(node), "arc_id": str(arc_ids[node]),
                             "reason": reason,
                             "speed_kmh": float(capture_speed_kmh[node])})
    return failures


def check_i10(bonus: np.ndarray, marginal: np.ndarray, charged_s: float) -> dict:
    """I10 — every arc credited on a deadhead pass is costed at capture time.

    The saving this stage reports is exactly the time it did *not* have to spend
    revisiting a street. If a bonus credit were taken without paying the slowdown, the
    saving would be that slowdown twice over — once by not paying it and once by not
    driving the street again — and the plan would be fiction.
    """
    owed = float((np.asarray(bonus) * marginal).sum())
    return {"owed_s": owed, "charged_s": float(charged_s),
            "ok": abs(owed - float(charged_s)) < 1e-6}


def outstanding_by_arc(remaining: np.ndarray, arc_ids) -> dict:
    """The remainder in the shape Stages 4 and 5 already know how to read.

    `pipeline._outstanding_passes` reduces a requirement by `06-outstanding.json`, so
    writing the remainder in that shape lets a re-plan happen through the existing
    path instead of a second one built for this stage.
    """
    owed: dict[str, int] = {}
    for node in np.flatnonzero(np.asarray(remaining)):
        key = str(arc_ids[node])
        owed[key] = max(owed.get(key, 0), int(remaining[node]))
    return owed


def summarise(days: list[dict], baseline: dict | None) -> dict:
    """Tier result, and what it bought against the incumbent."""
    route_h = sum(d["route_h"] for d in days)
    out = {
        "days": len(days),
        "route_h": route_h,
        "capture_h": sum(d["capture_h"] for d in days),
        "deadhead_h": sum(d["deadhead_h"] for d in days),
        "turn_h": sum(d["turn_h"] for d in days),
        "slowing_h": sum(d.get("slowing_h", 0.0) for d in days),
        "bonus_passes": sum(d.get("bonus_passes", 0) for d in days),
        "bonus_km": sum(d.get("bonus_km", 0.0) for d in days),
        "days_over_window": sum(1 for d in days if d.get("over_window")),
    }
    if baseline:
        out["vs_baseline"] = {
            "days": out["days"] - baseline["days"],
            "route_h": route_h - baseline["route_h"],
            "route_pct": (100.0 * (route_h - baseline["route_h"]) / baseline["route_h"]
                          if baseline["route_h"] else 0.0),
        }
    return out


def better(candidate: dict, incumbent: dict) -> bool:
    """SPEC §8's ranking, and the brief's: fewer days wins; then fewer hours.

    A tier is adopted only if it wins outright. Ties keep the incumbent, because a
    plan already checked and reported on is worth more than an equal one that is not.
    """
    if candidate["days"] != incumbent["days"]:
        return candidate["days"] < incumbent["days"]
    return candidate["route_h"] < incumbent["route_h"] - 1e-9
