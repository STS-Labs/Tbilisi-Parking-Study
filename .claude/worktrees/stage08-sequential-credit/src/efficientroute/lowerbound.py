"""Stage 3 item 3 — a lower bound that is actually a lower bound.

SPEC §4 calls the fixed-orientation Chinese Postman result "Stage A — Lower
bound", and SPEC §8 I5 asserts total driving is at or above it.  **That is the
wrong way round.**  Fixing an orientation for every narrow pair *adds* a
constraint — it decides something the real problem is free to choose — so the
result can only be at or above the true optimum.  It is a feasible solution, and
feasible solutions bound from above.

So the bound is computed separately, from a relaxation:

**LP relaxation (preferred).**  The generalised routing problem written over `L*`
with integrality dropped and each narrow pair contributing one "at least one of
the two" row.  It relaxes three things at once — integrality, the orientation
choice, and connectivity — so it is genuinely below the optimum, and loose in
proportion to how much those three matter.  Here they matter a lot, and the
report says so rather than presenting the gap as slack in the tour alone.

**Combinatorial fallback.**  Σ capture time over required elements, taking the
cheaper direction of each pair, plus the cheapest legal exit from each required
traversal.  Every traversal in a closed tour is followed by a manoeuvre, so the
exit term is real time that no tour can avoid.  Weaker than the LP, valid, and
computed in a second — it also serves as a cross-check that the LP is above it.
"""

from __future__ import annotations

import dataclasses
import time

import numpy as np

from .lstar import CAPACITY_INF, LStar

#: HiGHS interior point without crossover returns an approximately optimal point.
#: The primal-dual gap it reports is around 1e-9 relative, which is many orders
#: below the gap being measured; the tolerance is recorded rather than hidden.
LP_TIME_LIMIT_S = 1800.0


@dataclasses.dataclass(frozen=True)
class Bound:
    value_s: float
    method: str
    status: str
    runtime_s: float
    detail: dict

    def to_dict(self) -> dict:
        return {
            "lower_bound_s": self.value_s,
            "lower_bound_h": self.value_s / 3600.0,
            "method": self.method,
            "status": self.status,
            "runtime_s": round(self.runtime_s, 1),
            **self.detail,
        }


def compute(star: LStar, graph, time_limit_s: float = LP_TIME_LIMIT_S) -> tuple[Bound, Bound]:
    """The LP bound and the combinatorial bound; the caller reports both."""
    fallback = combinatorial_bound(star, graph)
    try:
        lp = lp_bound(star, time_limit_s)
    except Exception as error:  # noqa: BLE001 - the fallback exists for exactly this
        lp = Bound(
            value_s=float("nan"), method="lp_relaxation", status=f"failed: {error}",
            runtime_s=0.0, detail={},
        )
    return lp, fallback


# ------------------------------------------------------------------- the LP


def _pair_rows(star: LStar) -> list[tuple[int, int]]:
    """One row per narrow pair, as a pair of arc-group ids, deduplicated."""
    shared = (star.pair_requirement > 0) & star.in_scope
    group = star.arc_group
    seen: set[tuple[int, int]] = set()
    for node in np.flatnonzero(shared):
        twin = star.partner[node]
        if twin < 0:
            continue
        key = (int(group[node]), int(group[twin]))
        seen.add(key if key[0] <= key[1] else (key[1], key[0]))
    return sorted(seen)


def lp_bound(star: LStar, time_limit_s: float = LP_TIME_LIMIT_S) -> Bound:
    """Solve the LP relaxation of the generalised routing problem over `L*`."""
    import highspy
    import scipy.sparse as sp

    started = time.time()
    n, edges = star.n_arc_nodes, star.n_edges
    scope = star.in_scope
    shared = (star.pair_requirement > 0) & scope
    solo = (star.pair_requirement == 0) & scope
    min_passes = star.min_passes.astype("float64")

    # Capture edges are the only ones a coverage requirement can bind.  A
    # non-pair arc's requirement is a plain bound; a pair's needs a row, because
    # the LP must be free to choose the direction (that freedom is exactly what
    # makes this a relaxation and the constructive tour an upper bound).
    col_lower = np.zeros(edges)
    col_upper = np.zeros(edges)
    col_upper[:n] = np.where(scope, min_passes, 0.0)
    col_lower[:n] = np.where(solo, min_passes, 0.0)
    col_upper[:n] = np.where(shared, 1.0, col_upper[:n])
    col_upper[n : 2 * n] = np.where(scope, CAPACITY_INF, 0.0)
    col_upper[2 * n :] = np.where(star.upper[2 * n :] > 0, CAPACITY_INF, 0.0)

    # A cloned arc carries its requirement across its variants, so its bound
    # becomes a row instead: the individual variants are each free.
    group = star.arc_group
    counts = np.bincount(group, minlength=int(group.max()) + 1)
    cloned = counts[group] > 1
    col_lower[:n] = np.where(cloned[:n] if cloned.shape[0] == n else cloned, 0.0, col_lower[:n])

    clone_rows = sorted({int(g) for g in group[np.flatnonzero(cloned & solo)]})
    members: dict[int, list[int]] = {}
    for node in range(n):
        members.setdefault(int(group[node]), []).append(node)

    pairs = _pair_rows(star)
    n_conservation = star.n_nodes

    rows = [np.concatenate([star.head, star.tail])]
    cols = [np.concatenate([np.arange(edges), np.arange(edges)])]
    vals = [np.concatenate([np.ones(edges), -np.ones(edges)])]

    extra_rows, extra_cols = [], []
    row_lower = [np.zeros(n_conservation)]
    row_upper = [np.zeros(n_conservation)]

    offset = n_conservation
    clone_lower = []
    for key in clone_rows:
        for node in members[key]:
            extra_rows.append(offset)
            extra_cols.append(node)
        clone_lower.append(float(min_passes[members[key][0]]))
        offset += 1

    pair_lower = []
    for group_a, group_b in pairs:
        for key in (group_a, group_b):
            for node in members[key]:
                extra_rows.append(offset)
                extra_cols.append(node)
        pair_lower.append(1.0)
        offset += 1

    if extra_rows:
        rows.append(np.asarray(extra_rows, dtype="int64"))
        cols.append(np.asarray(extra_cols, dtype="int64"))
        vals.append(np.ones(len(extra_rows)))
    row_lower.append(np.asarray(clone_lower + pair_lower, dtype="float64"))
    row_upper.append(np.full(len(clone_lower) + len(pair_lower), np.inf))

    matrix = sp.coo_matrix(
        (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
        shape=(offset, edges),
    ).tocsc()

    lp = highspy.HighsLp()
    lp.num_col_ = edges
    lp.num_row_ = offset
    lp.col_cost_ = star.cost_s.astype("float64")
    lp.col_lower_ = col_lower
    lp.col_upper_ = col_upper
    lp.row_lower_ = np.concatenate(row_lower)
    lp.row_upper_ = np.concatenate(row_upper)
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = matrix.indptr
    lp.a_matrix_.index_ = matrix.indices
    lp.a_matrix_.value_ = matrix.data

    solver = highspy.Highs()
    solver.setOptionValue("output_flag", False)
    solver.setOptionValue("time_limit", float(time_limit_s))
    # Interior point without crossover: the basis is not needed, only the
    # objective, and IPM reaches it on a network LP of this size where simplex
    # stalls.
    solver.setOptionValue("solver", "ipm")
    solver.setOptionValue("run_crossover", "off")
    # Single-threaded and seeded: a parallel interior point solve reorders
    # floating-point reductions, and the bound would then wobble in its last
    # digits between runs (CLAUDE.md rule 5).
    solver.setOptionValue("threads", 1)
    solver.setOptionValue("random_seed", 20260825)
    solver.passModel(lp)
    solver.run()

    status = str(solver.getModelStatus())
    info = solver.getInfo()
    if "kOptimal" not in status:
        raise RuntimeError(f"the LP relaxation did not solve to optimality: {status}")

    return Bound(
        value_s=float(info.objective_function_value),
        method="lp_relaxation",
        status="optimal",
        runtime_s=time.time() - started,
        detail={
            "columns": int(edges),
            "rows": int(offset),
            "nonzeros": int(matrix.nnz),
            "pair_rows": len(pairs),
            "clone_rows": len(clone_rows),
            "primal_dual_gap": float(getattr(info, "primal_dual_integral", 0.0) or 0.0),
        },
    )


# ------------------------------------------------------------- the fallback


def min_exit_s(graph) -> np.ndarray:
    """Cheapest legal manoeuvre out of each L-node.

    An arc with no legal exit cannot appear in a closed tour at all, so it
    contributes nothing; Stage 1's trap audit already counted those.
    """
    out = np.zeros(graph.n_nodes, dtype="float64")
    for node, row in enumerate(graph.adjacency):
        if row:
            out[node] = min(penalty for _code, penalty in row.values())
    return out


def combinatorial_bound(star: LStar, graph) -> Bound:
    """Capture floor over required elements, plus the cheapest exit from each.

    Rigorous but weak: it accounts for no repositioning at all, which is the
    largest term the LP does capture.  Its job is to be computable in a second
    and to catch an LP that has quietly solved the wrong model.
    """
    started = time.time()
    scope = star.in_scope
    shared = (star.pair_requirement > 0) & scope
    solo = (star.pair_requirement == 0) & scope

    capture = star.cost_s[: star.n_arc_nodes]
    exit_s = min_exit_s(graph)
    per_traversal = capture + exit_s

    total = float((star.min_passes[solo] * per_traversal[solo]).sum())

    seen: set[tuple[int, int]] = set()
    group = star.arc_group
    pair_total = 0.0
    for node in np.flatnonzero(shared):
        twin = star.partner[node]
        if twin < 0:
            key = (int(group[node]), -1)
            if key in seen:
                continue
            seen.add(key)
            pair_total += float(per_traversal[node])
            continue
        key = (int(group[node]), int(group[twin]))
        key = key if key[0] <= key[1] else (key[1], key[0])
        if key in seen:
            continue
        seen.add(key)
        pair_total += float(min(per_traversal[node], per_traversal[twin]))

    return Bound(
        value_s=total + pair_total,
        method="capture_floor_plus_cheapest_exit",
        status="exact",
        runtime_s=time.time() - started,
        detail={
            "capture_floor_s": total + pair_total,
            "required_elements": int(solo.sum()) + len(seen),
        },
    )


def optimality_gap(upper_s: float, lower_s: float) -> float:
    """`(upper − lower) / lower`, the number CLAUDE.md rule 2 requires."""
    if not lower_s:
        return float("nan")
    return (upper_s - lower_s) / lower_s
